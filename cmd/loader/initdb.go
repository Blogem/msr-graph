package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/blogem/msr-graph/internal/store"
)

// runInitDB implements `loader init-db`: it opens (creating if absent) the
// SQLite measurement store at the configured path via store.Open, then
// applies the idempotent measurement_value DDL via store.Init (design D4).
func runInitDB(env func(string) string, stdout io.Writer) error {
	cfg := loadConfig(env)

	dir := filepath.Dir(cfg.dbPath)
	if err := os.MkdirAll(dir, 0o775); err != nil {
		return fmt.Errorf("init-db: creating database directory %s: %w", dir, err)
	}

	db, err := store.Open(cfg.dbPath)
	if err != nil {
		return fmt.Errorf("init-db: opening %s: %w", cfg.dbPath, err)
	}
	defer db.Close()

	if err := store.Init(context.Background(), db); err != nil {
		return fmt.Errorf("init-db: applying schema: %w", err)
	}

	fmt.Fprintf(stdout, "loader: init-db: initialized database at %s\n", cfg.dbPath)
	return nil
}
