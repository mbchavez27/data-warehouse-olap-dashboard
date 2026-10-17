//	GET /api/health                         service and warehouse status
//	GET /api/reports                        catalog: reports, levels, parameters
//	GET /api/reports/{report}/{level}?...   run one level with filters
//	GET /api/dimensions                     filter values (years, categories, ...)
//	GET /api/dimensions/cities?country=...  cities of one country

package api

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgconn"

	"olap-backend/internal/reports"
)

// Backend is what the handlers need from the warehouse side.
type Backend interface {
	Run(ctx context.Context, r reports.Report, l reports.Level, raw map[string][]string) (*reports.Result, error)
	Dimensions(ctx context.Context) (map[string][]string, error)
	Cities(ctx context.Context, country string) ([]string, error)
}

type Server struct {
	backend     Backend
	ping        func(context.Context) error
	corsOrigins []string
	log         *slog.Logger
}

func NewServer(backend Backend, ping func(context.Context) error, corsOrigins []string, log *slog.Logger) *Server {
	return &Server{backend: backend, ping: ping, corsOrigins: corsOrigins, log: log}
}

// Handler returns the routed handler wrapped in CORS and request logging.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/health", s.health)
	mux.HandleFunc("GET /api/reports", s.catalog)
	mux.HandleFunc("GET /api/reports/{report}", s.report)
	mux.HandleFunc("GET /api/reports/{report}/{level}", s.runLevel)
	mux.HandleFunc("GET /api/dimensions", s.dimensions)
	mux.HandleFunc("GET /api/dimensions/cities", s.cities)
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeError(w, http.StatusNotFound, "not found", nil)
	})
	return s.logRequests(s.cors(mux))
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	if err := s.ping(ctx); err != nil {
		s.log.Warn("warehouse unreachable", "err", err)
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "degraded", "database": "unreachable"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "database": "ok"})
}

func (s *Server) catalog(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"reports": reports.Catalog})
}

func (s *Server) report(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("report")
	for _, rep := range reports.Catalog {
		if rep.ID == id || rep.Folder == id {
			writeJSON(w, http.StatusOK, rep)
			return
		}
	}
	writeError(w, http.StatusNotFound, "unknown report "+quote(id), nil)
}

func (s *Server) runLevel(w http.ResponseWriter, r *http.Request) {
	reportID, levelID := r.PathValue("report"), r.PathValue("level")
	rep, level, ok := reports.Find(reportID, levelID)
	if !ok {
		if rep.ID == "" {
			writeError(w, http.StatusNotFound, "unknown report "+quote(reportID), nil)
		} else {
			writeError(w, http.StatusNotFound, "unknown level "+quote(levelID)+" for report "+rep.ID, nil)
		}
		return
	}

	result, err := s.backend.Run(r.Context(), rep, level, r.URL.Query())
	var invalid *reports.ValidationError
	switch {
	case errors.As(err, &invalid):
		// The dashboard shows only "error", so it carries the problems too.
		writeError(w, http.StatusBadRequest, "Invalid filters: "+invalid.Error(), invalid.Problems)
	case errors.Is(err, context.DeadlineExceeded):
		s.log.Error("query timed out", "report", rep.ID, "level", level.ID)
		writeError(w, http.StatusGatewayTimeout, "The report took too long to run. Try narrowing the filters.", nil)
	case errors.Is(err, context.Canceled):
		// Client went away; nothing useful to send.
	case isConnectError(err):
		s.log.Error("warehouse unreachable", "report", rep.ID, "level", level.ID, "err", err)
		writeError(w, http.StatusServiceUnavailable, "The data warehouse is not reachable. Check that the dw_db container is running.", nil)
	case err != nil:
		s.log.Error("query failed", "report", rep.ID, "level", level.ID, "err", err)
		writeError(w, http.StatusInternalServerError, "The report query failed. See the API log for details.", nil)
	default:
		writeJSON(w, http.StatusOK, result)
	}
}

func (s *Server) dimensions(w http.ResponseWriter, r *http.Request) {
	dims, err := s.backend.Dimensions(r.Context())
	if err != nil {
		s.log.Error("dimension lookup failed", "err", err)
		writeError(w, http.StatusInternalServerError, "dimension lookup failed", nil)
		return
	}
	writeJSON(w, http.StatusOK, dims)
}

func (s *Server) cities(w http.ResponseWriter, r *http.Request) {
	country := strings.TrimSpace(r.URL.Query().Get("country"))
	if country == "" {
		writeError(w, http.StatusBadRequest, "country is required", nil)
		return
	}
	cities, err := s.backend.Cities(r.Context(), country)
	if err != nil {
		s.log.Error("city lookup failed", "err", err)
		writeError(w, http.StatusInternalServerError, "city lookup failed", nil)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"country": country, "cities": cities})
}

func (s *Server) cors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" && (slices.Contains(s.corsOrigins, "*") || slices.Contains(s.corsOrigins, origin)) {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Vary", "Origin")
			w.Header().Set("Access-Control-Allow-Methods", "GET, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		}
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

func (s *Server) logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		started := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r)
		s.log.Info("request", "method", r.Method, "path", r.URL.Path, "query", r.URL.RawQuery,
			"status", rec.status, "ms", time.Since(started).Milliseconds())
	})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, message string, details []string) {
	body := map[string]any{"error": message}
	if len(details) > 0 {
		body["details"] = details
	}
	writeJSON(w, status, body)
}

func isConnectError(err error) bool {
	var connectErr *pgconn.ConnectError
	return errors.As(err, &connectErr)
}

func quote(s string) string {
	return "'" + s + "'"
}
