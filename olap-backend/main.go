// Command olap-backend serves the OLAP reports in olap/queries as a JSON API
// for the dashboard.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"olap-backend/internal/api"
	"olap-backend/internal/config"
	"olap-backend/internal/reports"
)

func main() {
	log := slog.New(slog.NewTextHandler(os.Stdout, nil))
	if err := run(log); err != nil {
		log.Error("server stopped", "err", err)
		os.Exit(1)
	}
}

func run(log *slog.Logger) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	statements, err := reports.LoadStatements(cfg.QueriesDir)
	if err != nil {
		return err
	}
	log.Info("loaded report queries", "dir", cfg.QueriesDir, "count", len(statements))

	pool, err := newPool(cfg)
	if err != nil {
		return err
	}
	defer pool.Close()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	if err := pool.Ping(pingCtx); err != nil {
		// Keep serving: /api/health reports the outage and requests recover
		// once the warehouse container is up.
		log.Warn("warehouse not reachable yet", "host", cfg.DWHost, "port", cfg.DWPort, "db", cfg.DWName, "err", err)
	} else {
		log.Info("connected to warehouse", "host", cfg.DWHost, "port", cfg.DWPort, "db", cfg.DWName)
	}
	cancel()

	service := reports.NewService(pool, statements, cfg.QueryTimeout)
	server := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           api.NewServer(service, pool.Ping, cfg.CORSOrigins, log).Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		WriteTimeout:      cfg.QueryTimeout + 10*time.Second,
		IdleTimeout:       60 * time.Second,
	}

	errs := make(chan error, 1)
	go func() {
		log.Info("OLAP API listening", "url", "http://localhost:"+cfg.Port)
		errs <- server.ListenAndServe()
	}()

	select {
	case err := <-errs:
		if !errors.Is(err, http.ErrServerClosed) {
			return err
		}
	case <-ctx.Done():
		log.Info("shutting down")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		return server.Shutdown(shutdownCtx)
	}
	return nil
}

func newPool(cfg config.Config) (*pgxpool.Pool, error) {
	poolCfg, err := pgxpool.ParseConfig(cfg.DSN())
	if err != nil {
		return nil, err
	}
	poolCfg.MaxConns = cfg.MaxConns
	params := poolCfg.ConnConfig.RuntimeParams
	params["application_name"] = "olap-backend"
	params["default_transaction_read_only"] = "on"
	params["plan_cache_mode"] = "force_custom_plan"
	return pgxpool.NewWithConfig(context.Background(), poolCfg)
}
