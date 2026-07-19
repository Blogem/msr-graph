package agent

import "time"

// defaultMaxIterations and defaultTurnDeadline are the loop bounds used
// by DefaultConfig (design D1): 10 iterations comfortably covers
// ground -> fetch -> compute -> (compare) with headroom, and 120s
// bounds a stuck turn without truncating a legitimate multi-script
// comparison. Both are config-overridable.
const (
	defaultMaxIterations = 10
	defaultTurnDeadline  = 120 * time.Second
)

// Config bounds one agent turn.
type Config struct {
	// MaxIterations caps the number of model round-trips in a single
	// turn's tool-use loop, guarding against a runaway model that never
	// stops requesting tools.
	MaxIterations int
	// TurnDeadline bounds the wall-clock time of one whole turn (all
	// iterations combined), distinct from the sandbox's own per-script
	// timeout.
	TurnDeadline time.Duration
}

// DefaultConfig returns the production defaults: 10 iterations and a
// 120s per-turn deadline.
func DefaultConfig() Config {
	return Config{
		MaxIterations: defaultMaxIterations,
		TurnDeadline:  defaultTurnDeadline,
	}
}
