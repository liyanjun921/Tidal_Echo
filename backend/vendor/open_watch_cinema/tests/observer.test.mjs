import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { access, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  addSessionObservations,
  endSession,
  listSessionObservations,
  openDatabase,
  openSession
} from '../src/database.mjs';
import {
  analyzeObservationSegment,
  getObserverStatus
} from '../src/observation-manager.mjs';

const PROJECT_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));

function createSceneChangeFilm(outputPath) {
  const result = spawnSync('ffmpeg', [
    '-hide_banner', '-loglevel', 'error', '-y',
    '-f', 'lavfi', '-i', 'color=c=black:s=320x180:d=2:r=24',
    '-f', 'lavfi', '-i', 'color=c=red:s=320x180:d=2:r=24',
    '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', outputPath
  ], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
}

test('OpenCV observer emits timed motion metrics, storyboards, and room archives lock observation writes', async () => {
  const root = await mkdtemp(join(tmpdir(), 'open-watch-cinema-observer-'));
  const videoPath = join(root, 'scene-change.mp4');
  const databasePath = join(root, 'cinema.sqlite');
  const outputDir = join(root, 'storyboards');
  createSceneChangeFilm(videoPath);

  const status = await getObserverStatus(PROJECT_ROOT);
  assert.equal(status.available, true);
  assert.equal(status.baselineAvailable, true);
  assert.equal(status.opencvAvailable, true);

  const analysis = await analyzeObservationSegment(PROJECT_ROOT, {
    inputPath: videoPath,
    startMs: 0,
    durationMs: 4_000,
    sampleFps: 2,
    outputDir,
    storyboardPrefix: 'test'
  });
  assert.equal(analysis.engine, 'opencv-observer-v1');
  assert.ok(analysis.decodedFrameCount >= 6);
  assert.ok(analysis.observations.length >= 2);
  assert.ok(Math.max(...analysis.observations.map((item) => item.sceneScore)) > 0.5);
  assert.ok(analysis.observations.some((item) => item.metrics.histogramDistance > 0));
  assert.ok(analysis.observations.every((item) => typeof item.metrics.perceptualHash === 'string'));
  assert.ok(analysis.frames.length >= 1);
  await access(join(outputDir, analysis.frames[0].filename));

  const db = openDatabase(databasePath);
  try {
    const room = openSession(db, { mediaId: 'b'.repeat(24), mediaTitle: 'Observer Film' });
    const inserted = addSessionObservations(db, room.id, analysis);
    assert.equal(inserted.length, analysis.observations.length);
    assert.deepEqual(listSessionObservations(db, room.id), inserted);

    endSession(db, room.id, { lastPositionMs: 4_000 });
    assert.throws(
      () => addSessionObservations(db, room.id, analysis),
      /read-only/i
    );
  } finally {
    db.close();
    await rm(root, { recursive: true, force: true });
  }
});
