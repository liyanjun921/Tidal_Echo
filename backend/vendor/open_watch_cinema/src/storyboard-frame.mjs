import { readFile, realpath, stat } from 'node:fs/promises';
import { extname, resolve, sep } from 'node:path';

import { readObservationTrackWindow } from './observation-track-reader.mjs';

const MIME_TYPES = new Map([
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.png', 'image/png'],
  ['.webp', 'image/webp']
]);
const MAX_FRAME_BYTES = 8 * 1024 * 1024;

function requireNonNegativeInteger(value, label) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new TypeError(`${label} must be a non-negative safe integer.`);
  }
  return value;
}

export function normalizeStoryboardRef(value) {
  if (typeof value !== 'string') throw new TypeError('storyboardRef must be a string.');
  const ref = value.trim();
  if (!ref || ref.includes('\0') || ref.includes('\\')) {
    throw new Error('storyboardRef must be one normalized package-relative reference.');
  }
  if (!/^chunks\/chunk-\d{4}\/storyboards\/[A-Za-z0-9][A-Za-z0-9._-]*\.(?:jpe?g|png|webp)$/i.test(ref)) {
    throw new Error('storyboardRef is outside the allowlisted storyboard namespace.');
  }
  if (ref.split('/').some((segment) => segment === '.' || segment === '..')) {
    throw new Error('storyboardRef contains a traversal segment.');
  }
  return ref;
}

export async function readSpoilerGatedStoryboardFrame(packageDir, {
  storyboardRef,
  mediaTimeMs,
  playheadMs
}) {
  mediaTimeMs = requireNonNegativeInteger(mediaTimeMs, 'mediaTimeMs');
  playheadMs = requireNonNegativeInteger(playheadMs, 'playheadMs');
  if (mediaTimeMs > playheadMs) {
    throw new Error('This storyboard has not reached the current playhead yet.');
  }

  const ref = normalizeStoryboardRef(storyboardRef);
  const packageRoot = await realpath(resolve(packageDir));
  const fromMs = Math.max(0, mediaTimeMs - 2_000);
  const toMs = Math.min(playheadMs + 1, mediaTimeMs + 2_001);
  const window = await readObservationTrackWindow(packageRoot, {
    fromMs,
    toMs,
    playheadMs,
    lookaheadMs: 0,
    maxItems: 100,
    maxDialogueItems: 1
  });
  const observation = window.observations.find((candidate) => (
    candidate?.storyboard?.storyboardRef === ref
    && candidate.storyboard.mediaTimeMs === mediaTimeMs
  ));
  if (!observation) {
    throw new Error('The requested storyboard is not revealed for this room playhead.');
  }

  const candidatePath = resolve(packageRoot, ref);
  const framePath = await realpath(candidatePath);
  if (!framePath.startsWith(`${packageRoot}${sep}`)) {
    throw new Error('The storyboard resolved outside its AI package.');
  }
  const frameStat = await stat(framePath);
  if (!frameStat.isFile()) throw new Error('The storyboard reference is not a file.');
  if (frameStat.size > MAX_FRAME_BYTES) {
    throw new Error('The storyboard exceeds the image bridge size limit.');
  }

  const mimeType = MIME_TYPES.get(extname(framePath).toLowerCase());
  if (!mimeType) throw new Error('The storyboard image type is not supported.');
  const content = await readFile(framePath);
  return {
    content,
    mimeType,
    metadata: {
      storyboardRef: ref,
      mediaTimeMs,
      playheadMs,
      revealThroughMs: window.revealThroughMs,
      fromMs: observation.fromMs,
      toMs: observation.toMs,
      kind: observation.kind,
      frameReason: observation.storyboard.frameReason || observation.kind,
      bytes: content.byteLength
    }
  };
}
