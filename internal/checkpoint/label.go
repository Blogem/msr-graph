package checkpoint

import (
	"errors"
	"regexp"
)

// ErrInvalidLabel is returned by ValidateLabel (and any Engine method
// that calls it) when a checkpoint label falls outside the conservative
// filesystem-safe charset. Callers (the HTTP layer) map it to a 400.
var ErrInvalidLabel = errors.New("checkpoint: invalid label")

// labelPattern is the conservative filesystem-safe charset a checkpoint
// label must match in full: ASCII letters, digits, dash, and
// underscore, one or more characters. No dots (blocks "." and ".."), no
// slashes, no whitespace, nothing that a path segment could interpret
// as traversal (design D8).
var labelPattern = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

// ValidateLabel rejects any label outside the conservative
// filesystem-safe charset (design D8, task 4.3). It MUST be called
// before any path is built from label -- Create, Restore, and any
// label-scoped List lookup call it first so an unsafe label (empty,
// containing "..", "/", or other path-traversal characters) never
// reaches os.MkdirAll, os.Open, or any other filesystem call.
func ValidateLabel(label string) error {
	if !labelPattern.MatchString(label) {
		return ErrInvalidLabel
	}
	return nil
}
