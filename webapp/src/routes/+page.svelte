<script lang="ts">
	// Chat surface (chat-ui spec) mount point. Wave 2 fills this in with
	// the conversation pane, streamChat($lib/sse) wiring, and the per-turn
	// trace timeline (design D4). Keep this page's root element's
	// data-testid stable ("chat-surface") -- it is the hook the app-shell
	// tests use to assert this route renders on `/`.
</script>

<section data-testid="chat-surface">
	<h1>Chat</h1>
	<p>TODO(wave 2, chat-ui): conversation pane + trace timeline over lib/sse.ts's streamChat.</p>
</section>
