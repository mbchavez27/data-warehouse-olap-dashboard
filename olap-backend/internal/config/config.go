package config

import (
	"bufio"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Port         string
	DWHost       string
	DWPort       string
	DWName       string
	DWUser       string
	DWPassword   string
	DWSSLMode    string
	QueriesDir   string
	QueryTimeout time.Duration
	MaxConns     int32
	CORSOrigins  []string
}


func Load() (Config, error) {
	for _, path := range []string{".env", filepath.Join("..", ".env")} {
		if err := loadDotEnv(path); err != nil {
			return Config{}, err
		}
	}

	timeout, err := time.ParseDuration(get("QUERY_TIMEOUT", "60s"))
	if err != nil {
		return Config{}, fmt.Errorf("QUERY_TIMEOUT: %w", err)
	}
	maxConns, err := strconv.Atoi(get("DW_MAX_CONNS", "8"))
	if err != nil || maxConns < 1 {
		return Config{}, fmt.Errorf("DW_MAX_CONNS must be a positive integer")
	}
	queriesDir, err := findQueriesDir(os.Getenv("OLAP_QUERIES_DIR"))
	if err != nil {
		return Config{}, err
	}

	return Config{
		Port:         get("API_PORT", get("PORT", "8080")),
		DWHost:       get("DW_HOST", "localhost"),
		DWPort:       get("DW_PORT", "5434"),
		DWName:       get("DW_DB", "dw_db"),
		DWUser:       get("DW_USER", "postgres"),
		DWPassword:   get("DW_PASSWORD", "postgres"),
		DWSSLMode:    get("DW_SSLMODE", "disable"),
		QueriesDir:   queriesDir,
		QueryTimeout: timeout,
		MaxConns:     int32(maxConns),
		CORSOrigins:  splitList(get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")),
	}, nil
}

// DSN is the warehouse connection URL. The password is escaped, so any
// character is safe in it.
func (c Config) DSN() string {
	u := url.URL{
		Scheme:   "postgres",
		User:     url.UserPassword(c.DWUser, c.DWPassword),
		Host:     c.DWHost + ":" + c.DWPort,
		Path:     "/" + c.DWName,
		RawQuery: url.Values{"sslmode": {c.DWSSLMode}}.Encode(),
	}
	return u.String()
}

func get(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok && strings.TrimSpace(v) != "" {
		return strings.TrimSpace(v)
	}
	return fallback
}

func splitList(s string) []string {
	var out []string
	for _, part := range strings.Split(s, ",") {
		if part = strings.TrimSpace(part); part != "" {
			out = append(out, part)
		}
	}
	return out
}

// findQueriesDir locates olap/queries, the single source of the report SQL.
// The API runs from olap-backend/ (README) or from the repository root.
func findQueriesDir(explicit string) (string, error) {
	candidates := []string{filepath.Join("..", "olap", "queries"), filepath.Join("olap", "queries")}
	if explicit != "" {
		candidates = []string{explicit}
	}
	for _, dir := range candidates {
		if info, err := os.Stat(dir); err == nil && info.IsDir() {
			return filepath.Abs(dir)
		}
	}
	return "", fmt.Errorf("query directory not found (tried %s); set OLAP_QUERIES_DIR", strings.Join(candidates, ", "))
}

func loadDotEnv(path string) error {
	f, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		line = strings.TrimPrefix(line, "export ")
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		value = strings.TrimSpace(value)
		if len(value) >= 2 && (value[0] == '"' || value[0] == '\'') && value[len(value)-1] == value[0] {
			value = value[1 : len(value)-1]
		}
		if _, exists := os.LookupEnv(key); !exists {
			os.Setenv(key, value)
		}
	}
	return scanner.Err()
}
