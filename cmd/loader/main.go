// Command loader loads seed data into GraphDB and initializes the SQLite
// measurement store. Subcommands: seed, init-db, nist. The dispatch in run
// is kept flat and switch-based so adding a subcommand is a one-line change.
package main

import (
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/blogem/msr-graph/internal/graph"
)

func main() {
	if err := run(os.Args[1:], os.Getenv, os.Stdout, os.Stderr); err != nil {
		reportError(os.Stderr, err)
		os.Exit(1)
	}
}

// reportError prints err to w. A write rejected by SHACL validation
// (task 5.2, design D5) is reported distinctly from other write
// failures -- e.g. transport errors or a generic 5xx -- by naming the
// failing constraint(s) and focus node(s) so the operator sees a SHACL
// rejection at a glance, not just an opaque error string. Any other
// error (including wrapped generic write failures) falls through to the
// existing one-line format.
//
// Note for the extraction (Python) writers: they hit the same GraphDB
// write endpoints and should surface this same distinction (a validation
// rejection vs. a transport/5xx failure) in their own error reporting;
// this function is the Go-side reference behavior, not a shared
// implementation.
func reportError(w io.Writer, err error) {
	var ve *graph.ValidationError
	if errors.As(err, &ve) {
		fmt.Fprintln(w, "loader: SHACL validation rejected the write (not a transport/5xx failure):")
		if len(ve.Violations) == 0 {
			fmt.Fprintln(w, "loader:   (no violations parsed; raw report follows)")
			fmt.Fprintln(w, ve.Report)
			return
		}
		for _, v := range ve.Violations {
			fmt.Fprintf(w, "loader:   - focus node=%s constraint=%s shape=%s path=%s message=%s\n",
				orUnknown(v.FocusNode), orUnknown(v.SourceConstraintComponent), orUnknown(v.SourceShape), orUnknown(v.ResultPath), orUnknown(v.Message))
		}
		return
	}
	fmt.Fprintln(w, "loader:", err)
}

// orUnknown renders s, or a placeholder if the corresponding violation
// field could not be extracted from the validation report.
func orUnknown(s string) string {
	if s == "" {
		return "(unknown)"
	}
	return s
}

// run dispatches to the requested subcommand. It is factored out of main
// (rather than inlined) so tests can exercise dispatch and the subcommands
// directly, injecting an env lookup and capturing output, without invoking
// os.Exit.
func run(args []string, env func(string) string, stdout, stderr io.Writer) error {
	if len(args) < 1 {
		printUsage(stderr)
		return fmt.Errorf("missing subcommand")
	}

	switch args[0] {
	case "seed":
		return runSeed(env, stdout)
	case "init-db":
		return runInitDB(env, stdout)
	case "nist":
		return runNist(env, stdout)
	case "-h", "--help", "help":
		printUsage(stdout)
		return nil
	default:
		printUsage(stderr)
		return fmt.Errorf("unknown subcommand %q", args[0])
	}
}

func printUsage(w io.Writer) {
	fmt.Fprintln(w, "usage: loader <subcommand>")
	fmt.Fprintln(w)
	fmt.Fprintln(w, "subcommands:")
	fmt.Fprintln(w, "  seed      PUT the ontology/vocab/data seed files into their named graphs and ensure urn:msr:staging exists")
	fmt.Fprintln(w, "  init-db   initialize the SQLite measurement_value schema")
	fmt.Fprintln(w, "  nist      ingest the vendored NIST SRD 27 property files into SQLite + urn:msr:data")
}
