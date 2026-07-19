package agent

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/sandbox"
)

// fakeSandbox is a scripted Sandbox stub: it records the script it was
// called with and returns canned output, so tests never contact a
// container runtime (design D6).
type fakeSandbox struct {
	stdout   []byte
	stderr   []byte
	exitCode int
	err      error

	gotScript []byte
}

func (f *fakeSandbox) Run(ctx context.Context, script []byte) (stdout, stderr []byte, exitCode int, err error) {
	f.gotScript = script
	return f.stdout, f.stderr, f.exitCode, f.err
}

func TestPythonTool_Success(t *testing.T) {
	wantStdout := `{"density":1.974}`
	fake := &fakeSandbox{stdout: []byte(wantStdout), exitCode: 0}
	tool := NewPythonTool(fake)

	var events []Event
	emit := func(e Event) { events = append(events, e) }

	args, err := json.Marshal(runPythonArgs{Script: "print('hi')"})
	if err != nil {
		t.Fatalf("marshal args: %v", err)
	}

	result, err := tool.Call(context.Background(), string(args), emit)
	if err != nil {
		t.Fatalf("Call returned error: %v", err)
	}
	if result != wantStdout {
		t.Errorf("result = %q, want %q", result, wantStdout)
	}

	if len(events) != 1 {
		t.Fatalf("got %d events, want exactly 1", len(events))
	}
	ev := events[0]
	if ev.Type != EventScriptRun {
		t.Errorf("event type = %q, want %q", ev.Type, EventScriptRun)
	}
	if ev.ScriptRun == nil {
		t.Fatal("event ScriptRun payload is nil")
	}
	if ev.ScriptRun.Source != "print('hi')" {
		t.Errorf("ScriptRun.Source = %q, want %q", ev.ScriptRun.Source, "print('hi')")
	}
	if ev.ScriptRun.Stdout != wantStdout {
		t.Errorf("ScriptRun.Stdout = %q, want %q", ev.ScriptRun.Stdout, wantStdout)
	}
	if ev.ScriptRun.ExitCode != 0 {
		t.Errorf("ScriptRun.ExitCode = %d, want 0", ev.ScriptRun.ExitCode)
	}
	if ev.ScriptRun.SandboxID == "" {
		t.Error("ScriptRun.SandboxID is empty, want a non-empty correlation id")
	}
}

func TestPythonTool_NonZeroExit(t *testing.T) {
	wantStderr := "Traceback: boom"
	fake := &fakeSandbox{stderr: []byte(wantStderr), exitCode: 1}
	tool := NewPythonTool(fake)

	var events []Event
	emit := func(e Event) { events = append(events, e) }

	args, _ := json.Marshal(runPythonArgs{Script: "raise ValueError()"})
	result, err := tool.Call(context.Background(), string(args), emit)
	if err != nil {
		t.Fatalf("Call returned error for a non-zero exit, want nil (this is a normal result): %v", err)
	}

	var failure scriptFailure
	if jsonErr := json.Unmarshal([]byte(result), &failure); jsonErr != nil {
		t.Fatalf("result is not valid JSON: %v (result: %q)", jsonErr, result)
	}
	if !strings.Contains(failure.Error, "1") {
		t.Errorf("failure.Error = %q, want it to mention exit code 1", failure.Error)
	}
	if failure.Stderr != wantStderr {
		t.Errorf("failure.Stderr = %q, want %q", failure.Stderr, wantStderr)
	}

	if len(events) != 1 {
		t.Fatalf("got %d events, want exactly 1", len(events))
	}
	if events[0].ScriptRun.ExitCode != 1 {
		t.Errorf("ScriptRun.ExitCode = %d, want 1", events[0].ScriptRun.ExitCode)
	}
	if events[0].ScriptRun.Stderr != wantStderr {
		t.Errorf("ScriptRun.Stderr = %q, want %q", events[0].ScriptRun.Stderr, wantStderr)
	}
}

func TestPythonTool_InfraError(t *testing.T) {
	fake := &fakeSandbox{err: sandbox.ErrTimeout}
	tool := NewPythonTool(fake)

	var events []Event
	emit := func(e Event) { events = append(events, e) }

	args, _ := json.Marshal(runPythonArgs{Script: "while True: pass"})
	_, err := tool.Call(context.Background(), string(args), emit)
	if err == nil {
		t.Fatal("Call returned nil error, want an error surfacing the timeout")
	}
	if !strings.Contains(err.Error(), "timeout") {
		t.Errorf("error = %v, want it to mention timeout", err)
	}

	if len(events) != 1 {
		t.Fatalf("got %d events, want exactly 1 (best-effort emit even on infra error)", len(events))
	}
	if events[0].Type != EventScriptRun {
		t.Errorf("event type = %q, want %q", events[0].Type, EventScriptRun)
	}
}

func TestPythonTool_Truncation(t *testing.T) {
	bigStdout := strings.Repeat("x", truncateLimit+100)
	fake := &fakeSandbox{stdout: []byte(bigStdout), exitCode: 0}
	tool := NewPythonTool(fake)

	var events []Event
	emit := func(e Event) { events = append(events, e) }

	args, _ := json.Marshal(runPythonArgs{Script: "print('x' * 5000)"})
	result, err := tool.Call(context.Background(), string(args), emit)
	if err != nil {
		t.Fatalf("Call returned error: %v", err)
	}

	if result != bigStdout {
		t.Errorf("tool result to the model was truncated, want the full stdout (len %d, got len %d)", len(bigStdout), len(result))
	}

	if len(events) != 1 {
		t.Fatalf("got %d events, want exactly 1", len(events))
	}
	ev := events[0]
	if !ev.ScriptRun.Truncated {
		t.Error("ScriptRun.Truncated = false, want true for an oversized stdout")
	}
	if len(ev.ScriptRun.Stdout) != truncateLimit {
		t.Errorf("ScriptRun.Stdout len = %d, want capped at %d", len(ev.ScriptRun.Stdout), truncateLimit)
	}
}

func TestPythonTool_BadArguments(t *testing.T) {
	tool := NewPythonTool(&fakeSandbox{})

	tests := []struct {
		name string
		args string
	}{
		{"invalid JSON", `{not json`},
		{"blank script", `{"script": "   "}`},
		{"missing script", `{}`},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			_, err := tool.Call(context.Background(), tc.args, func(Event) {})
			if err == nil {
				t.Errorf("Call(%q) returned nil error, want a descriptive error", tc.args)
			}
		})
	}
}

func TestPythonTool_Spec(t *testing.T) {
	tool := NewPythonTool(&fakeSandbox{})
	spec := tool.Spec()

	if spec.Name != "run_python" {
		t.Errorf("Name = %q, want %q", spec.Name, "run_python")
	}

	for _, want := range []string{"/data/msr.db", "numpy", "pandas", "stdout"} {
		if !strings.Contains(spec.Description, want) {
			t.Errorf("Description does not contain %q:\n%s", want, spec.Description)
		}
	}

	var schema map[string]any
	if err := json.Unmarshal(spec.Parameters, &schema); err != nil {
		t.Fatalf("Parameters is not valid JSON: %v", err)
	}
	if schema["type"] != "object" {
		t.Errorf("Parameters.type = %v, want %q", schema["type"], "object")
	}
	required, ok := schema["required"].([]any)
	if !ok || len(required) != 1 || required[0] != "script" {
		t.Errorf("Parameters.required = %v, want [\"script\"]", schema["required"])
	}
}
