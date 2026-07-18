// Package store provides the SQLite-backed measurement value store,
// including idempotent schema initialization and a connection-opening
// helper that pins the runtime contract (journal_mode=DELETE,
// busy_timeout). Implementation is added by later tasks.
package store
