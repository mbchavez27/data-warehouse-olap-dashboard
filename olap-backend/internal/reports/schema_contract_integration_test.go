//go:build integration

// Prepares every report query against an empty copy of the warehouse schema
// and compares the columns Postgres reports with the ones the catalog
// declares. CI cannot load the warehouse (the source archive is not in the
// repository), but it can apply the DDL, and planning a statement needs the
// tables, not their rows.
//
//	DW_TEST_DSN='postgres://postgres:postgres@localhost:5434/dw_db?sslmode=disable' \
//	  go test -tags integration ./internal/reports/
//
// Without DW_TEST_DSN the test skips, so `go test ./...` stays database-free.
// api-tests.yml runs it against a postgres service container.
package reports

import (
	"context"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
)

// testSchema is a throwaway schema the test owns; it never touches a loaded
// warehouse, so it is safe to point DW_TEST_DSN at a real one.
const testSchema = "dw_query_contract"

func TestQueriesMatchCatalogAgainstSchema(t *testing.T) {
	dsn := os.Getenv("DW_TEST_DSN")
	if dsn == "" {
		t.Skip("set DW_TEST_DSN to a Postgres this test may create a throwaway schema in")
	}

	ctx := context.Background()
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	// Cleanups run last-in-first-out, so the schema is dropped before the
	// connection that owns it is closed.
	t.Cleanup(func() { conn.Close(context.Background()) })

	ddl, err := os.ReadFile(repoFile(t, filepath.Join("db", "dw", "init", "01_dw_schema.sql")))
	if err != nil {
		t.Fatal(err)
	}

	exec := func(sql string) {
		t.Helper()
		if _, err := conn.PgConn().Exec(ctx, sql).ReadAll(); err != nil {
			t.Fatalf("exec %q: %v", sql, err)
		}
	}
	exec(`DROP SCHEMA IF EXISTS ` + testSchema + ` CASCADE`)
	exec(`CREATE SCHEMA ` + testSchema)
	t.Cleanup(func() {
		if _, err := conn.PgConn().Exec(context.Background(), `DROP SCHEMA IF EXISTS `+testSchema+` CASCADE`).ReadAll(); err != nil {
			t.Errorf("dropping %s: %v", testSchema, err)
		}
	})
	// The DDL is unqualified, so it lands in the throwaway schema and every
	// query below resolves against it.
	exec(`SET search_path TO ` + testSchema)
	exec(string(ddl))
	// The reports read the AGG_* views that 03_preagg.sql builds, so the schema
	// needs them too. The views are empty here; planning only needs their names
	// and columns.
	preagg, err := os.ReadFile(repoFile(t, filepath.Join("db", "dw", "optimize", "03_preagg.sql")))
	if err != nil {
		t.Fatal(err)
	}
	exec(stripPsqlMetaCommands(string(preagg)))

	statements, err := LoadStatements(repoFile(t, filepath.Join("olap", "queries")))
	if err != nil {
		t.Fatal(err)
	}

	for _, report := range Catalog {
		for _, level := range report.Levels {
			t.Run(level.File, func(t *testing.T) {
				stmt, ok := statements[level.File]
				if !ok {
					t.Fatalf("no statement loaded for %s", level.File)
				}
				// Parse and describe only: nothing is executed, so an empty
				// warehouse is enough.
				desc, err := conn.Prepare(ctx, "", stmt.SQL)
				if err != nil {
					t.Fatalf("prepare: %v", err)
				}

				got := make([]string, len(desc.Fields))
				for i, field := range desc.Fields {
					got[i] = field.Name
				}
				if !slices.Equal(got, level.Columns) {
					t.Errorf("the SQL returns\n  %v\nbut the catalog declares\n  %v", got, level.Columns)
				}
				if len(desc.ParamOIDs) != len(stmt.Names) {
					t.Errorf("the SQL takes %d parameters, the catalog binds %d %v", len(desc.ParamOIDs), len(stmt.Names), stmt.Names)
				}
			})
		}
	}
}

// stripPsqlMetaCommands drops psql backslash commands (such as \timing on).
// The server cannot run them, and the SQL files are written for psql.
func stripPsqlMetaCommands(sql string) string {
	var kept []string
	for _, line := range strings.Split(sql, "\n") {
		if !strings.HasPrefix(strings.TrimSpace(line), `\`) {
			kept = append(kept, line)
		}
	}
	return strings.Join(kept, "\n")
}

// repoFile walks up from the test's directory to the path inside the
// repository, so the test does not depend on the working directory.
func repoFile(t *testing.T, rel string) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	for {
		candidate := filepath.Join(dir, rel)
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatalf("%s not found above %s", rel, dir)
		}
		dir = parent
	}
}
