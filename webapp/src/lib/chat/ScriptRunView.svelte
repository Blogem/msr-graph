<script lang="ts">
	// Renders a `script_run` trace event: the executed source plus
	// stdout, stderr, exit code, and sandbox id, all viewable inline
	// (chat-ui spec 3.3 "script_run: source + stdout/stderr + exit code +
	// sandbox id"; spec "Script source and output are inspectable").
	import type { ScriptRunPayload } from '$lib/types';

	let { scriptRun }: { scriptRun: ScriptRunPayload } = $props();
</script>

<div class="script-run" data-testid="script-run">
	<span class="event-label">Script run</span>
	{#if scriptRun.truncated}
		<span class="badge-truncated">truncated by server</span>
	{/if}
	<pre data-testid="script-source">{scriptRun.source}</pre>
	<div class="script-output">
		<div class="script-stream">
			<span class="output-label">stdout</span>
			<pre data-testid="script-stdout">{scriptRun.stdout}</pre>
		</div>
		<div class="script-stream">
			<span class="output-label">stderr</span>
			<pre data-testid="script-stderr">{scriptRun.stderr}</pre>
		</div>
	</div>
	<dl class="script-meta">
		<dt>Exit code</dt>
		<dd data-testid="script-exit-code">{scriptRun.exit_code}</dd>
		<dt>Sandbox</dt>
		<dd data-testid="script-sandbox-id">{scriptRun.sandbox_id}</dd>
	</dl>
</div>
