package store

import (
	"context"
	"database/sql"
	"fmt"
)

// MeasurementRow is a typed measurement_value row. Nullable numeric/text
// columns use sql.Null* so callers can distinguish 0/"" from absent.
type MeasurementRow struct {
	Locator      string
	Salt         sql.NullString
	Property     sql.NullString
	C0           sql.NullFloat64
	C1           sql.NullFloat64
	C2           sql.NullFloat64
	C3           sql.NullFloat64
	C4           sql.NullFloat64
	TMin         sql.NullFloat64
	TMax         sql.NullFloat64
	EquationForm sql.NullString
	Uncertainty  sql.NullString
	Source       string // "nist" | "document" (NOT NULL by schema)
	DocID        sql.NullString
}

// upsertSQL inserts a measurement_value row, or updates every non-PK column
// from the excluded values when a row with the same locator already exists.
// This keeps writes idempotent by locator: re-upserting identical values is
// a no-op in effect, and re-upserting changed values updates the row in
// place rather than creating a duplicate.
const upsertSQL = `INSERT INTO measurement_value
	(locator, salt, property, c0, c1, c2, c3, c4, t_min, t_max, equation_form, uncertainty, source, doc_id)
	VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	ON CONFLICT(locator) DO UPDATE SET
		salt = excluded.salt,
		property = excluded.property,
		c0 = excluded.c0,
		c1 = excluded.c1,
		c2 = excluded.c2,
		c3 = excluded.c3,
		c4 = excluded.c4,
		t_min = excluded.t_min,
		t_max = excluded.t_max,
		equation_form = excluded.equation_form,
		uncertainty = excluded.uncertainty,
		source = excluded.source,
		doc_id = excluded.doc_id`

// Upsert writes all rows in a single transaction, upserting on the locator
// primary key (INSERT ... ON CONFLICT(locator) DO UPDATE). Re-upserting the
// same locator with identical values leaves the row count and values
// unchanged; re-upserting with a changed value updates the row in place (no
// duplicate row). db must be one opened via Open (pinned
// journal_mode=DELETE / busy_timeout). An empty rows slice is a no-op. On
// any error, the transaction is rolled back and the first error is returned
// wrapped.
func Upsert(ctx context.Context, db *sql.DB, rows []MeasurementRow) error {
	if len(rows) == 0 {
		return nil
	}

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("store: upsert: %w", err)
	}

	stmt, err := tx.PrepareContext(ctx, upsertSQL)
	if err != nil {
		_ = tx.Rollback()
		return fmt.Errorf("store: upsert: %w", err)
	}
	defer stmt.Close()

	for _, row := range rows {
		if _, err := stmt.ExecContext(ctx,
			row.Locator,
			row.Salt,
			row.Property,
			row.C0,
			row.C1,
			row.C2,
			row.C3,
			row.C4,
			row.TMin,
			row.TMax,
			row.EquationForm,
			row.Uncertainty,
			row.Source,
			row.DocID,
		); err != nil {
			_ = tx.Rollback()
			return fmt.Errorf("store: upsert: %w", err)
		}
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf("store: upsert: %w", err)
	}
	return nil
}
