package main

import (
	"strconv"
	"time"
)

// serverConfig holds the server's runtime configuration, sourced from
// environment variables with defaults so `go run ./cmd/server` works
// unconfigured from the repo root against a local GraphDB, while the compose
// file can override each value via environment.
type serverConfig struct {
	// graphDBURL is the GraphDB base URL (env GRAPHDB_URL).
	graphDBURL string
	// graphDBRepo is the GraphDB repository name (env GRAPHDB_REPO).
	graphDBRepo string
	// dbPath is the SQLite measurement store path (env MSR_DB_PATH).
	dbPath string
	// addr is the HTTP listen address (env SERVER_ADDR).
	addr string
	// deepSeekBaseURL is the OpenAI-compatible base URL for DeepSeek V4 Pro
	// (env DEEPSEEK_BASE_URL).
	deepSeekBaseURL string
	// llmModelAnalysis is the analysis-agent model identifier (env
	// LLM_MODEL_ANALYSIS).
	llmModelAnalysis string
	// deepSeekAPIKey is the DeepSeek API secret (env DEEPSEEK_API_KEY).
	// Sourced from the host environment only; never committed and has no
	// default value.
	deepSeekAPIKey string
	// agentMaxIterations caps the model round-trips in one chat turn's
	// tool-use loop (env AGENT_MAX_ITERATIONS); overrides agent.DefaultConfig.
	agentMaxIterations int
	// agentTurnDeadline bounds one chat turn's wall-clock across all
	// iterations (env AGENT_TURN_DEADLINE, a Go duration like "600s" / "10m").
	agentTurnDeadline time.Duration
	// checkpointDir is the checkpoints base directory checkpoint.Engine
	// writes each labelled checkpoint under, as data/checkpoints/{label}/
	// (env MSR_CHECKPOINT_DIR). This must be set to a path under the same
	// persistent volume as dbPath in any deployment where the working
	// directory isn't already on that volume -- e.g. the Docker image runs
	// with WORKDIR /app while dbPath is bind-mounted at /data/msr.db, so
	// the relative default below would resolve to the non-persistent
	// /app/data/checkpoints inside the container unless MSR_CHECKPOINT_DIR
	// is set (e.g. to /data/checkpoints) in that environment.
	checkpointDir string
}

const (
	defaultGraphDBURL       = "http://localhost:7200"
	defaultGraphDBRepo      = "msr"
	defaultDBPath           = "data/msr.db"
	defaultAddr             = ":8080"
	defaultDeepSeekBaseURL  = "https://api.deepseek.com"
	defaultLLMModelAnalysis = "deepseek-v4-pro"
	defaultDeepSeekAPIKey   = ""
	// defaultAgentMaxIterations and defaultAgentTurnDeadline give the grounded
	// agent generous headroom for multi-step ground -> fetch -> compute ->
	// compare questions. They are intentionally higher than agent.DefaultConfig's
	// library bounds (10 / 120s), which proved tight for real questions against
	// the live graph. Both are env-overridable (AGENT_MAX_ITERATIONS,
	// AGENT_TURN_DEADLINE).
	defaultAgentMaxIterations = 30
	defaultAgentTurnDeadline  = 10 * time.Minute
	// defaultCheckpointDir is the checkpoints base directory used when
	// MSR_CHECKPOINT_DIR is unset -- a relative path sufficient for
	// `go run ./cmd/server` from the repo root, but deliberately not
	// assumed to be correct in every deployment (see checkpointDir's
	// field comment above): the Docker Compose deployment must override
	// it to a path under the same persistent volume as MSR_DB_PATH.
	defaultCheckpointDir = "data/checkpoints"
)

// loadServerConfig reads serverConfig from env (via the injected lookup,
// ordinarily os.Getenv), falling back to defaults for unset or empty values.
func loadServerConfig(env func(string) string) serverConfig {
	return serverConfig{
		graphDBURL:         envOrDefault(env, "GRAPHDB_URL", defaultGraphDBURL),
		graphDBRepo:        envOrDefault(env, "GRAPHDB_REPO", defaultGraphDBRepo),
		dbPath:             envOrDefault(env, "MSR_DB_PATH", defaultDBPath),
		addr:               envOrDefault(env, "SERVER_ADDR", defaultAddr),
		deepSeekBaseURL:    envOrDefault(env, "DEEPSEEK_BASE_URL", defaultDeepSeekBaseURL),
		llmModelAnalysis:   envOrDefault(env, "LLM_MODEL_ANALYSIS", defaultLLMModelAnalysis),
		deepSeekAPIKey:     envOrDefault(env, "DEEPSEEK_API_KEY", defaultDeepSeekAPIKey),
		agentMaxIterations: envIntOrDefault(env, "AGENT_MAX_ITERATIONS", defaultAgentMaxIterations),
		agentTurnDeadline:  envDurationOrDefault(env, "AGENT_TURN_DEADLINE", defaultAgentTurnDeadline),
		checkpointDir:      envOrDefault(env, "MSR_CHECKPOINT_DIR", defaultCheckpointDir),
	}
}

func envOrDefault(env func(string) string, key, def string) string {
	if v := env(key); v != "" {
		return v
	}
	return def
}

// envIntOrDefault reads a positive integer from env. An unset, empty,
// non-numeric, or non-positive value falls back to def -- a zero or negative
// bound would disable the agent loop entirely, so it is treated as unset.
func envIntOrDefault(env func(string) string, key string, def int) int {
	v := env(key)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil || n <= 0 {
		return def
	}
	return n
}

// envDurationOrDefault reads a Go duration (e.g. "600s", "10m") from env. An
// unset, empty, unparseable, or non-positive value falls back to def.
func envDurationOrDefault(env func(string) string, key string, def time.Duration) time.Duration {
	v := env(key)
	if v == "" {
		return def
	}
	d, err := time.ParseDuration(v)
	if err != nil || d <= 0 {
		return def
	}
	return d
}
