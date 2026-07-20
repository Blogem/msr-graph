// Command server runs the msr-graph HTTP API. It wires the grounded
// analysis agent (GraphDB-backed sparql_query, read-only-SQLite-backed
// sql_query, sandbox-pool-backed run_python) to the stateless POST
// /api/chat SSE endpoint, and the proposal review + checkpoint APIs to
// the proposal and checkpoint engines; the embedded frontend is added by
// a later task.
package main

import (
	"context"
	"database/sql"
	"log"
	"net/http"
	"os"

	_ "modernc.org/sqlite"

	"github.com/blogem/msr-graph/internal/agent"
	"github.com/blogem/msr-graph/internal/checkpoint"
	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/proposal"
	"github.com/blogem/msr-graph/internal/sandbox"
)

// defaultCheckpointRoot is the checkpoints base directory checkpoint.Engine
// writes each labelled checkpoint under (data/checkpoints/{label}/). A
// literal is sufficient for the POC; promoting it to an env-configurable
// serverConfig field is straightforward follow-up if a deployment needs a
// different location.
const defaultCheckpointRoot = "data/checkpoints"

func main() {
	cfg := loadServerConfig(os.Getenv)

	gc := graph.New(cfg.graphDBURL, cfg.graphDBRepo, nil)

	// The measurement store is opened read-only: the chat request path must
	// never write SQLite (spec "Stateless POST /api/chat endpoint"). The
	// SELECT-only guard in internal/agent's sql_query tool rejects any
	// statement that isn't a single read-only SELECT before it reaches this
	// connection; this mode=ro open (plus query_only, below) is the
	// defense-in-depth compensating control on the connection, not a
	// substitute for the guard. mode=ro alone still lets ATTACH open a
	// separate, writable database file and write to it (SQLite's read-only
	// open only protects the file named in the DSN); the query_only pragma
	// additionally puts the whole connection into read-only mode, which
	// SQLite documents as rejecting writes to attached databases too, so a
	// query that slipped past the guard still can't write anywhere via this
	// connection.
	db, err := sql.Open("sqlite", readOnlyMeasurementStoreDSN(cfg.dbPath))
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
	agentCfg := agent.DefaultConfig()
	agentCfg.MaxIterations = cfg.agentMaxIterations
	agentCfg.TurnDeadline = cfg.agentTurnDeadline
	ag := agent.New(llm, tools, agentCfg)
	prompts := agent.NewPromptCache(gc)

	// The proposal and checkpoint engines reuse gc, the same full-
	// capability graph client the chat path's sparql_query tool reads
	// through -- unlike db above, gc is never opened read-only, since
	// approving a proposal and restoring a checkpoint both need to write
	// the graph.
	propEngine := proposal.NewEngine(gc)
	ckptEngine := checkpoint.NewEngine(gc, cfg.dbPath, defaultCheckpointRoot)

	mux := newMux(newChatHandler(ag, prompts), gc, propEngine, ckptEngine)

	log.Printf("server listening on %s", cfg.addr)
	if err := http.ListenAndServe(cfg.addr, mux); err != nil {
		log.Fatal(err)
	}
}

// readOnlyMeasurementStoreDSN builds the modernc.org/sqlite DSN used to open
// the measurement store for the chat request path. See the comment at its
// call site in main for why both mode=ro and query_only are needed: mode=ro
// alone does not stop a query from ATTACHing a separate, writable database
// file and writing to it, but query_only puts the whole connection (all
// attached databases included) into read-only mode.
func readOnlyMeasurementStoreDSN(dbPath string) string {
	return "file:" + dbPath + "?mode=ro&_pragma=busy_timeout(5000)&_pragma=query_only(true)"
}
