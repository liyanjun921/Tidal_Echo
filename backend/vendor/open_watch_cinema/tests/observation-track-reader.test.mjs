import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import {
  createObservationPrecomputeManifest,
  markObservationChunkComplete
} from '../src/observation-precompute-plan.mjs';
import { readObservationTrackWindow } from '../src/observation-track-reader.mjs';

async function createPackage() {
  const packageDir = await mkdtemp(join(tmpdir(), 'owc-track-reader-'));
  const chunkDir = join(packageDir, 'chunks', 'chunk-0000');
  await mkdir(join(chunkDir, 'storyboards'), { recursive: true });
  let manifest = createObservationPrecomputeManifest({
    mediaIdentity: 'sha256:reader-fixture',
    durationMs: 30_000
  });
  manifest = markObservationChunkComplete(manifest, 0, {
    observationCount: 4,
    storyboardCount: 1,
    resultRef: 'chunks/chunk-0000/visual.json'
  });
  manifest.chunks[0] = {
    ...manifest.chunks[0],
    visualRef: 'chunks/chunk-0000/visual.json',
    dialogueRef: 'chunks/chunk-0000/dialogue.json',
    storyboardRootRef: 'chunks/chunk-0000/storyboards',
    dialogueCueCount: 3
  };
  manifest = {
    ...manifest,
    visualTrack: { status: 'ready', protocolVersion: 2 },
    dialogueTrack: { status: 'ready', cueCount: 3 },
    aiReadiness: {
      status: 'ready',
      ready: true,
      experienceMode: 'complete',
      blockers: []
    }
  };
  const observations = [1_000, 5_000, 15_000, 25_000].map((fromMs, index) => ({
    fromMs,
    toMs: fromMs + 500,
    kind: index === 1 ? 'scene_change' : 'heartbeat',
    sceneScore: index / 10,
    motionScore: index / 20,
    metrics: { motionDirection: 'right' },
    ...(index === 1 ? {
      storyboard: {
        filename: 'sample.jpg',
        mediaTimeMs: fromMs,
        frameReason: 'scene_change'
      }
    } : {})
  }));
  const dialogue = [
    { cueId: 'one', fromMs: 900, toMs: 1_800, text: 'First line.' },
    { cueId: 'two', fromMs: 5_500, toMs: 7_500, text: 'Near the spoiler gate.' },
    { cueId: 'three', fromMs: 15_200, toMs: 16_000, text: 'After the seek.' }
  ];
  await writeFile(
    join(chunkDir, 'visual.json'),
    `${JSON.stringify({ observations })}\n`
  );
  await writeFile(
    join(chunkDir, 'dialogue.json'),
    `${JSON.stringify({ status: 'ready', cues: dialogue })}\n`
  );
  await writeFile(join(packageDir, 'manifest.json'), `${JSON.stringify(manifest)}\n`);
  return packageDir;
}

test('track reader enforces the playhead spoiler gate for visual and dialogue tracks', async () => {
  const packageDir = await createPackage();
  try {
    const result = await readObservationTrackWindow(packageDir, {
      fromMs: 0,
      toMs: 20_000,
      playheadMs: 6_000,
      lookaheadMs: 1_000
    });

    assert.equal(result.revealThroughMs, 7_000);
    assert.deepEqual(result.observations.map((item) => item.fromMs), [1_000, 5_000]);
    assert.deepEqual(result.dialogue.map((item) => item.cueId), ['one', 'two']);
    assert.ok(result.observations.every((item) => item.fromMs < result.revealThroughMs));
    assert.ok(result.dialogue.every((item) => item.fromMs < result.revealThroughMs));
    assert.equal(result.aiReadiness.ready, true);
  } finally {
    await rm(packageDir, { recursive: true, force: true });
  }
});

test('seek reads from the new cursor without replaying earlier visual or dialogue items', async () => {
  const packageDir = await createPackage();
  try {
    const result = await readObservationTrackWindow(packageDir, {
      fromMs: 14_000,
      toMs: 30_000,
      playheadMs: 20_000,
      lookaheadMs: 0
    });

    assert.deepEqual(result.observations.map((item) => item.fromMs), [15_000]);
    assert.deepEqual(result.dialogue.map((item) => item.cueId), ['three']);
    assert.ok(!result.observations.some((item) => item.fromMs < 14_000));
    assert.ok(!result.dialogue.some((item) => item.fromMs < 14_000));
    assert.equal(result.nextCursorMs, 16_000);
  } finally {
    await rm(packageDir, { recursive: true, force: true });
  }
});

test('storyboards are exposed only as chunk-relative package references', async () => {
  const packageDir = await createPackage();
  try {
    const result = await readObservationTrackWindow(packageDir, {
      fromMs: 4_000,
      toMs: 6_000,
      playheadMs: 6_000,
      lookaheadMs: 0
    });
    const storyboard = result.observations[0].storyboard;
    assert.equal(storyboard.storyboardRef, 'chunks/chunk-0000/storyboards/sample.jpg');
    assert.equal('filename' in storyboard, false);
  } finally {
    await rm(packageDir, { recursive: true, force: true });
  }
});
