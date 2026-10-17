package reports

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// Dimension member lists for the dashboard's filter controls. The 'Unknown'
// members (key 0) exist only to keep facts joinable and are left out.
var dimensionQueries = []struct {
	Name string
	SQL  string
}{
	{"years", `SELECT DISTINCT "year"::text FROM "DIM_DATE" ORDER BY 1`},
	{"categories", `SELECT DISTINCT "category" FROM "DIM_PRODUCT" WHERE "productKey" <> 0 ORDER BY 1`},
	{"couriers", `SELECT DISTINCT "courierName" FROM "DIM_RIDER" WHERE "riderKey" <> 0 ORDER BY 1`},
	{"vehicles", `SELECT DISTINCT "vehicleType" FROM "DIM_RIDER" WHERE "riderKey" <> 0 ORDER BY 1`},
	{"ageBands", `SELECT DISTINCT "ageBand" FROM "DIM_RIDER" WHERE "riderKey" <> 0 AND "ageBand" IS NOT NULL ORDER BY 1`},
	{"sizeGroups", `SELECT DISTINCT "sizeGroup" FROM "DIM_ORDERSIZE" WHERE "orderSizeKey" <> 0 ORDER BY 1`},
	{"countries", `SELECT DISTINCT "country" FROM "DIM_GEOGRAPHY" WHERE "geoKey" <> 0 ORDER BY 1`},
	{"genders", `SELECT DISTINCT "gender"::text FROM "DIM_CUSTOMER" WHERE "gender" IS NOT NULL ORDER BY 1`},
}

const citiesSQL = `SELECT DISTINCT "city" FROM "DIM_GEOGRAPHY" WHERE "geoKey" <> 0 AND "country" = $1 ORDER BY 1`

// Dimensions returns the members of every filterable dimension.
func (s *Service) Dimensions(ctx context.Context) (map[string][]string, error) {
	ctx, cancel := context.WithTimeout(ctx, s.timeout)
	defer cancel()
	out := make(map[string][]string, len(dimensionQueries))
	for _, q := range dimensionQueries {
		values, err := s.strings(ctx, q.SQL)
		if err != nil {
			return nil, fmt.Errorf("dimension %s: %w", q.Name, err)
		}
		out[q.Name] = values
	}
	return out, nil
}

// Cities returns the cities of one country, for the Country > City drill.
func (s *Service) Cities(ctx context.Context, country string) ([]string, error) {
	ctx, cancel := context.WithTimeout(ctx, s.timeout)
	defer cancel()
	return s.strings(ctx, citiesSQL, country)
}

func (s *Service) strings(ctx context.Context, sql string, args ...any) ([]string, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	values, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	if values == nil {
		values = []string{}
	}
	return values, nil
}
