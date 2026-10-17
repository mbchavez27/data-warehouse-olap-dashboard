package reports

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

// Querier is the part of *pgxpool.Pool the service needs.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
}

type Column struct {
	Name string `json:"name"`
	Type string `json:"type"` // "text" | "integer" | "numeric" | "boolean" | "date"
}

// Result is one level's output, shaped for the dashboard: columns in SQL
// order and one object per row keyed by column name.
type Result struct {
	Report    string            `json:"report"`
	Level     string            `json:"level"`
	Params    map[string]string `json:"params"`
	Columns   []Column          `json:"columns"`
	Rows      []map[string]any  `json:"rows"`
	RowCount  int               `json:"rowCount"`
	ElapsedMs float64           `json:"elapsedMs"`
}

type Service struct {
	db         Querier
	statements map[string]Statement
	timeout    time.Duration
}

func NewService(db Querier, statements map[string]Statement, timeout time.Duration) *Service {
	return &Service{db: db, statements: statements, timeout: timeout}
}

// Run validates the parameters, executes the level's statement and returns
// its rows. A *ValidationError means the request itself was wrong.
func (s *Service) Run(ctx context.Context, r Report, l Level, raw map[string][]string) (*Result, error) {
	bound, err := Validate(l, raw)
	if err != nil {
		return nil, err
	}
	stmt, ok := s.statements[l.File]
	if !ok {
		return nil, fmt.Errorf("no statement loaded for %s", l.File)
	}
	args := make([]any, len(stmt.Names))
	for i, name := range stmt.Names {
		args[i] = bound[name]
	}

	ctx, cancel := context.WithTimeout(ctx, s.timeout)
	defer cancel()

	started := time.Now()
	rows, err := s.db.Query(ctx, stmt.SQL, args...)
	if err != nil {
		return nil, fmt.Errorf("query %s: %w", l.File, err)
	}
	defer rows.Close()

	fields := rows.FieldDescriptions()
	columns := make([]Column, len(fields))
	for i, f := range fields {
		columns[i] = Column{Name: f.Name, Type: typeName(f.DataTypeOID)}
	}

	out := []map[string]any{}
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return nil, fmt.Errorf("read %s: %w", l.File, err)
		}
		row := make(map[string]any, len(values))
		for i, v := range values {
			row[columns[i].Name] = jsonValue(v, fields[i].DataTypeOID)
		}
		out = append(out, row)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("query %s: %w", l.File, err)
	}
	elapsed := time.Since(started)

	return &Result{
		Report:    r.ID,
		Level:     l.ID,
		Params:    bound,
		Columns:   columns,
		Rows:      out,
		RowCount:  len(out),
		ElapsedMs: float64(elapsed.Microseconds()) / 1000,
	}, nil
}

func typeName(oid uint32) string {
	switch oid {
	case pgtype.Int2OID, pgtype.Int4OID, pgtype.Int8OID:
		return "integer"
	case pgtype.NumericOID, pgtype.Float4OID, pgtype.Float8OID:
		return "numeric"
	case pgtype.BoolOID:
		return "boolean"
	case pgtype.DateOID, pgtype.TimestampOID, pgtype.TimestamptzOID:
		return "date"
	default:
		return "text"
	}
}

// jsonValue converts a driver value into something encoding/json writes
// faithfully: NUMERIC keeps its exact decimal digits, DATE becomes
// "YYYY-MM-DD".
func jsonValue(v any, oid uint32) any {
	switch x := v.(type) {
	case nil:
		return nil
	case pgtype.Numeric:
		if !x.Valid {
			return nil
		}
		if x.NaN || x.InfinityModifier != pgtype.Finite {
			return nil
		}
		b, err := x.MarshalJSON()
		if err != nil {
			return nil
		}
		return json.Number(b)
	case time.Time:
		if oid == pgtype.DateOID {
			return x.Format(time.DateOnly)
		}
		return x.Format(time.RFC3339)
	default:
		return v
	}
}
