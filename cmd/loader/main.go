// Command loader loads seed data into GraphDB and initializes the SQLite
// measurement store. Subcommands: seed, init-db, nist. The dispatch in run
// is kept flat and switch-based so adding a subcommand is a one-line change.
package main

import (
	"fmt"
	"io"
	"os"
)

func main() {
	if err := run(os.Args[1:], os.Getenv, os.Stdout, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, "loader:", err)
		os.Exit(1)
	}
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
