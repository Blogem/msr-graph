package agent

import (
	"fmt"
	"regexp"
	"strings"
)

// forbiddenKeywords are write/DDL/pragma keywords that must not appear
// anywhere in a query passed to guardSelectOnly, even inside a WITH CTE.
// This is deliberately conservative -- it also rejects a data-modifying
// "WITH ... DELETE" CTE and all PRAGMA use, but coefficient reads never
// need those (design D2).
var forbiddenKeywordPattern = regexp.MustCompile(
	`(?i)\b(INSERT|UPDATE|DELETE|REPLACE|INTO|CREATE|ALTER|DROP|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|TRIGGER|GRANT|REVOKE)\b`,
)

// blockCommentPattern matches /* ... */ block comments (non-greedy, so
// adjacent comments are stripped individually rather than merged).
var blockCommentPattern = regexp.MustCompile(`(?s)/\*.*?\*/`)

// lineCommentPattern matches -- line comments through to end of line.
var lineCommentPattern = regexp.MustCompile(`--[^\n]*`)

// guardSelectOnly rejects any statement that is not a single read-only
// SELECT (optionally introduced by WITH), per the analysis-agent spec's
// "sql_query is read-only with a SELECT-only guard" requirement. It
// strips comments before checking so a write cannot be smuggled past the
// guard inside a -- or /* */ comment, then requires the statement to
// start with SELECT/WITH, contain no interior statement separator, and
// contain no whole-word match for a write/DDL/pragma keyword anywhere in
// the remaining (non-comment) text.
func guardSelectOnly(query string) error {
	stripped := blockCommentPattern.ReplaceAllString(query, " ")
	stripped = lineCommentPattern.ReplaceAllString(stripped, "")

	trimmed := strings.TrimSpace(stripped)
	if trimmed == "" {
		return fmt.Errorf("sql_query: empty query")
	}

	// Strip a single optional trailing ';'; any ';' remaining in the
	// interior means multiple statements were supplied.
	trimmed = strings.TrimRight(trimmed, " \t\r\n")
	trimmed = strings.TrimSuffix(trimmed, ";")
	trimmed = strings.TrimSpace(trimmed)

	if strings.Contains(trimmed, ";") {
		return fmt.Errorf("sql_query: multiple statements are not allowed")
	}

	upper := strings.ToUpper(trimmed)
	if !strings.HasPrefix(upper, "SELECT") && !strings.HasPrefix(upper, "WITH") {
		return fmt.Errorf("sql_query: only a single read-only SELECT statement is allowed")
	}

	if loc := forbiddenKeywordPattern.FindString(trimmed); loc != "" {
		return fmt.Errorf("sql_query: statement contains a disallowed keyword %q; only read-only SELECT is allowed", loc)
	}

	return nil
}
