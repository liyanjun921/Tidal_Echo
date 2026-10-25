import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { createObservationPrecomputeManifest } from '../src/observation-precompute-plan.mjs';
import { runObservationPrecompute } from '../src/observation-precompute-runner.mjs';

const PROJECT_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const DIALOGUE_FIXTURE = {
  status: 'source_detected',
  sourceMode: 'test_fixture',
  track: {
    id: 'fixture-eng',
    language: 'eng',
    title: 'English',
    label: 'English',
    default: true,
    format: 'webvtt'
  },
  cues: [
    { cueId: 'cue-a', fromMs: 1000, toMs: 3000, text: 'Opening line.' },
    { cueId: 'cue-b', fromMs: 299000, toMs: 301000, text: 'Boundary line.' }
  ],
  note: 'Synthetic dialogue fixture.'
};

async function createFakeAnalyzer(callLog, { failOnce = false } = {}) {
  let failed = false;
  return async (_projectRoot, options) => {
    callLog.push({ ...options });
    if (failOnce && !failed) {
      failed = true;
      throw new Error('synthetic worker interruption');
    }

    await mkdir(options.outputDir, { recursive: true });
    const times = [
      options.startMs,
      options.startMs + 2_000,
      options.startMs + options.durationMs - 1_000
    ];
    const frames = [];
    for (const [index, mediaTimeMs] of times.entries()) {
      const filename = `${options.storyboardPrefix}-${index}.jpg`;
      await writeFile(join(options.outputDir, filename), `frame-${mediaTimeMs}`);
      frames.push({ filename, mediaTimeMs, frameReason: 'motion_peak' });
    }

    return {
      ok: true,
      protocolVersion: 2,
      engine: 'fake-observer-v1',
      sampleFps: options.sampleFps,
      decodedFrameCount: 3,
      observations: times.map((fromMs, index) => ({
        fromMs,
        toMs: fromMs + 1_000,
        kind: index === 0 ? 'segment_start' : 'motion_peak',
        sceneScore: 0,
        motionScore: 0.5,
        metrics: { perceptualHash: String(index) },
        storyboard: frames[index]
      })),
      frames
    };
  };
}

test('runner checkpoints one chunk, trims overlap, and resumes the same package to ready', async () => {
  const root = await mkdtemp(join(tmpdir(), 'owc-precompute-runner-'));
  const inputPath = join(root, 'film.mp4');
  const outputRoot = join(root, 'observations');
  await writeFile(inputPath, 'placeholder-compatible-film');
  const calls = [];
  const analyzeSegment = await createFakeAnalyzer(calls);

  try {
    const first = await runObservationPrecompute(PROJECT_ROOT, {
      inputPath,
      outputRoot,
      durationMs: 700_000,
      mediaIdentity: 'sha256:test-resume-film',
      dialogueSource: DIALOGUE_FIXTURE,
      maxChunks: 1,
      analyzeSegment
    });

    assert.equal(first.chunksRun, 1);
    assert.equal(first.ready, false);
    assert.equal(first.manifest.analysisActivation, 'manual_opt_in');
    assert.equal(first.manifest.progress.completeChunks, 1);
    assert.equal(first.manifest.chunks[0].attempts, 1);

    const second = await runObservationPrecompute(PROJECT_ROOT, {
      inputPath,
      outputRoot,
      durationMs: 700_000,
      mediaIdentity: 'sha256:test-resume-film',
      dialogueSource: DIALOGUE_FIXTURE,
      analyzeSegment
    });

    assert.equal(second.ready, true);
    assert.equal(second.manifest.status, 'ready');
    assert.equal(second.manifest.visualTrack.status, 'ready');
    assert.equal(second.manifest.aiReadiness.ready, true);
    assert.deepEqual(second.manifest.aiReadiness.blockers, []);
    assert.equal(second.manifest.dialogueTrack.status, 'ready');
    assert.equal(second.manifest.progress.percent, 100);
    assert.equal(calls.length, second.manifest.chunks.length);

    const boundaryChunk = second.manifest.chunks[1];
    assert.match(boundaryChunk.visualRef, /^chunks\/chunk-0001\/visual\.json$/);
    assert.match(boundaryChunk.dialogueRef, /^chunks\/chunk-0001\/dialogue\.json$/);
    assert.match(boundaryChunk.storyboardRootRef, /^chunks\/chunk-0001\/storyboards$/);
    const result = JSON.parse(await readFile(join(second.packageDir, boundaryChunk.visualRef), 'utf8'));
    const dialogue = JSON.parse(await readFile(join(second.packageDir, boundaryChunk.dialogueRef), 'utf8'));
    assert.ok(result.observations.length >= 1);
    assert.ok(result.observations.every((item) => (
      item.fromMs >= boundaryChunk.acceptFromMs
      && item.fromMs < boundaryChunk.acceptToMs
    )));
    assert.ok(result.frames.every((item) => item.mediaTimeMs >= boundaryChunk.acceptFromMs));
    assert.ok(!result.observations.some((item) => item.fromMs === boundaryChunk.analysisStartMs));
    assert.equal(dialogue.status, 'ready');
    assert.ok(dialogue.cues.some((cue) => cue.cueId === 'cue-b'));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('runner records a failed checkpoint and retries it without creating another package', async () => {
  const root = await mkdtemp(join(tmpdir(), 'owc-precompute-failure-'));
  const inputPath = join(root, 'film.mp4');
  const outputRoot = join(root, 'observations');
  await writeFile(inputPath, 'placeholder-compatible-film');
  const calls = [];
  const analyzeSegment = await createFakeAnalyzer(calls, { failOnce: true });
  const expected = createObservationPrecomputeManifest({
    mediaIdentity: 'sha256:test-failure-film',
    durationMs: 90_000
  });
  const manifestPath = join(outputRoot, expected.planId, 'manifest.json');

  try {
    await assert.rejects(
      runObservationPrecompute(PROJECT_ROOT, {
        inputPath,
        outputRoot,
        durationMs: 90_000,
        mediaIdentity: 'sha256:test-failure-film',
        dialogueSource: DIALOGUE_FIXTURE,
        analyzeSegment
      }),
      /synthetic worker interruption/
    );

    const failed = JSON.parse(await readFile(manifestPath, 'utf8'));
    assert.equal(failed.status, 'failed');
    assert.equal(failed.chunks[0].status, 'failed');
    assert.equal(failed.chunks[0].attempts, 1);

    const resumed = await runObservationPrecompute(PROJECT_ROOT, {
      inputPath,
      outputRoot,
      durationMs: 90_000,
      mediaIdentity: 'sha256:test-failure-film',
      dialogueSource: DIALOGUE_FIXTURE,
      analyzeSegment
    });
    assert.equal(resumed.ready, true);
    assert.equal(resumed.manifest.chunks[0].attempts, 2);
    assert.equal(calls.length, 2);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('runner holds an exclusive package lock while a chunk is being analyzed', async () => {
  const root = await mkdtemp(join(tmpdir(), 'owc-precompute-lock-'));
  const inputPath = join(root, 'film.mp4');
  const outputRoot = join(root, 'observations');
  await writeFile(inputPath, 'placeholder-compatible-film');

  let signalEntered;
  let releaseWorker;
  const entered = new Promise((resolvePromise) => { signalEntered = resolvePromise; });
  const workerGate = new Promise((resolvePromise) => { releaseWorker = resolvePromise; });
  const analyzeSegment = async (_projectRoot, options) => {
    signalEntered();
    await workerGate;
    return {
      ok: true,
      protocolVersion: 2,
      engine: 'fake-observer-v1',
      sampleFps: options.sampleFps,
      decodedFrameCount: 1,
      observations: [{
        fromMs: options.startMs,
        toMs: options.startMs + 500,
        kind: 'segment_start',
        sceneScore: 0,
        motionScore: 0,
        metrics: {}
      }],
      frames: []
    };
  };

  try {
    const firstRun = runObservationPrecompute(PROJECT_ROOT, {
      inputPath,
      outputRoot,
      durationMs: 90_000,
      mediaIdentity: 'sha256:test-lock-film',
      dialogueSource: DIALOGUE_FIXTURE,
      analyzeSegment
    });
    await entered;

    await assert.rejects(
      runObservationPrecompute(PROJECT_ROOT, {
        inputPath,
        outputRoot,
        durationMs: 90_000,
        mediaIdentity: 'sha256:test-lock-film',
        dialogueSource: DIALOGUE_FIXTURE,
        analyzeSegment
      }),
      /already being prepared/
    );

    releaseWorker();
    const completed = await firstRun;
    assert.equal(completed.ready, true);
    assert.equal(completed.manifest.chunks[0].attempts, 1);
  } finally {
    releaseWorker?.();
    await rm(root, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 50
    });
  }
});
