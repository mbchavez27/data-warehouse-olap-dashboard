package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"olap-backend/internal/reports"
)

type fakeBackend struct {
	runErr error
}

func (f fakeBackend) Run(_ context.Context, r reports.Report, l reports.Level, raw map[string][]string) (*reports.Result, error) {
	bound, err := reports.Validate(l, raw)
	if err != nil {
		return nil, err
	}
	if f.runErr != nil {
		return nil, f.runErr
	}
	return &reports.Result{Report: r.ID, Level: l.ID, Params: bound, Rows: []map[string]any{{"x": 1}}, RowCount: 1}, nil
}

func (fakeBackend) Dimensions(context.Context) (map[string][]string, error) {
	return map[string][]string{"years": {"2024", "2025"}}, nil
}

func (fakeBackend) Cities(_ context.Context, country string) ([]string, error) {
	return []string{"Manila"}, nil
}

func newTestServer(backend Backend, pingErr error) http.Handler {
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	ping := func(context.Context) error { return pingErr }
	return NewServer(backend, ping, []string{"http://localhost:3000"}, log).Handler()
}

func get(t *testing.T, h http.Handler, path string) (*httptest.ResponseRecorder, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, path, nil)
	req.Header.Set("Origin", "http://localhost:3000")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("%s: invalid JSON %q", path, rec.Body.String())
	}
	return rec, body
}

func TestRoutes(t *testing.T) {
	h := newTestServer(fakeBackend{}, nil)
	cases := []struct {
		path   string
		status int
	}{
		{"/api/health", 200},
		{"/api/reports", 200},
		{"/api/reports/r2", 200},
		{"/api/reports/r9", 404},
		{"/api/reports/r1/category?year=2025&vehicle=Car", 200},
		{"/api/reports/r1_product_category_value/product?category=Toys&top_n=5", 200},
		{"/api/reports/r1/category?year=1999", 400},
		{"/api/reports/r2/pivot?measure=per_rider&year=2025", 200},
		{"/api/reports/r2/cube?courier=JNT", 200},
		{"/api/reports/r2/courier_vehicle_cube", 200},
		{"/api/reports/r1/nope", 404},
		{"/api/dimensions", 200},
		{"/api/dimensions/cities?country=Philippines", 200},
		{"/api/dimensions/cities", 400},
		{"/elsewhere", 404},
	}
	for _, c := range cases {
		rec, _ := get(t, h, c.path)
		if rec.Code != c.status {
			t.Errorf("%s: status %d, want %d (%s)", c.path, rec.Code, c.status, rec.Body.String())
		}
		if rec.Header().Get("Access-Control-Allow-Origin") != "http://localhost:3000" {
			t.Errorf("%s: missing CORS header", c.path)
		}
	}
}

func TestRunLevelBody(t *testing.T) {
	h := newTestServer(fakeBackend{}, nil)
	_, body := get(t, h, "/api/reports/r4/trend?level=day")
	params := body["params"].(map[string]any)
	if params["level"] != "day" || params["year"] != "" {
		t.Fatalf("params = %v", params)
	}

	_, body = get(t, h, "/api/reports/r4/trend?level=hour&foo=1")
	if details, _ := body["details"].([]any); len(details) != 2 {
		t.Fatalf("expected 2 validation problems, got %v", body)
	}
	// The dashboard shows only "error", so it must name the problem.
	if msg, _ := body["error"].(string); !strings.Contains(msg, "level must be one of") {
		t.Fatalf("error does not explain the problem: %q", msg)
	}
}

func TestErrorsAreNotLeaked(t *testing.T) {
	h := newTestServer(fakeBackend{runErr: errors.New("pq: password authentication failed")}, nil)
	rec, body := get(t, h, "/api/reports/r1/category")
	if rec.Code != 500 || strings.Contains(body["error"].(string), "password") {
		t.Fatalf("got %d %v", rec.Code, body)
	}

	h = newTestServer(fakeBackend{runErr: context.DeadlineExceeded}, nil)
	if rec, _ := get(t, h, "/api/reports/r1/category"); rec.Code != http.StatusGatewayTimeout {
		t.Fatalf("timeout status %d", rec.Code)
	}
}

func TestHealthDegraded(t *testing.T) {
	h := newTestServer(fakeBackend{}, errors.New("connection refused"))
	rec, body := get(t, h, "/api/health")
	if rec.Code != http.StatusServiceUnavailable || body["database"] != "unreachable" {
		t.Fatalf("got %d %v", rec.Code, body)
	}
}

func TestCORSRejectsOtherOrigins(t *testing.T) {
	h := newTestServer(fakeBackend{}, nil)
	req := httptest.NewRequest(http.MethodOptions, "/api/reports", nil)
	req.Header.Set("Origin", "http://evil.example")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatal("unexpected CORS grant")
	}
}
