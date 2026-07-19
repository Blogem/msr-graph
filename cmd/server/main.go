// Command server runs the msr-graph HTTP API. It wires the grounded
// analysis agent (GraphDB-backed sparql_query, read-only-SQLite-backed
// sql_query, sandbox-pool-backed run_python) to the stateless POST
// /api/chat SSE endpoint; the review/checkpoint APIs and the embedded
// frontend are added by later tasks.
package main

import (
	"context"
	"database/sql"
	"log"
	"net/http"
	"os"

	_ "modernc.org/sqlite"

	"github.com/blogem/msr-graph/internal/agent"
	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/sandbox"
)

func main() {
	cfg := loadServerConfig(os.Getenv)

	gc := graph.New(cfg.graphDBURL, cfg.graphDBRepo, nil)

	// The measurement store is opened read-only: the chat request path must
	// never write SQLite (spec "Stateless POST /api/chat endpoint"). The
	// SELECT-only guard in internal/agent's sql_query tool rejects any
	// statement that isn't a single read-only SELECT before it reaches this
	// connection; this mode=ro open is the defense-in-depth compensating
	// control on the main database, not a substitute for the guard (e.g. it
	// does not stop ATTACH from opening a separate, writable database file).
	db, err := sql.Open("sqlite", "file:"+cfg.dbPath+"?mode=ro&_pragma=busy_timeout(5000)")
	if err != nil {
		log.Fatalf("server: open read-only measurement store %s: %v", cfg.dbPath, err)
	}
	defer db.Close()

	sbCfg, err := sandbox.LoadConfig()
	if err != nil {
		log.Fatalf("server: load sandbox config: %v", err)
	}
	rt, err := sandbox.NewDockerRuntime()
	if err != nil {
		log.Fatalf("server: create docker runtime: %v", err)
	}
	pool, err := sandbox.New(context.Background(), sbCfg, rt)
	if err != nil {
		log.Fatalf("server: create sandbox pool: %v", err)
	}
	defer func() {
		if err := pool.Close(); err != nil {
			log.Printf("server: sandbox pool close: %v", err)
		}
	}()

	llm := agent.NewDeepSeekClient(agent.LLMConfig{
		BaseURL: cfg.deepSeekBaseURL,
		Model:   cfg.llmModelAnalysis,
		APIKey:  cfg.deepSeekAPIKey,
	}, nil)

	tools := []agent.Tool{
		agent.NewSPARQLTool(gc),
		agent.NewSQLTool(db),
		agent.NewPythonTool(pool),
	}
	ag := agent.New(llm, tools, agent.DefaultConfig())
	prompts := agent.NewPromptCache(gc)

	mux := newMux(newChatHandler(ag, prompts))

	log.Printf("server listening on %s", cfg.addr)
	if err := http.ListenAndServe(cfg.addr, mux); err != nil {
		log.Fatal(err)
	}
}
