package reports

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
)

// psqlParam matches psql-style named parameters such as :'year'.
var psqlParam = regexp.MustCompile(`:'([a-z_]+)'`)

// Statement is one SQL file translated for the driver: each :'name' becomes
// a positional $n::text placeholder, and Names[n-1] is the parameter bound
// to $n. A name used several times in the file reuses the same placeholder.
type Statement struct {
	SQL   string
	Names []string
}

// Translate turns a query file's text into a driver statement. The ::text
// cast keeps every parameter a string, exactly like psql's :'x' quoting, so
// the SQL's own nullif(...)::int conversions behave the same in both.
func Translate(sqlText string) Statement {
	index := map[string]int{}
	var names []string
	out := psqlParam.ReplaceAllStringFunc(sqlText, func(m string) string {
		name := psqlParam.FindStringSubmatch(m)[1]
		n, ok := index[name]
		if !ok {
			names = append(names, name)
			n = len(names)
			index[name] = n
		}
		return fmt.Sprintf("$%d::text", n)
	})
	out = strings.TrimRight(strings.TrimSpace(out), ";")
	return Statement{SQL: out, Names: names}
}

// LoadStatements reads every level's SQL file from queriesDir and checks
// that the parameters the file uses are exactly the ones the catalog
// declares, so a changed query file fails at startup rather than per request.
func LoadStatements(queriesDir string) (map[string]Statement, error) {
	statements := map[string]Statement{}
	for _, r := range Catalog {
		for _, l := range r.Levels {
			text, err := os.ReadFile(filepath.Join(queriesDir, filepath.FromSlash(l.File)))
			if err != nil {
				return nil, fmt.Errorf("read %s: %w", l.File, err)
			}
			stmt := Translate(string(text))
			if err := checkParams(l, stmt.Names); err != nil {
				return nil, fmt.Errorf("%s: %w", l.File, err)
			}
			statements[l.File] = stmt
		}
	}
	return statements, nil
}

func checkParams(l Level, used []string) error {
	declared := make([]string, 0, len(l.Params))
	for _, p := range l.Params {
		declared = append(declared, p.Name)
	}
	usedSorted := slices.Sorted(slices.Values(used))
	slices.Sort(declared)
	if !slices.Equal(usedSorted, declared) {
		return fmt.Errorf("file uses parameters %v but the catalog declares %v", usedSorted, declared)
	}
	return nil
}
