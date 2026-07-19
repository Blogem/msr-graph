package agent_test

// Tests for the sql_query tool (task 6.5): a real temp-file SQLite
// database opened via internal/store, seeded with one measurement_value
// row directly (test setup, not via the tool), then read through
// agent.NewSQLTool. Pins the analysis-agent spec's "A SELECT returns
// rows" and "Non-SELECT statements are rejected" scenarios.

import (
	"context"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/agent"
	"github.com/blogem/msr-graph/internal/store"
)

const testLocator = "nist-srd27/density#BeF2-LiF|34.0-66.0"

func TestSQLTool_SelectReturnsRow(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	path := filepath.Join(dir, "measurements.db")

	db, err := store.Open(path)
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	defer db.Close()

	if err := store.Init(ctx, db); err != nil {
		t.Fatalf("store.Init: %v", err)
	}

	const insertSQL = `INSERT INTO measurement_value
		(locator, salt, property, c0, c1, t_min, t_max, equation_form, source)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
	if _, err := db.ExecContext(ctx, insertSQL,
		testLocator, "BeF2-LiF|34.0-66.0", "density",
		2.413, -4.88e-4, 800.0, 1080.0, "Linear", "nist",
	); err != nil {
		t.Fatalf("seeding a measurement_value row: %v", err)
	}

	tool := agent.NewSQLTool(db)

	spec := tool.Spec()
	if spec.Name != "sql_query" {
		t.Fatalf("Spec().Name = %q, want %q", spec.Name, "sql_query")
	}
	if spec.Description == "" {
		t.Fatalf("Spec().Description is empty")
	}
	if len(spec.Parameters) == 0 {
		t.Fatalf("Spec().Parameters is empty")
	}

	args, err := json.Marshal(map[string]string{
		"query": "SELECT c0, c1 FROM measurement_value WHERE locator = '" + testLocator + "'",
	})
	if err != nil {
		t.Fatalf("marshal args: %v", err)
	}

	result, err := tool.Call(ctx, string(args), func(agent.Event) {})
	if err != nil {
		t.Fatalf("Call: %v", err)
	}

	var decoded struct {
		Columns []string `json:"columns"`
		Rows    [][]any  `json:"rows"`
	}
	if err := json.Unmarshal([]byte(result), &decoded); err != nil {
		t.Fatalf("result is not valid JSON: %v\nresult: %s", err, result)
	}

	if len(decoded.Rows) != 1 {
		t.Fatalf("got %d rows, want 1\nresult: %s", len(decoded.Rows), result)
	}
	if len(decoded.Rows[0]) != 2 {
		t.Fatalf("got %d columns in row, want 2\nresult: %s", len(decoded.Rows[0]), result)
	}
	c0, ok := decoded.Rows[0][0].(float64)
	if !ok || c0 != 2.413 {
		t.Errorf("row[0][0] (c0) = %v, want 2.413", decoded.Rows[0][0])
	}
	c1, ok := decoded.Rows[0][1].(float64)
	if !ok || c1 != -4.88e-4 {
		t.Errorf("row[0][1] (c1) = %v, want -4.88e-4", decoded.Rows[0][1])
	}
}

func TestSQLTool_WriteIsRejectedAndNeverReachesSQLite(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	path := filepath.Join(dir, "measurements.db")

	db, err := store.Open(path)
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	defer db.Close()

	if err := store.Init(ctx, db); err != nil {
		t.Fatalf("store.Init: %v", err)
	}

	const insertSQL = `INSERT INTO measurement_value
		(locator, salt, property, c0, c1, t_min, t_max, equation_form, source)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
	if _, err := db.ExecContext(ctx, insertSQL,
		testLocator, "BeF2-LiF|34.0-66.0", "density",
		2.413, -4.88e-4, 800.0, 1080.0, "Linear", "nist",
	); err != nil {
		t.Fatalf("seeding a measurement_value row: %v", err)
	}

	var before int
	if err := db.QueryRowContext(ctx, `SELECT COUNT(*) FROM measurement_value`).Scan(&before); err != nil {
		t.Fatalf("counting rows before: %v", err)
	}

	tool := agent.NewSQLTool(db)

	args, err := json.Marshal(map[string]string{
		"query": "DELETE FROM measurement_value WHERE locator = '" + testLocator + "'",
	})
	if err != nil {
		t.Fatalf("marshal args: %v", err)
	}

	result, err := tool.Call(ctx, string(args), func(agent.Event) {})
	if err == nil {
		t.Fatalf("Call(DELETE) = %q, nil error; want the guard to reject it", result)
	}
	if !strings.Contains(err.Error(), "sql_query") {
		t.Errorf("error %q does not look like a sql_query guard error", err.Error())
	}

	var after int
	if err := db.QueryRowContext(ctx, `SELECT COUNT(*) FROM measurement_value`).Scan(&after); err != nil {
		t.Fatalf("counting rows after: %v", err)
	}
	if after != before {
		t.Fatalf("row count changed from %d to %d; the guarded DELETE reached SQLite", before, after)
	}
}
