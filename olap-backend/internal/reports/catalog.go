// Package reports serves the four OLAP reports in olap/queries.
//
// The SQL files are the single source of truth for the queries; this package
// only knows which files exist, which parameters each accepts, and which
// values those parameters may take. Every value is validated here and then
// bound as a query parameter, never concatenated into SQL.
package reports

import "slices"

// Param describes one query parameter. An empty value always means "all"
// (no filter), matching the "(:'x' = ” OR column = :'x')" pattern in the SQL.
type Param struct {
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Kind        string   `json:"kind"`              // "enum" | "int" | "text"
	Values      []string `json:"values,omitempty"`  // allowed values for "enum"
	Min         int      `json:"min,omitempty"`     // bounds for "int"
	Max         int      `json:"max,omitempty"`     // bounds for "int"
	Default     string   `json:"default,omitempty"` // what the SQL uses when empty
}

// Level is one drill level of a report: one SQL file.
type Level struct {
	ID          string   `json:"id"`
	Aliases     []string `json:"aliases,omitempty"` // other names the dashboard uses
	File        string   `json:"file"`              // relative to olap/queries
	Title       string   `json:"title"`
	Description string   `json:"description"`
	Operations  []string `json:"operations"`
	Columns     []string `json:"columns"`
	Params      []Param  `json:"params"`
}

type Report struct {
	ID     string  `json:"id"`
	Folder string  `json:"folder"`
	Title  string  `json:"title"`
	Levels []Level `json:"levels"`
}

// Shared parameter definitions. Allowed values come from each file header.
var (
	pYear      = Param{Name: "year", Description: "Delivery year", Kind: "enum", Values: []string{"2024", "2025"}}
	pYearR3    = Param{Name: "year", Description: "Order year", Kind: "enum", Values: []string{"2024", "2025"}}
	pQuarter   = Param{Name: "quarter", Description: "Quarter", Kind: "enum", Values: []string{"1", "2", "3", "4"}}
	pMonth     = Param{Name: "month", Description: "Month number", Kind: "enum", Values: []string{"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"}}
	pVehicle   = Param{Name: "vehicle", Description: "Rider vehicle type", Kind: "enum", Values: []string{"Bicycle", "Motorcycle", "Car", "Trike"}}
	pSizeGroup = Param{Name: "size_group", Description: "Order-size group", Kind: "enum", Values: []string{"Light", "Heavy"}}
	pCourier   = Param{Name: "courier", Description: "Courier", Kind: "enum", Values: []string{"FEDEZ", "JNT", "LBCD"}}
	pAgeBand   = Param{Name: "age_band", Description: "Rider age band", Kind: "enum", Values: []string{"18-29", "30-39", "40-49", "50-60"}}
	pDayType   = Param{Name: "day_type", Description: "Weekday or weekend", Kind: "enum", Values: []string{"weekday", "weekend"}}
	pPayday    = Param{Name: "payday", Description: "Payday or not", Kind: "enum", Values: []string{"yes", "no"}}
	pGender    = Param{Name: "gender", Description: "Customer gender", Kind: "enum", Values: []string{"M", "F"}}
	pCategory  = Param{Name: "category", Description: "Product category (see /api/dimensions)", Kind: "text"}
	pCountry   = Param{Name: "country", Description: "Customer country (see /api/dimensions)", Kind: "text"}
	pCity      = Param{Name: "city", Description: "Customer city; use with country (see /api/dimensions/cities)", Kind: "text"}
)

func topN(def string) Param {
	return Param{Name: "top_n", Description: "Number of ranked rows returned", Kind: "int", Min: 1, Max: 1000, Default: def}
}

// Catalog lists every report and level, in dashboard order.
var Catalog = []Report{
	{
		ID: "r1", Folder: "r1_product_category_value", Title: "Product & Category Value",
		Levels: []Level{
			{
				ID: "category", File: "r1_product_category_value/category.sql", Title: "By category",
				Description: "Which categories carry the most delivered units and list-price value?",
				Operations:  []string{"roll-up", "slice", "dice"},
				Columns:     []string{"category", "units", "value", "value_share_pct", "value_rank", "is_total"},
				Params:      []Param{pYear, pQuarter, pMonth, pVehicle, pSizeGroup},
			},
			{
				ID: "product", File: "r1_product_category_value/product.sql", Title: "By product",
				Description: "Which products lead each category by list-price value?",
				Operations:  []string{"drill-down", "slice", "dice"},
				Columns:     []string{"category", "product", "units", "value", "share_of_category_pct", "rank_in_category", "is_subtotal"},
				Params:      []Param{pCategory, pYear, pQuarter, pMonth, pVehicle, pSizeGroup, topN("10")},
			},
		},
	},
	{
		ID: "r2", Folder: "r2_fleet_courier_workload", Title: "Fleet, Courier & Rider Workload",
		Levels: []Level{
			{
				ID: "courier_vehicle_cube", Aliases: []string{"cube"}, File: "r2_fleet_courier_workload/courier_vehicle_cube.sql", Title: "Courier x vehicle (cube)",
				Description: "How is delivery volume split across couriers and vehicles, and is the work fair per rider?",
				Operations:  []string{"roll-up", "slice", "dice"},
				Columns:     []string{"courier", "vehicle", "orders", "units", "riders", "orders_per_rider", "order_share_pct", "grouping_level"},
				Params:      []Param{pYear, pQuarter, pMonth, pCourier, pVehicle, pAgeBand, pSizeGroup},
			},
			{
				ID: "courier_vehicle_pivot", Aliases: []string{"pivot"}, File: "r2_fleet_courier_workload/courier_vehicle_pivot.sql", Title: "Courier x vehicle (pivot)",
				Description: "Cross-tab: one row per courier, one column per vehicle type.",
				Operations:  []string{"pivot", "slice", "dice"},
				Columns:     []string{"courier", "motorcycle", "bicycle", "car", "trike", "total", "riders", "is_total"},
				Params: []Param{
					{Name: "measure", Description: "Cell measure", Kind: "enum", Values: []string{"orders", "per_rider"}, Default: "orders"},
					pYear, pQuarter, pMonth, pCourier, pVehicle, pAgeBand, pSizeGroup,
				},
			},
			{
				ID: "rider", File: "r2_fleet_courier_workload/rider.sql", Title: "By rider",
				Description: "Which riders carry the most work, how often are they active, and how high do their peak days go?",
				Operations:  []string{"drill-down", "drill-across", "slice", "dice"},
				Columns: []string{"workload_rank", "rider", "courier", "vehicle", "age_band", "orders", "units", "active_days",
					"calendar_days", "utilization_pct", "avg_orders_per_active_day", "peak_day_orders", "workload_percentile"},
				Params: []Param{
					pYear, pQuarter, pMonth, pCourier, pVehicle, pAgeBand,
					{Name: "sort", Description: "Ranking direction", Kind: "enum", Values: []string{"most", "least"}, Default: "most"},
					topN("20"),
				},
			},
		},
	},
	{
		ID: "r3", Folder: "r3_customer_value_distribution", Title: "Customer Value Distribution",
		Levels: []Level{
			{
				ID: "deciles", File: "r3_customer_value_distribution/deciles.sql", Title: "Value deciles",
				Description: "How concentrated is customer value?",
				Operations:  []string{"roll-up", "slice", "dice"},
				Columns: []string{"decile", "customers", "value", "value_share_pct", "cumulative_share_pct",
					"avg_value_per_customer", "min_customer_value", "max_customer_value"},
				Params: []Param{pCountry, pGender, pYearR3, pQuarter},
			},
			{
				ID: "geography", File: "r3_customer_value_distribution/geography.sql", Title: "By geography",
				Description: "Where are customers and their value concentrated, and how does gender split it?",
				Operations:  []string{"drill-down", "slice", "dice"},
				Columns:     []string{"location", "gender", "customers", "orders", "value", "value_per_customer", "value_rank", "grouping_level"},
				Params: []Param{
					{Name: "level", Description: "Geography level; 'city' requires country", Kind: "enum", Values: []string{"country", "city"}, Default: "country"},
					pCountry, pGender, pYearR3, pQuarter, topN("20"),
				},
			},
			{
				ID: "customer", File: "r3_customer_value_distribution/customer.sql", Title: "By customer",
				Description: "Who are the top customers, and where do they sit in the value distribution?",
				Operations:  []string{"drill-down", "slice", "dice"},
				Columns: []string{"value_rank", "customer", "country", "city", "gender", "orders", "units", "value",
					"avg_order_value", "decile", "value_percentile"},
				Params: []Param{
					pCountry, pCity, pGender,
					{Name: "decile", Description: "Only customers in this decile", Kind: "int", Min: 1, Max: 10},
					pYearR3, pQuarter, topN("20"),
				},
			},
		},
	},
	{
		ID: "r4", Folder: "r4_demand_calendar", Title: "Demand Calendar",
		Levels: []Level{
			{
				ID: "rollup", File: "r4_demand_calendar/rollup.sql", Title: "Year > Quarter > Month roll-up",
				Description: "Every month, its quarter and year subtotals and the grand total, normalized to orders per day.",
				Operations:  []string{"roll-up", "slice", "dice"},
				Columns:     []string{"hierarchy_level", "year", "quarter", "month", "month_name", "days", "orders", "units", "orders_per_day"},
				Params:      []Param{pYear, pDayType, pPayday, pVehicle, pSizeGroup},
			},
			{
				ID: "trend", File: "r4_demand_calendar/trend.sql", Title: "Trend",
				Description: "How does order demand move over time, and do weekends or paydays differ?",
				Operations:  []string{"roll-up", "drill-down", "slice", "dice"},
				Columns: []string{"period_label", "period_start", "days", "orders", "units", "orders_per_day",
					"change_vs_previous_pct", "moving_avg_orders_per_day"},
				Params: []Param{
					{Name: "level", Description: "Date hierarchy level", Kind: "enum", Values: []string{"year", "quarter", "month", "week", "day"}, Default: "month"},
					pYear, pQuarter, pMonth, pDayType, pPayday, pVehicle, pSizeGroup,
				},
			},
			{
				ID: "weekday_pivot", File: "r4_demand_calendar/weekday_pivot.sql", Title: "Month x weekday pivot",
				Description: "Is any day of the week busier, and does that pattern hold every month?",
				Operations:  []string{"pivot", "roll-up", "slice", "dice"},
				Columns:     []string{"month_label", "mon", "tue", "wed", "thu", "fri", "sat", "sun", "all_days", "is_total"},
				Params:      []Param{pYear, pQuarter, pPayday, pVehicle, pSizeGroup},
			},
			{
				ID: "busiest_days", File: "r4_demand_calendar/busiest_days.sql", Title: "Busiest days",
				Description: "Which single days put the most load on the network?",
				Operations:  []string{"drill-down", "slice", "dice"},
				Columns: []string{"demand_rank", "date", "day_name", "is_weekend", "is_payday", "orders", "units",
					"active_riders", "orders_per_active_rider", "vs_average_pct"},
				Params: []Param{
					pYear, pQuarter, pMonth, pDayType, pPayday, pVehicle, pSizeGroup,
					{Name: "sort", Description: "Ranking direction", Kind: "enum", Values: []string{"busiest", "quietest"}, Default: "busiest"},
					topN("10"),
				},
			},
		},
	},
}

// Find returns the report and level with the given ids. A level matches by
// its id or any alias, so the dashboard's /r2/pivot and /r2/cube resolve.
func Find(reportID, levelID string) (Report, Level, bool) {
	for _, r := range Catalog {
		if r.ID != reportID && r.Folder != reportID {
			continue
		}
		for _, l := range r.Levels {
			if l.ID == levelID || slices.Contains(l.Aliases, levelID) {
				return r, l, true
			}
		}
		return r, Level{}, false
	}
	return Report{}, Level{}, false
}
