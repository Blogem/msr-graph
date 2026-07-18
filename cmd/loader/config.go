package main

// config holds the loader's runtime configuration, sourced from
// environment variables with defaults so `go run ./cmd/loader <subcommand>`
// works unconfigured from the repo root against a local GraphDB, while the
// compose file can override each value via environment.
type config struct {
	// graphDBURL is the GraphDB base URL (env GRAPHDB_URL).
	graphDBURL string
	// graphDBRepo is the GraphDB repository name (env GRAPHDB_REPO).
	graphDBRepo string
	// ontologyDir is the directory containing the seed turtle files (env
	// MSR_ONTOLOGY_DIR).
	ontologyDir string
	// dbPath is the SQLite measurement store path (env MSR_DB_PATH).
	dbPath string
}

const (
	defaultGraphDBURL  = "http://localhost:7200"
	defaultGraphDBRepo = "msr"
	defaultOntologyDir = "ontology"
	defaultDBPath      = "data/msr.db"
)

// loadConfig reads config from env (via the injected lookup, ordinarily
// os.Getenv), falling back to defaults for unset or empty values.
func loadConfig(env func(string) string) config {
	return config{
		graphDBURL:  envOrDefault(env, "GRAPHDB_URL", defaultGraphDBURL),
		graphDBRepo: envOrDefault(env, "GRAPHDB_REPO", defaultGraphDBRepo),
		ontologyDir: envOrDefault(env, "MSR_ONTOLOGY_DIR", defaultOntologyDir),
		dbPath:      envOrDefault(env, "MSR_DB_PATH", defaultDBPath),
	}
}

func envOrDefault(env func(string) string, key, def string) string {
	if v := env(key); v != "" {
		return v
	}
	return def
}
