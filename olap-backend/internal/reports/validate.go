package reports

import (
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

// maxTextLen bounds free-text filters (category, country, city); the
// warehouse columns are VARCHAR(128).
const maxTextLen = 128

// ValidationError is a client error: the request names an unknown
// parameter or a value the parameter does not allow.
type ValidationError struct {
	Problems []string
}

func (e *ValidationError) Error() string {
	return strings.Join(e.Problems, "; ")
}

// Validate checks raw query values against the level's parameters and
// returns a value for every parameter, "" meaning all. Values are trimmed.
func Validate(l Level, raw map[string][]string) (map[string]string, error) {
	var problems []string
	known := map[string]Param{}
	for _, p := range l.Params {
		known[p.Name] = p
	}

	var unknown []string
	for name := range raw {
		if _, ok := known[name]; !ok {
			unknown = append(unknown, name)
		}
	}
	sort.Strings(unknown)
	for _, name := range unknown {
		problems = append(problems, fmt.Sprintf("unknown parameter %q", name))
	}

	bound := make(map[string]string, len(l.Params))
	for _, p := range l.Params {
		values := raw[p.Name]
		if len(values) > 1 {
			problems = append(problems, fmt.Sprintf("parameter %q given more than once", p.Name))
			continue
		}
		value := ""
		if len(values) == 1 {
			value = strings.TrimSpace(values[0])
		}
		if err := checkValue(p, value); err != nil {
			problems = append(problems, err.Error())
			continue
		}
		bound[p.Name] = value
	}

	// Cross-parameter rules from the file headers.
	if l.ID == "geography" && bound["level"] == "city" && bound["country"] == "" {
		problems = append(problems, "level 'city' requires country (city names repeat across countries)")
	}
	if l.ID == "customer" && bound["city"] != "" && bound["country"] == "" {
		problems = append(problems, "city requires country (city names repeat across countries)")
	}

	if len(problems) > 0 {
		return nil, &ValidationError{Problems: problems}
	}
	return bound, nil
}

func checkValue(p Param, value string) error {
	if value == "" {
		return nil
	}
	switch p.Kind {
	case "enum":
		if !slices.Contains(p.Values, value) {
			return fmt.Errorf("%s must be one of %s", p.Name, strings.Join(p.Values, ", "))
		}
	case "int":
		n, err := strconv.Atoi(value)
		if err != nil || n < p.Min || n > p.Max {
			return fmt.Errorf("%s must be an integer from %d to %d", p.Name, p.Min, p.Max)
		}
	case "text":
		if utf8.RuneCountInString(value) > maxTextLen {
			return fmt.Errorf("%s must be at most %d characters", p.Name, maxTextLen)
		}
	default:
		return fmt.Errorf("%s has unsupported kind %q", p.Name, p.Kind)
	}
	return nil
}
