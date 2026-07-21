<script lang="ts">
	// Admin surface (admin-ui spec) route: thin wrapper mounting
	// $lib/admin/AdminSurface.svelte, which owns the checkpoint
	// list/create/restore flows over lib/api.ts. Keep the data-testid
	// stable -- it is the mount point tests target.
	import AdminSurface from '$lib/admin/AdminSurface.svelte';
</script>

<section data-testid="admin-surface">
	<h1>Admin</h1>
	<AdminSurface />
</section>
