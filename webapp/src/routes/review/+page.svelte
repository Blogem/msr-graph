<script lang="ts">
	// Thin route wrapper (review-ui spec): all behavior lives in
	// $lib/review/ReviewSurface.svelte, which owns the
	// data-testid="review-surface" root.
	import ReviewSurface from '$lib/review/ReviewSurface.svelte';
</script>

<ReviewSurface />
