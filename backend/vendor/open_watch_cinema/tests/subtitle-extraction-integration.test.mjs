import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { access, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { prepareMediaForChrome } from '../src/media-compatibility.mjs';
import { readSubtitleBundle } from '../src/media-subtitles.mjs';

async function exists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

test('compatibility preparation preserves embedded text subtitles as WebVTT sidecars', async (context) => {
  const versionCheck = spawnSync('ffmpeg', ['-version'], { windowsHide: true });
  if (versionCheck.status !== 0) {
    context.skip('FFmpeg is unavailable in this environment.');
    return;
  }

  const root = await mkdtemp(join(tmpdir(), 'open-watch-cinema-subtitles-'));
  const inputPath = join(root, 'sample.mkv');
  const outputPath = join(root, 'sample.mp4');
  const subtitlePath = join(root, 'sample.srt');

  try {
    await writeFile(subtitlePath, [
      '1',
      '00:00:00,100 --> 00:00:00,900',
      'Hello from the subtitle track.',
      ''
    ].join('\n'), 'utf8');

    const generated = spawnSync('ffmpeg', [
      '-y',
      '-hide_banner',
      '-loglevel', 'error',
      '-f', 'lavfi',
      '-i', 'color=c=black:s=320x180:r=24:d=1',
      '-f', 'lavfi',
      '-i', 'sine=frequency=440:duration=1',
      '-f', 'srt',
      '-i', subtitlePath,
      '-map', '0:v:0',
      '-map', '1:a:0',
      '-map', '2:s:0',
      '-shortest',
      '-c:v', 'libx264',
      '-pix_fmt', 'yuv420p',
      '-c:a', 'aac',
      '-c:s', 'subrip',
      '-metadata:s:s:0', 'language=eng',
      '-metadata:s:s:0', 'title=English',
      '-disposition:s:0', 'default',
      inputPath
    ], { windowsHide: true, encoding: 'utf8' });

    assert.equal(generated.status, 0, generated.stderr || 'Could not generate subtitle fixture.');

    const result = await prepareMediaForChrome(inputPath);
    assert.equal(result.changed, true);
    assert.equal(result.subtitleStatus, 'ready');
    assert.equal(result.subtitleTracks.length, 1);
    assert.equal(result.subtitleTracks[0].language, 'eng');
    assert.equal(await exists(inputPath), false);
    assert.equal(await exists(outputPath), true);

    const tracks = await readSubtitleBundle(outputPath);
    assert.equal(tracks.length, 1);
    assert.equal(tracks[0].default, true);
    const webVtt = await readFile(tracks[0].absolutePath, 'utf8');
    assert.match(webVtt, /^WEBVTT/);
    assert.match(webVtt, /Hello from the subtitle track\./);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
