// Shared checkpoint fixtures for the admin-ui test suite (8.5), typed
// against `CheckpointManifest`/`CheckpointListResponse` (src/lib/types.ts),
// which pin the concrete `{label, ontology_version}` shape the merged
// chunk-9 checkpoint API emits (design D7).
import type { CheckpointListResponse, CheckpointManifest } from '../types';

export const preDemoCheckpoint: CheckpointManifest = {
	label: 'pre-demo',
	ontology_version: 'v1.0.0'
};

export const postReviewCheckpoint: CheckpointManifest = {
	label: 'post-review',
	ontology_version: 'v1.1.0'
};

export const checkpointList: CheckpointListResponse = {
	checkpoints: [preDemoCheckpoint, postReviewCheckpoint]
};
