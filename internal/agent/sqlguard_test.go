package agent

import "testing"

// TestGuardSelectOnly pins the analysis-agent spec's "sql_query is
// read-only with a SELECT-only guard" requirement (task 6.5): the guard
// accepts clean single read-only SELECT statements and rejects every
// write/DDL/pragma/multi-statement/comment-smuggled vector before a
// query ever reaches SQLite.
func TestGuardSelectOnly(t *testing.T) {
	tests := []struct {
		name    string
		query   string
		wantErr bool
	}{
		// --- PASS: clean read-only SELECTs ---
		{
			name:  "simple select",
			query: "SELECT c0, c1 FROM measurement_value WHERE locator = 'nist-srd27/density#BeF2-LiF|34.0-66.0'",
		},
		{
			name:  "select with trailing semicolon",
			query: "SELECT c0, c1 FROM measurement_value;",
		},
		{
			name:  "lowercase select",
			query: "select c0, c1 from measurement_value",
		},
		{
			name:  "select with whitespace and newlines",
			query: "  \n\tSELECT c0,\n c1\nFROM measurement_value\n  ",
		},
		{
			name:  "with cte then select",
			query: "WITH cte AS (SELECT locator FROM measurement_value WHERE property = 'density') SELECT * FROM cte",
		},
		{
			name:  "select star from t with write fully inside a block comment",
			query: "SELECT * FROM t /* ; DROP TABLE t */",
		},
		{
			name:  "keyword INSERT inside a string literal",
			query: "SELECT * FROM measurement_value WHERE source = 'insert-derived'",
		},
		{
			name:  "semicolon inside a string literal",
			query: "SELECT c0 FROM measurement_value WHERE locator = 'a;b'",
		},
		{
			name:  "comment tokens inside a string literal",
			query: "SELECT c0 FROM t WHERE note = 'has -- dashes and /* comment */ text'",
		},
		{
			name:  "legitimate backtick identifier",
			query: "SELECT c0 AS `density` FROM measurement_value",
		},
		{
			name:  "legitimate bracket identifier",
			query: "SELECT [c0] FROM measurement_value",
		},
		{
			name:  "semicolon inside a backtick identifier is still one statement",
			query: "SELECT `weird;col` FROM t",
		},
		{
			name:  "semicolon inside a double-quoted identifier is still one statement",
			query: `SELECT "col;name" FROM t`,
		},

		// --- REJECT: writes ---
		{
			name:    "insert",
			query:   "INSERT INTO measurement_value (locator) VALUES ('x')",
			wantErr: true,
		},
		{
			name:    "update",
			query:   "UPDATE measurement_value SET c0 = 1 WHERE locator = 'x'",
			wantErr: true,
		},
		{
			name:    "delete",
			query:   "DELETE FROM measurement_value WHERE locator = 'x'",
			wantErr: true,
		},
		{
			name:    "replace",
			query:   "REPLACE INTO measurement_value (locator) VALUES ('x')",
			wantErr: true,
		},

		// --- REJECT: DDL ---
		{
			name:    "create table",
			query:   "CREATE TABLE t (a TEXT)",
			wantErr: true,
		},
		{
			name:    "alter table",
			query:   "ALTER TABLE measurement_value ADD COLUMN foo TEXT",
			wantErr: true,
		},
		{
			name:    "drop table",
			query:   "DROP TABLE measurement_value",
			wantErr: true,
		},

		// --- REJECT: pragma writes ---
		{
			name:    "pragma journal mode",
			query:   "PRAGMA journal_mode=WAL",
			wantErr: true,
		},

		// --- REJECT: multi-statement ---
		{
			name:    "select then drop",
			query:   "SELECT 1; DROP TABLE t",
			wantErr: true,
		},

		// --- REJECT: comment-smuggled writes ---
		{
			name:    "line comment does not hide a drop on the next line",
			query:   "SELECT 1 --\nDROP TABLE t",
			wantErr: true,
		},
		{
			name:    "block comment splitting select, then a drop statement",
			query:   "SELECT/**/1;DROP TABLE t",
			wantErr: true,
		},

		// --- REJECT: block-comment-across-string-literals bypass (HIGH-severity repro) ---
		{
			name:    "block comment delimiters smuggled across separate string literals to drop a table",
			query:   "SELECT '/*' ; DROP TABLE measurement_value ; SELECT '*/'",
			wantErr: true,
		},
		{
			name:    "block comment delimiters smuggled across separate string literals to attach and create a file",
			query:   "SELECT '/*' ; ATTACH DATABASE '/tmp/evil.db' AS e ; CREATE TABLE e.pwned(x) ; SELECT '*/'",
			wantErr: true,
		},
		{
			name:    "stacked statement after a quoted identifier",
			query:   `SELECT "a" ; DROP TABLE t`,
			wantErr: true,
		},
		{
			name:    "block comment delimiters smuggled inside a backtick identifier to drop a table",
			query:   "SELECT 1 AS `/*` ; DROP TABLE measurement_value ; SELECT 1 AS `*/`",
			wantErr: true,
		},
		{
			name:    "block comment delimiters smuggled inside a bracket identifier to drop a table",
			query:   "SELECT 1 AS [/*] ; DROP TABLE measurement_value ; SELECT 1 AS [*/]",
			wantErr: true,
		},
		{
			name:    "block comment delimiters smuggled inside a backtick identifier to attach and create a file",
			query:   "SELECT 1 AS `/*` ; ATTACH DATABASE '/tmp/evil.db' AS e ; CREATE TABLE e.pwned(x) ; SELECT 1 AS `*/`",
			wantErr: true,
		},
		{
			name:    "block comment delimiters smuggled inside a bracket identifier to attach and create a file",
			query:   "SELECT 1 AS [/*] ; ATTACH DATABASE '/tmp/evil.db' AS e ; CREATE TABLE e.pwned(x) ; SELECT 1 AS [*/]",
			wantErr: true,
		},
		{
			name:    "stacked statement after a backtick-quoted identifier",
			query:   "SELECT 1 AS `a`;DROP TABLE t",
			wantErr: true,
		},
		{
			name:    "stacked statement after a bracket-quoted identifier",
			query:   "SELECT 1 AS [a];DROP TABLE t",
			wantErr: true,
		},
		{
			name:    "unterminated backtick-quoted identifier",
			query:   "SELECT 1 AS `abc",
			wantErr: true,
		},
		{
			name:    "unterminated bracket-quoted identifier",
			query:   "SELECT 1 AS [abc",
			wantErr: true,
		},
		{
			name:    "unterminated string literal",
			query:   "SELECT 'abc",
			wantErr: true,
		},
		{
			name:    "unterminated block comment",
			query:   "SELECT 1 /* unterminated block comment",
			wantErr: true,
		},
		{
			name:    "single attach statement",
			query:   "ATTACH DATABASE '/tmp/x.db' AS e",
			wantErr: true,
		},
		{
			name:    "load_extension call",
			query:   "SELECT load_extension('x')",
			wantErr: true,
		},

		// --- REJECT: not a SELECT at all ---
		{
			name:    "empty query",
			query:   "",
			wantErr: true,
		},
		{
			name:    "non-select garbage",
			query:   "EXPLAIN SELECT 1",
			wantErr: true,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := guardSelectOnly(tc.query)
			if tc.wantErr && err == nil {
				t.Fatalf("guardSelectOnly(%q) = nil, want an error", tc.query)
			}
			if !tc.wantErr && err != nil {
				t.Fatalf("guardSelectOnly(%q) = %v, want nil", tc.query, err)
			}
		})
	}
}
