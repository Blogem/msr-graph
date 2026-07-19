package main

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
}

const (
	defaultGraphDBURL       = "http://localhost:7200"
	defaultGraphDBRepo      = "msr"
	defaultDBPath           = "data/msr.db"
	defaultAddr             = ":8080"
	defaultDeepSeekBaseURL  = "https://api.deepseek.com"
	defaultLLMModelAnalysis = "deepseek-v4-pro"
	defaultDeepSeekAPIKey   = ""
)

// loadServerConfig reads serverConfig from env (via the injected lookup,
// ordinarily os.Getenv), falling back to defaults for unset or empty values.
func loadServerConfig(env func(string) string) serverConfig {
	return serverConfig{
		graphDBURL:       envOrDefault(env, "GRAPHDB_URL", defaultGraphDBURL),
		graphDBRepo:      envOrDefault(env, "GRAPHDB_REPO", defaultGraphDBRepo),
		dbPath:           envOrDefault(env, "MSR_DB_PATH", defaultDBPath),
		addr:             envOrDefault(env, "SERVER_ADDR", defaultAddr),
		deepSeekBaseURL:  envOrDefault(env, "DEEPSEEK_BASE_URL", defaultDeepSeekBaseURL),
		llmModelAnalysis: envOrDefault(env, "LLM_MODEL_ANALYSIS", defaultLLMModelAnalysis),
		deepSeekAPIKey:   envOrDefault(env, "DEEPSEEK_API_KEY", defaultDeepSeekAPIKey),
	}
}

func envOrDefault(env func(string) string, key, def string) string {
	if v := env(key); v != "" {
		return v
	}
	return def
}
