package main

import (
	"testing"
	"time"
)

func TestLoadServerConfig(t *testing.T) {
	tests := []struct {
		name string
		env  map[string]string
		want serverConfig
	}{
		{
			name: "all defaults when env is empty",
			env:  map[string]string{},
			want: serverConfig{
				graphDBURL:         defaultGraphDBURL,
				graphDBRepo:        defaultGraphDBRepo,
				dbPath:             defaultDBPath,
				addr:               defaultAddr,
				deepSeekBaseURL:    defaultDeepSeekBaseURL,
				llmModelAnalysis:   defaultLLMModelAnalysis,
				deepSeekAPIKey:     "",
				agentMaxIterations: defaultAgentMaxIterations,
				agentTurnDeadline:  defaultAgentTurnDeadline,
			},
		},
		{
			name: "full override from env",
			env: map[string]string{
				"GRAPHDB_URL":          "http://graphdb:7200",
				"GRAPHDB_REPO":         "custom-repo",
				"MSR_DB_PATH":          "/data/msr.db",
				"SERVER_ADDR":          ":9090",
				"DEEPSEEK_BASE_URL":    "https://custom.deepseek.example",
				"LLM_MODEL_ANALYSIS":   "deepseek-v5",
				"DEEPSEEK_API_KEY":     "test-key-not-a-real-secret",
				"AGENT_MAX_ITERATIONS": "50",
				"AGENT_TURN_DEADLINE":  "90s",
			},
			want: serverConfig{
				graphDBURL:         "http://graphdb:7200",
				graphDBRepo:        "custom-repo",
				dbPath:             "/data/msr.db",
				addr:               ":9090",
				deepSeekBaseURL:    "https://custom.deepseek.example",
				llmModelAnalysis:   "deepseek-v5",
				deepSeekAPIKey:     "test-key-not-a-real-secret",
				agentMaxIterations: 50,
				agentTurnDeadline:  90 * time.Second,
			},
		},
		{
			name: "invalid/non-positive agent bounds fall back to defaults",
			env: map[string]string{
				"AGENT_MAX_ITERATIONS": "not-a-number",
				"AGENT_TURN_DEADLINE":  "0s",
			},
			want: serverConfig{
				graphDBURL:         defaultGraphDBURL,
				graphDBRepo:        defaultGraphDBRepo,
				dbPath:             defaultDBPath,
				addr:               defaultAddr,
				deepSeekBaseURL:    defaultDeepSeekBaseURL,
				llmModelAnalysis:   defaultLLMModelAnalysis,
				deepSeekAPIKey:     "",
				agentMaxIterations: defaultAgentMaxIterations,
				agentTurnDeadline:  defaultAgentTurnDeadline,
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			env := func(key string) string { return tt.env[key] }
			got := loadServerConfig(env)
			if got != tt.want {
				t.Errorf("loadServerConfig() = %+v, want %+v", got, tt.want)
			}
		})
	}
}

// TestDeepSeekAPIKeyDefaultsEmpty pins that the API secret has no committed
// default: loadServerConfig must never fabricate a key when the environment
// doesn't supply one.
func TestDeepSeekAPIKeyDefaultsEmpty(t *testing.T) {
	env := func(string) string { return "" }
	got := loadServerConfig(env)
	if got.deepSeekAPIKey != "" {
		t.Errorf("deepSeekAPIKey default = %q, want empty (no committed secret)", got.deepSeekAPIKey)
	}
}
