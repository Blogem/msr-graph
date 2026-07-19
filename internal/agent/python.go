package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"
)

// runPythonDescription is the tool description advertised to the model. It
// states the runtime contract every generated script must target (design
// D2): the read-only database path and schema, the preinstalled libraries,
// the JSON-on-stdout result contract, and the sandbox's isolation
// properties -- so the model never has to guess where or how to read the
// data, and never attempts computation itself.
const runPythonDescription = `Execute a Python script in an isolated sandbox to perform ALL numeric computation -- equation evaluation, aggregation, comparison, or any other arithmetic. Never compute numbers yourself; always use this tool for that.

Runtime contract:
- A read-only SQLite database is mounted at /data/msr.db. It contains the table measurement_value with columns: locator, salt, property, c0, c1, c2, c3, c4, t_min, t_max, equation_form, uncertainty, source, doc_id.
- numpy and pandas are preinstalled and available to import.
- The script MUST print its result as JSON to stdout; that JSON is returned as the tool result.
- Network access is disabled and the filesystem is read-only except for /tmp (scratch space only; not persisted).`

// Sandbox is the seam this tool consumes: it submits script source and
// gets back the verbatim exit status of one run. *sandbox.Pool satisfies
// this interface; tests inject a fake so no test contacts a container
// runtime (design D6).
type Sandbox interface {
	Run(ctx context.Context, script []byte) (stdout, stderr []byte, exitCode int, err error)
}

// pythonTool implements Tool by submitting script source to a Sandbox.
type pythonTool struct {
	sb Sandbox
}

// NewPythonTool builds the run_python Tool backed by sb. Production code
// passes a *sandbox.Pool; tests inject a fake Sandbox.
func NewPythonTool(sb Sandbox) Tool {
	return &pythonTool{sb: sb}
}

// runPythonParams is the JSON Schema for run_python's arguments: a single
// required "script" string.
const runPythonParams = `{
  "type": "object",
  "properties": {
    "script": {
      "type": "string",
      "description": "Python source to execute in the sandbox."
    }
  },
  "required": ["script"]
}`

func (t *pythonTool) Spec() ToolSpec {
	return ToolSpec{
		Name:        "run_python",
		Description: runPythonDescription,
		Parameters:  json.RawMessage(runPythonParams),
	}
}

// runPythonArgs is the JSON shape of run_python's arguments as decoded from
// the model's raw JSON argument string.
type runPythonArgs struct {
	Script string `json:"script"`
}

// scriptFailure is the JSON shape returned to the model when a script runs
// to completion but exits non-zero: this is a normal tool result, not a
// crash, so the model can see the failure and react.
type scriptFailure struct {
	Error  string `json:"error"`
	Stderr string `json:"stderr"`
}

// Call decodes args, submits the script to the sandbox, and always emits a
// ScriptRunEvent describing the run -- whatever the outcome -- before
// returning. See Tool.Call for the general contract: a non-nil error here
// is surfaced by the loop as the tool result, not treated as a crash.
func (t *pythonTool) Call(ctx context.Context, args string, emit Emitter) (string, error) {
	var parsed runPythonArgs
	if err := json.Unmarshal([]byte(args), &parsed); err != nil {
		return "", fmt.Errorf("agent: run_python: invalid arguments JSON: %w", err)
	}
	if strings.TrimSpace(parsed.Script) == "" {
		return "", fmt.Errorf("agent: run_python: script argument must not be blank")
	}

	// A per-run correlation id: the sandbox pool does not surface the
	// underlying container id (containers are single-use and torn down
	// immediately after Run returns), so this id exists purely to let the
	// trace correlate the tool_call, script_run, and tool_result events
	// for one run -- it is not a container identifier.
	sandboxID := uuid.NewString()

	stdout, stderr, exitCode, runErr := t.sb.Run(ctx, []byte(parsed.Script))

	emitScriptRun(emit, parsed.Script, stdout, stderr, exitCode, sandboxID)

	if runErr != nil {
		return "", fmt.Errorf("agent: run_python: sandbox run failed: %w", runErr)
	}

	if exitCode != 0 {
		failure := scriptFailure{
			Error:  fmt.Sprintf("script exited %d", exitCode),
			Stderr: string(stderr),
		}
		out, err := json.Marshal(failure)
		if err != nil {
			return "", fmt.Errorf("agent: run_python: encode failure result: %w", err)
		}
		return string(out), nil
	}

	return string(stdout), nil
}

// emitScriptRun builds and emits one ScriptRunEvent, truncating Stdout and
// Stderr for the trace via the package's shared truncateForTrace (the same
// ~4 KB cap loop.go applies to tool_result payloads); the full stdout is
// still returned to the model by Call, independent of this event.
func emitScriptRun(emit Emitter, source string, stdout, stderr []byte, exitCode int, sandboxID string) {
	if emit == nil {
		return
	}

	traceStdout, stdoutTruncated := truncateForTrace(string(stdout))
	traceStderr, stderrTruncated := truncateForTrace(string(stderr))

	emit(Event{
		Type: EventScriptRun,
		ScriptRun: &ScriptRunEvent{
			Source:    source,
			Stdout:    traceStdout,
			Stderr:    traceStderr,
			ExitCode:  exitCode,
			SandboxID: sandboxID,
			Truncated: stdoutTruncated || stderrTruncated,
		},
	})
}
