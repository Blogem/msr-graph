package main

// Task 7.8: pure unit test for the unit-allowlist shape generator (design
// D3, tasks 3.1/3.2). Never talks to GraphDB. The generator's internal
// API is not finalized (its own implementation lands in a parallel
// worktree), so per the pinned contract this test is deliberately
// black-box: it invokes the command via `go run ./cmd/gen-unit-shape`
// redirected to a temp -o path, then does a regex/string scan of the
// resulting Turtle to extract the sh:in ( ... ) IRI list and compares it
// to ontology/qudt-units.json's allowedUnits array, in order.
//
// Pinned flag contract: -o (output path, default
// deploy/graphdb/msr-shapes-units.ttl) and -units (allowlist JSON path,
// default ontology/qudt-units.json). This test never runs with default
// flags against the real repo tree (that would write into
// deploy/graphdb/*.ttl, a forbidden path for this change) -- it always
// passes an explicit -o pointing at t.TempDir(), and an explicit -units
// pointing at the real ontology/qudt-units.json so the comparison is
// against the actual source of truth regardless of cwd.
//
// This package (cmd/gen-unit-shape) does not exist as a buildable command
// yet in this worktree -- only this test file is authored here (pass 1).
// `go run ./cmd/gen-unit-shape ...` will fail until the coder's parallel
// branch adds main.go; expected pass-1 state (see handoff report).

import (
	"bufio"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"testing"
)

// repoRoot locates the module root from this test file's own path, same
// pattern as internal/graph/seed_integration_test.go's helper (not
// shared across packages, so re-declared here).
func repoRoot(t *testing.T) string {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("repoRoot: runtime.Caller failed")
	}
	// thisFile: <repoRoot>/cmd/gen-unit-shape/generate_test.go
	return filepath.Dir(filepath.Dir(filepath.Dir(thisFile)))
}

// qudtUnitsAllowedUnits reads the allowedUnits array straight out of
// ontology/qudt-units.json -- the single source of truth the generator
// must derive its sh:in list from (design D3).
func qudtUnitsAllowedUnits(t *testing.T, root string) []string {
	t.Helper()
	path := filepath.Join(root, "ontology", "qudt-units.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading %s: %v", path, err)
	}
	var doc struct {
		AllowedUnits []string `json:"allowedUnits"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		t.Fatalf("parsing %s: %v", path, err)
	}
	if len(doc.AllowedUnits) == 0 {
		t.Fatalf("%s: allowedUnits is empty -- fixture/contract assumption broken", path)
	}
	return doc.AllowedUnits
}

var (
	shInPattern       = regexp.MustCompile(`(?s)sh:in\s*\(([^)]*)\)`)
	prefixDeclPattern = regexp.MustCompile(`(?m)^\s*@prefix\s+([A-Za-z][\w-]*):\s*<([^>]+)>\s*\.`)
	iriTokenPattern   = regexp.MustCompile(`^<([^>]+)>$`)
	curieTokenPattern = regexp.MustCompile(`^([A-Za-z][\w-]*):([A-Za-z0-9_.\-]+)$`)
)

// extractShInIRIs is a deliberately rdflib-free black-box scan of
// generated Turtle: it finds the FIRST "sh:in ( ... )" list, resolves
// every token inside it to a full IRI string -- whether written as
// <...> or as a prefixed CURIE resolved via the file's own @prefix
// declarations -- and returns them in file order. This avoids depending
// on the generator's internal API while still pinning task 7.8's
// contract: the emitted sh:in list must equal
// ontology/qudt-units.json's allowedUnits array, in order.
func extractShInIRIs(t *testing.T, ttl string) []string {
	t.Helper()

	prefixes := map[string]string{}
	for _, m := range prefixDeclPattern.FindAllStringSubmatch(ttl, -1) {
		prefixes[m[1]] = m[2]
	}

	match := shInPattern.FindStringSubmatch(ttl)
	if match == nil {
		t.Fatalf("no sh:in ( ... ) list found in generated Turtle:\n%s", ttl)
	}
	list := match[1]

	var iris []string
	scanner := bufio.NewScanner(strings.NewReader(list))
	scanner.Split(bufio.ScanWords)
	for scanner.Scan() {
		tok := strings.TrimSpace(scanner.Text())
		if tok == "" {
			continue
		}
		if m := iriTokenPattern.FindStringSubmatch(tok); m != nil {
			iris = append(iris, m[1])
			continue
		}
		if m := curieTokenPattern.FindStringSubmatch(tok); m != nil {
			ns, ok := prefixes[m[1]]
			if !ok {
				t.Fatalf("sh:in list token %q uses undeclared prefix %q -- generated Turtle:\n%s", tok, m[1], ttl)
			}
			iris = append(iris, ns+m[2])
			continue
		}
		t.Fatalf("sh:in list token %q did not parse as an IRI or CURIE -- generated Turtle:\n%s", tok, ttl)
	}
	return iris
}

// TestGenerate_ShInListMatchesQUDTAllowlist pins task 7.8 / design D3:
// the generator's emitted sh:in ( ... ) list contains exactly the IRIs in
// ontology/qudt-units.json's allowedUnits array, in the same order. Pure
// unit test -- never talks to GraphDB, only runs the generator binary via
// `go run` and does a string/regex scan of its output file.
func TestGenerate_ShInListMatchesQUDTAllowlist(t *testing.T) {
	root := repoRoot(t)
	want := qudtUnitsAllowedUnits(t, root)

	outPath := filepath.Join(t.TempDir(), "msr-shapes-units.ttl")
	unitsPath := filepath.Join(root, "ontology", "qudt-units.json")

	cmd := exec.Command("go", "run", "./cmd/gen-unit-shape", "-o", outPath, "-units", unitsPath)
	cmd.Dir = root
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("`go run ./cmd/gen-unit-shape -o %s -units %s` failed: %v\noutput:\n%s", outPath, unitsPath, err, out)
	}

	generated, err := os.ReadFile(outPath)
	if err != nil {
		t.Fatalf("reading generated shapes file %s: %v", outPath, err)
	}

	got := extractShInIRIs(t, string(generated))

	if len(got) != len(want) {
		t.Fatalf("sh:in list has %d IRIs, want %d\n got: %v\nwant: %v", len(got), len(want), got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("sh:in list[%d] = %q, want %q (order must match ontology/qudt-units.json allowedUnits)\n got: %v\nwant: %v", i, got[i], want[i], got, want)
		}
	}
}

// TestGenerate_FlagsHaveDocumentedDefaults is a light smoke test for the
// pinned default-flag contract (-o defaults to
// deploy/graphdb/msr-shapes-units.ttl, -units defaults to
// ontology/qudt-units.json). It only inspects -h/--help text, so it never
// writes into deploy/graphdb (a forbidden path for this change).
func TestGenerate_FlagsHaveDocumentedDefaults(t *testing.T) {
	root := repoRoot(t)

	cmd := exec.Command("go", "run", "./cmd/gen-unit-shape", "-h")
	cmd.Dir = root
	// `-h` conventionally causes Go's flag package to print usage and
	// exit non-zero; the assertion is on the text, not the exit code.
	out, _ := cmd.CombinedOutput()
	text := string(out)

	for _, want := range []string{"-o", "deploy/graphdb/msr-shapes-units.ttl", "-units", "ontology/qudt-units.json"} {
		if !strings.Contains(text, want) {
			t.Errorf("`go run ./cmd/gen-unit-shape -h` output does not mention %q (pinned default flag contract); output:\n%s", want, text)
		}
	}
}
