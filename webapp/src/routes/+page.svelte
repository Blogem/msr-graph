<script lang="ts">
	// Chat surface (chat-ui spec) mount point. The route stays a thin
	// wrapper: all conversation/trace logic lives in
	// `$lib/chat/ChatSurface.svelte` so it is independently testable.
	// Keep this page's root element's data-testid stable ("chat-surface")
	// -- it is the hook the app-shell tests use to assert this route
	// renders on `/`.
	import ChatSurface from '$lib/chat/ChatSurface.svelte';
</script>

<section data-testid="chat-surface">
	<h1>Chat</h1>
	<ChatSurface />
</section>
