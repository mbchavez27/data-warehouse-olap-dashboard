package reports

import (
	"errors"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

var queriesDir = filepath.Join("..", "..", "..", "olap", "queries")

func TestTranslateReusesPlaceholders(t *testing.T) {
	stmt := Translate("SELECT 1 WHERE (:'year' = '' OR y = nullif(:'year', '')::int) AND :'month' = '';\n")
	want := "SELECT 1 WHERE ($1::text = '' OR y = nullif($1::text, '')::int) AND $2::text = ''"
	if stmt.SQL != want {
		t.Fatalf("SQL:\n got %q\nwant %q", stmt.SQL, want)
	}
	if !slices.Equal(stmt.Names, []string{"year", "month"}) {
		t.Fatalf("Names = %v", stmt.Names)
	}
}

// Every query file must use exactly the parameters the catalog declares,
// and nothing psql-specific may survive translation.
func TestCatalogMatchesQueryFiles(t *testing.T) {
	statements, err := LoadStatements(queriesDir)
	if err != nil {
		t.Fatal(err)
	}
	for file, stmt := range statements {
		if strings.Contains(stmt.SQL, ":'") {
			t.Errorf("%s: untranslated psql parameter left in SQL", file)
		}
		if strings.HasSuffix(stmt.SQL, ";") {
			t.Errorf("%s: trailing semicolon left in SQL", file)
		}
	}
	levels := 0
	for _, r := range Catalog {
		levels += len(r.Levels)
	}
	if len(statements) != levels {
		t.Fatalf("loaded %d statements for %d levels", len(statements), levels)
	}
}

func TestFind(t *testing.T) {
	if _, l, ok := Find("r1", "product"); !ok || l.File != "r1_product_category_value/product.sql" {
		t.Fatal("r1/product not found")
	}
	if _, _, ok := Find("r4_demand_calendar", "trend"); !ok {
		t.Fatal("folder name should also resolve")
	}
	if _, l, ok := Find("r2", "pivot"); !ok || l.ID != "courier_vehicle_pivot" {
		t.Fatal("dashboard alias r2/pivot should resolve")
	}
	if _, l, ok := Find("r2", "cube"); !ok || l.ID != "courier_vehicle_cube" {
		t.Fatal("dashboard alias r2/cube should resolve")
	}
	if r, _, ok := Find("r2", "nope"); ok || r.ID != "r2" {
		t.Fatal("unknown level should return the report but not ok")
	}
	if r, _, ok := Find("r9", "trend"); ok || r.ID != "" {
		t.Fatal("unknown report should return nothing")
	}
}

func level(t *testing.T, report, id string) Level {
	t.Helper()
	_, l, ok := Find(report, id)
	if !ok {
		t.Fatalf("%s/%s missing", report, id)
	}
	return l
}

func TestValidateFillsEveryParam(t *testing.T) {
	l := level(t, "r1", "category")
	bound, err := Validate(l, map[string][]string{"year": {" 2025 "}, "vehicle": {"Motorcycle"}})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]string{"year": "2025", "quarter": "", "month": "", "vehicle": "Motorcycle", "size_group": ""}
	for k, v := range want {
		if bound[k] != v {
			t.Errorf("%s = %q, want %q", k, bound[k], v)
		}
	}
	if len(bound) != len(want) {
		t.Errorf("bound = %v", bound)
	}
}

func TestValidateRejects(t *testing.T) {
	cases := []struct {
		report, level string
		raw           map[string][]string
		problem       string
	}{
		{"r1", "category", map[string][]string{"year": {"2023"}}, "year must be one of"},
		{"r1", "category", map[string][]string{"bogus": {"1"}}, `unknown parameter "bogus"`},
		{"r1", "category", map[string][]string{"year": {"2024", "2025"}}, "more than once"},
		{"r1", "product", map[string][]string{"top_n": {"0"}}, "top_n must be an integer"},
		{"r1", "product", map[string][]string{"top_n": {"10; DROP TABLE x"}}, "top_n must be an integer"},
		{"r1", "product", map[string][]string{"category": {strings.Repeat("x", 129)}}, "at most 128"},
		{"r3", "geography", map[string][]string{"level": {"city"}}, "requires country"},
		{"r3", "customer", map[string][]string{"city": {"Manila"}}, "city requires country"},
		{"r3", "customer", map[string][]string{"decile": {"11"}}, "decile must be an integer from 1 to 10"},
		{"r4", "trend", map[string][]string{"level": {"hour"}}, "level must be one of"},
	}
	for _, c := range cases {
		_, err := Validate(level(t, c.report, c.level), c.raw)
		var v *ValidationError
		if !errors.As(err, &v) {
			t.Errorf("%s/%s %v: expected ValidationError, got %v", c.report, c.level, c.raw, err)
			continue
		}
		if !strings.Contains(v.Error(), c.problem) {
			t.Errorf("%s/%s %v: %q does not mention %q", c.report, c.level, c.raw, v.Error(), c.problem)
		}
	}
}

func TestValidateAcceptsCityDrill(t *testing.T) {
	l := level(t, "r3", "geography")
	if _, err := Validate(l, map[string][]string{"level": {"city"}, "country": {"Philippines"}, "top_n": {"20"}}); err != nil {
		t.Fatal(err)
	}
}
