package agent

import (
	"fmt"
	"regexp"
	"strings"
)

// forbiddenKeywordPattern lists write/DDL/pragma/attach/file-IO keywords
// that must not appear in the CODE stream (see extractCodeStream) of a
// query passed to guardSelectOnly, even inside a WITH CTE. This is
// deliberately conservative -- it also rejects a data-modifying
// "WITH ... DELETE" CTE and all PRAGMA use, but coefficient reads never
// need those (design D2). ATTACH is included because it can open a new,
// separate writable database file regardless of how the original
// connection was opened (e.g. mode=ro); LOAD_EXTENSION/WRITEFILE/READFILE/
// FTS3_TOKENIZER are included for the same file-system-access reason.
var forbiddenKeywordPattern = regexp.MustCompile(
	`(?i)\b(INSERT|UPDATE|DELETE|REPLACE|INTO|CREATE|ALTER|DROP|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|TRIGGER|GRANT|REVOKE|LOAD_EXTENSION|WRITEFILE|READFILE|FTS3_TOKENIZER)\b`,
)

// guardSelectOnly rejects any statement that is not a single read-only
// SELECT (optionally introduced by WITH), per the analysis-agent spec's
// "sql_query is read-only with a SELECT-only guard" requirement.
//
// It first reduces the query to a "code stream": every character OUTSIDE
// a single-quoted string, a double-quoted identifier, a -- line comment,
// or a /* */ block comment, tracked by an explicit character-by-character
// state machine (extractCodeStream) rather than a regex. A prior
// regex-based comment stripper matched /* ... */ across separate string
// literals -- e.g. SELECT '/*' ; DROP TABLE t ; SELECT '*/' -- which let
// the interior ';' and DROP be deleted as if they were a comment, letting
// a stacked write statement slip past the guard. Because the state
// machine enters string/identifier state on the first quote it sees, a
// /* or -- appearing inside a string can never be mistaken for the start
// of a real comment, and conversely a ';' or keyword appearing inside a
// string is correctly excluded from the code stream (so it can no longer
// cause a false rejection of a legitimate literal).
//
// All decisions below are made on the code stream only:
//  1. An unterminated string, quoted identifier, or block comment is
//     malformed input and is rejected (fail closed).
//  2. The first code token must be SELECT or WITH (case-insensitive).
//  3. Any ';' in the code stream followed by further non-whitespace code
//     means multiple statements were supplied (a single optional
//     trailing ';' is allowed).
//  4. Any whole-word forbidden keyword (see forbiddenKeywordPattern)
//     appearing in the code stream is rejected.
//
// This guard is a query-shape check, not a full SQL parser: it does not
// validate that the statement is syntactically well-formed SQL beyond
// what's needed to classify it, and it does not understand every SQLite
// quoting form (e.g. bracket or backtick identifiers). Combined with the
// read-only (mode=ro) connection used for the measurement store, it forms
// defense in depth rather than a single guaranteed control.
func guardSelectOnly(query string) error {
	code, err := extractCodeStream(query)
	if err != nil {
		return err
	}

	trimmed := strings.TrimSpace(code)
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

	if kw := forbiddenKeywordPattern.FindString(trimmed); kw != "" {
		return fmt.Errorf("sql_query: statement contains a disallowed keyword %q; only read-only SELECT is allowed", kw)
	}

	return nil
}

// codeScanState is the state of extractCodeStream's character-by-character
// scan of a SQL query.
type codeScanState int

const (
	stateCode codeScanState = iota
	stateSingleQuote
	stateDoubleQuote
	stateLineComment
	stateBlockComment
)

// extractCodeStream walks query one rune at a time and returns only the
// characters that lie outside string/identifier literals and comments
// (the "code"). String literals and comments are never merged together
// by this scan: a comment delimiter can only be recognized while in
// stateCode, so a /* or -- occurring inside an open string is treated as
// ordinary string content, not the start of a comment (and vice versa, a
// quote occurring inside a comment does not open a string). Where a
// comment is elided from the code stream, a single space is substituted
// so adjacent tokens are not accidentally joined (e.g. "SELECT/**/1"
// must not become the single token "SELECT1").
//
// An unterminated string, quoted identifier, or block comment is
// malformed input and returns an error; an unterminated line comment
// (running to end of input with no trailing newline) is valid and simply
// ends the scan.
func extractCodeStream(query string) (string, error) {
	var b strings.Builder
	r := []rune(query)
	n := len(r)
	state := stateCode

	for i := 0; i < n; i++ {
		c := r[i]
		switch state {
		case stateCode:
			switch {
			case c == '\'':
				state = stateSingleQuote
			case c == '"':
				state = stateDoubleQuote
			case c == '-' && i+1 < n && r[i+1] == '-':
				state = stateLineComment
				i++
			case c == '/' && i+1 < n && r[i+1] == '*':
				state = stateBlockComment
				i++
			default:
				b.WriteRune(c)
			}
		case stateSingleQuote:
			if c == '\'' {
				if i+1 < n && r[i+1] == '\'' {
					// SQL '' escape: a doubled quote stays in-string.
					i++
					continue
				}
				state = stateCode
			}
		case stateDoubleQuote:
			if c == '"' {
				if i+1 < n && r[i+1] == '"' {
					i++
					continue
				}
				state = stateCode
			}
		case stateLineComment:
			if c == '\n' {
				state = stateCode
				b.WriteRune(' ')
				b.WriteRune(c)
			}
		case stateBlockComment:
			if c == '*' && i+1 < n && r[i+1] == '/' {
				state = stateCode
				i++
				b.WriteRune(' ')
			}
		}
	}

	switch state {
	case stateSingleQuote:
		return "", fmt.Errorf("sql_query: unterminated string literal")
	case stateDoubleQuote:
		return "", fmt.Errorf("sql_query: unterminated quoted identifier")
	case stateBlockComment:
		return "", fmt.Errorf("sql_query: unterminated block comment")
	}

	return b.String(), nil
}
