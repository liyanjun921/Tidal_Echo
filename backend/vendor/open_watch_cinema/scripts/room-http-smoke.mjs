import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(SCRIPT_DIR, '..');
const PORT = 4191;
const BASE_URL = `http://127.0.0.1:${PORT}`;

function run(command, args, options = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, {
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      ...options
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.once('error', reject);
    child.once('exit', (code) => {
      if (code === 0) resolvePromise({ stdout, stderr });
      else reject(new Error(`${command} exited ${code}: ${stderr || stdout}`));
    });
  });
}

async function waitForServer(child) {
  let lastError;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`Test server exited early with code ${child.exitCode}.`);
    try {
      const response = await fetch(`${BASE_URL}/api/health`, { cache: 'no-store' });
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100));
  }
  throw lastError || new Error('Timed out waiting for test server.');
}

async function request(path, options = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    cache: 'no-store',
    ...options,
    headers: {
      ...(options.body ? { 'content-type': 'application/json' } : {}),
      ...(options.headers || {})
    }
  });
  const payload = await response.json().catch(() => ({}));
  return { response, payload };
}

const localDataRoot = await mkdtemp(join(tmpdir(), 'open-watch-cinema-http-'));
const mediaRoot = join(localDataRoot, 'media');
await mkdir(mediaRoot, { recursive: true });

let server;
let serverOutput = '';
try {
  await run('ffmpeg', [
    '-hide_banner', '-loglevel', 'error', '-y',
    '-f', 'lavfi', '-i', 'color=c=black:s=320x180:d=1',
    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-shortest',
    join(mediaRoot, 'room-smoke.mp4')
  ]);

  server = spawn(process.execPath, ['server.mjs'], {
    cwd: PROJECT_ROOT,
    env: {
      ...process.env,
      PORT: String(PORT),
      OPEN_BROWSER: '0',
      LOCAL_DATA_ROOT: localDataRoot
    },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  server.stdout.on('data', (chunk) => { serverOutput += chunk; });
  server.stderr.on('data', (chunk) => { serverOutput += chunk; });
  await waitForServer(server);

  let result = await request('/api/media');
  assert.equal(result.response.status, 200);
  assert.equal(result.payload.items.length, 1);
  let media = result.payload.items[0];

  result = await request(`/api/media/${media.id}/prepare`, { method: 'POST' });
  assert.equal(result.response.status, 202);
  const jobId = result.payload.job.id;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    result = await request(`/api/jobs/${jobId}`);
    if (result.payload.job?.status === 'done') break;
    if (result.payload.job?.status === 'error') throw new Error(result.payload.job.error);
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100));
  }
  assert.equal(result.payload.job.status, 'done');

  result = await request('/api/media');
  media = result.payload.items[0];
  assert.equal(media.compatibilityStatus, 'prepared');
  assert.equal(result.payload.items[0].compatibilityNote.includes('Safest fallback'), true);

  result = await request('/api/rooms/open', {
    method: 'POST',
    body: JSON.stringify({ mediaId: media.id })
  });
  assert.equal(result.response.status, 201);
  const room = result.payload.room;
  assert.equal(room.status, 'active');
  assert.equal(room.aiAvailable, true);

  result = await request('/api/observer/status');
  assert.equal(result.response.status, 200);
  assert.equal(result.payload.observer.baselineAvailable, true);

  result = await request(`/api/rooms/${room.id}/observations/analyze`, {
    method: 'POST',
    body: JSON.stringify({ startMs: 0, durationMs: 1_000, sampleFps: 2 })
  });
  assert.equal(result.response.status, 201);
  assert.ok(
    ['ffmpeg-baseline-v1', 'opencv-observer-v1'].includes(result.payload.analysis.engine),
    `Unexpected observer engine: ${result.payload.analysis.engine}`
  );
  assert.ok(result.payload.observations.length >= 1);

  result = await request(`/api/rooms/${room.id}/observations`);
  assert.equal(result.response.status, 200);
  assert.ok(result.payload.observations.length >= 1);

  result = await request(`/api/rooms/${room.id}/messages`, {
    method: 'POST',
    body: JSON.stringify({
      senderName: 'Smoke Viewer',
      content: 'Bound to the film timeline.',
      mediaTimeMs: 420
    })
  });
  assert.equal(result.response.status, 201);
  assert.equal(result.payload.message.mediaTimeMs, 420);

  result = await request(`/api/rooms/${room.id}/messages`);
  assert.equal(result.response.status, 200);
  assert.equal(result.payload.messages.length, 1);

  result = await request(`/api/rooms/${room.id}/end`, {
    method: 'POST',
    body: JSON.stringify({ mediaTimeMs: 900 })
  });
  assert.equal(result.response.status, 200);
  assert.equal(result.payload.room.status, 'ended');

  result = await request(`/api/rooms/${room.id}/messages`, {
    method: 'POST',
    body: JSON.stringify({
      senderName: 'Smoke Viewer',
      content: 'Archived rooms must reject this.',
      mediaTimeMs: 950
    })
  });
  assert.equal(result.response.status, 409);

  result = await request(`/api/rooms/${room.id}/observations/analyze`, {
    method: 'POST',
    body: JSON.stringify({ startMs: 0, durationMs: 1_000 })
  });
  assert.equal(result.response.status, 409);

  result = await request('/api/rooms');
  assert.equal(result.response.status, 200);
  assert.equal(result.payload.activeRoom, null);
  assert.equal(result.payload.rooms[0].messageCount, 1);

  console.log('room-http-smoke: PASS');
} finally {
  if (server && server.exitCode === null) {
    server.kill('SIGTERM');
    await new Promise((resolvePromise) => {
      const timer = setTimeout(resolvePromise, 1500);
      server.once('exit', () => {
        clearTimeout(timer);
        resolvePromise();
      });
    });
  }
  await rm(localDataRoot, { recursive: true, force: true });
  if (server?.exitCode && server.exitCode !== 0) {
    console.error(serverOutput);
  }
}
