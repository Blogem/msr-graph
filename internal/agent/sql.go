package agent

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
)

// sqlToolParameters is the JSON Schema advertised to the model for the
// sql_query tool's single "query" argument.
const sqlToolParameters = `{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "A single read-only SQL SELECT statement (optionally a WITH ... SELECT) to run against the measurement_value table."
    }
  },
  "required": ["query"]
}`

// sqlToolDescription documents the measurement_value schema and the
// read-only contract so the model can form correct queries (design D2):
// coefficient lookups by the dataLocator obtained from sparql_query
// grounding.
const sqlToolDescription = `Run a single read-only SQL SELECT statement against the measurement_value table, which holds fitted-equation coefficients for salt properties.

Columns: locator, salt, property, c0, c1, c2, c3, c4, t_min, t_max, equation_form, uncertainty, source, doc_id.

locator is the dataLocator key returned by sparql_query grounding (e.g. "nist-srd27/density#BeF2-LiF|34.0-66.0"); look coefficients up by matching it. Typical use: SELECT c0, c1, c2, c3, c4, t_min, t_max, equation_form FROM measurement_value WHERE locator = '...'.

Only a single, read-only SELECT statement is allowed (a WITH ... SELECT is also allowed). INSERT, UPDATE, DELETE, DDL, PRAGMA, and multi-statement input are rejected before reaching the database.`

// SQLQuerier is the consumer-side interface sql_query needs from a
// database handle: a read-only query. *sql.DB satisfies it; tests may
// substitute a narrower fake.
type SQLQuerier interface {
	QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)
}

// sqlTool implements Tool for sql_query: a SELECT-only reader over
// measurement_value (design D2). The guard runs before any call reaches
// db, so a write never reaches SQLite regardless of what the model
// requests.
type sqlTool struct {
	db SQLQuerier
}

// NewSQLTool builds the sql_query Tool backed by db (typically a
// *sql.DB opened via internal/store.Open against the read-only
// measurement store).
func NewSQLTool(db SQLQuerier) Tool {
	return &sqlTool{db: db}
}

// sqlToolArgs is the JSON argument shape the model supplies for a
// sql_query call.
type sqlToolArgs struct {
	Query string `json:"query"`
}

func (t *sqlTool) Spec() ToolSpec {
	return ToolSpec{
		Name:        "sql_query",
		Description: sqlToolDescription,
		Parameters:  json.RawMessage(sqlToolParameters),
	}
}

func (t *sqlTool) Call(ctx context.Context, args string, emit Emitter) (string, error) {
	var a sqlToolArgs
	if err := json.Unmarshal([]byte(args), &a); err != nil {
		return "", fmt.Errorf("sql_query: decode arguments: %w", err)
	}

	if err := guardSelectOnly(a.Query); err != nil {
		return "", err
	}

	rows, err := t.db.QueryContext(ctx, a.Query)
	if err != nil {
		return "", fmt.Errorf("sql_query: %w", err)
	}
	defer rows.Close()

	cols, err := rows.Columns()
	if err != nil {
		return "", fmt.Errorf("sql_query: reading columns: %w", err)
	}

	result := make([][]any, 0)
	for rows.Next() {
		raw := make([]any, len(cols))
		ptrs := make([]any, len(cols))
		for i := range raw {
			ptrs[i] = &raw[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return "", fmt.Errorf("sql_query: scanning row: %w", err)
		}

		row := make([]any, len(cols))
		for i, v := range raw {
			row[i] = normalizeSQLValue(v)
		}
		result = append(result, row)
	}
	if err := rows.Err(); err != nil {
		return "", fmt.Errorf("sql_query: iterating rows: %w", err)
	}

	out := struct {
		Columns []string `json:"columns"`
		Rows    [][]any  `json:"rows"`
	}{Columns: cols, Rows: result}

	b, err := json.Marshal(out)
	if err != nil {
		return "", fmt.Errorf("sql_query: encoding result: %w", err)
	}
	return string(b), nil
}

// normalizeSQLValue converts a database/sql-scanned value into one that
// encoding/json renders sensibly: []byte (SQLite TEXT/BLOB frequently
// scans as []byte) becomes a string, and nil (SQL NULL) stays nil.
func normalizeSQLValue(v any) any {
	if b, ok := v.([]byte); ok {
		return string(b)
	}
	return v
}
