import { spawn } from 'node:child_process';
import { access, mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { basename, dirname, join, parse, resolve } from 'node:path';

const TEXT_SUBTITLE_CODECS = new Set([
  'ass',
  'mov_text',
  'ssa',
  'subrip',
  'text',
  'webvtt'
]);

function runAndCapture(command, args, { maxChars = 8 * 1024 * 1024 } = {}) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, {
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe']
    });
    let stdout = '';
    let stderr = '';

    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      if (stdout.length < maxChars) stdout += chunk;
    });
    child.stderr.on('data', (chunk) => {
      if (stderr.length < maxChars) stderr += chunk;
    });
    child.once('error', rejectPromise);
    child.once('close', (code) => {
      if (code === 0) resolvePromise({ stdout, stderr });
      else rejectPromise(new Error(`${command} exited with code ${code}: ${stderr.trim() || 'unknown error'}`));
    });
  });
}

async function pathExists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

function normalizeTags(tags = {}) {
  return Object.fromEntries(
    Object.entries(tags).map(([key, value]) => [key, String(value)])
  );
}

function cleanToken(value, fallback) {
  const cleaned = String(value || '')
    .normalize('NFKC')
    .replace(/[^\p{Letter}\p{Number}._-]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  return cleaned || fallback;
}

function subtitleLabel(stream, ordinal) {
  return stream.tags.title
    || stream.tags.language
    || `Subtitle ${ordinal + 1}`;
}

export function subtitleBundleDirectory(mediaPath) {
  const parsed = parse(mediaPath);
  return join(parsed.dir, `${parsed.name}.owc-subtitles`);
}

export function isTextSubtitleStream(stream) {
  return TEXT_SUBTITLE_CODECS.has(String(stream?.codecName || '').toLowerCase());
}

export async function probeSubtitleStreams(filePath) {
  const { stdout } = await runAndCapture('ffprobe', [
    '-v', 'error',
    '-select_streams', 's',
    '-show_entries', 'stream=index,codec_name,codec_long_name:stream_tags=language,title,handler_name:stream_disposition=default,forced,hearing_impaired',
    '-of', 'json',
    filePath
  ]);

  const payload = JSON.parse(stdout || '{}');
  const streams = Array.isArray(payload.streams) ? payload.streams : [];
  return streams.map((stream) => ({
    index: Number(stream.index),
    codecName: stream.codec_name || '',
    codecLongName: stream.codec_long_name || '',
    tags: normalizeTags(stream.tags),
    disposition: {
      default: Boolean(stream.disposition?.default),
      forced: Boolean(stream.disposition?.forced),
      hearingImpaired: Boolean(stream.disposition?.hearing_impaired)
    }
  }));
}

export function describeDialogueSource(subtitleStreams = []) {
  const textStreams = subtitleStreams.filter(isTextSubtitleStream);
  if (textStreams.length > 0) {
    return {
      mode: 'embedded_subtitle_stream',
      extractable: true,
      subtitleStreams,
      textStreams,
      note: 'Timed subtitle text can be extracted without reading it from storyboard pixels.'
    };
  }

  if (subtitleStreams.length > 0) {
    return {
      mode: 'image_subtitle_stream_only',
      extractable: false,
      subtitleStreams,
      textStreams: [],
      note: 'Subtitle streams exist, but they are image-based and cannot become timed text without recognition.'
    };
  }

  return {
    mode: 'no_embedded_subtitle_stream',
    extractable: false,
    subtitleStreams: [],
    textStreams: [],
    note: 'No separate subtitle stream is present. Visible subtitles, if any, are likely burned into the video image and need another dialogue source such as sidecar subtitles, audio transcription, or subtitle-region OCR.'
  };
}

export function createDialogueTrackState(assessment) {
  if (!assessment) {
    return {
      status: 'unassessed',
      sourceMode: 'unknown',
      extractable: false,
      subtitleStreams: [],
      resultRef: null,
      note: 'Dialogue source has not been inspected yet.'
    };
  }

  return {
    status: assessment.extractable ? 'source_detected' : 'source_missing',
    sourceMode: assessment.mode,
    extractable: assessment.extractable,
    subtitleStreams: assessment.subtitleStreams,
    resultRef: null,
    note: assessment.note
  };
}

export async function assessDialogueSource(filePath) {
  return describeDialogueSource(await probeSubtitleStreams(filePath));
}

async function replaceBundleDirectory(tempDirectory, targetDirectory) {
  const stamp = `${Date.now()}-${process.pid}`;
  const backupDirectory = `${targetDirectory}.owc-backup-${stamp}`;
  const hadTarget = await pathExists(targetDirectory);

  if (hadTarget) await rename(targetDirectory, backupDirectory);
  try {
    await rename(tempDirectory, targetDirectory);
    if (hadTarget) await rm(backupDirectory, { recursive: true, force: true });
  } catch (error) {
    await rm(targetDirectory, { recursive: true, force: true });
    if (hadTarget && await pathExists(backupDirectory)) {
      await rename(backupDirectory, targetDirectory);
    }
    throw error;
  }
}

export async function extractSubtitleStreams(inputPath, { outputMediaPath = inputPath } = {}) {
  const subtitleStreams = await probeSubtitleStreams(inputPath);
  const textStreams = subtitleStreams.filter(isTextSubtitleStream);
  if (textStreams.length === 0) {
    return {
      status: subtitleStreams.length > 0 ? 'unsupported_image_subtitles' : 'no_subtitles',
      subtitleStreams,
      tracks: [],
      bundleDirectory: null
    };
  }

  const targetDirectory = subtitleBundleDirectory(outputMediaPath);
  const tempDirectory = `${targetDirectory}.owc-processing-${Date.now()}-${process.pid}`;
  await rm(tempDirectory, { recursive: true, force: true });
  await mkdir(tempDirectory, { recursive: true });

  const tracks = [];
  try {
    for (const [ordinal, stream] of textStreams.entries()) {
      const language = cleanToken(stream.tags.language, 'und');
      const title = cleanToken(stream.tags.title, `track-${ordinal + 1}`);
      const fileName = `${String(ordinal + 1).padStart(2, '0')}-${language}-${title}.vtt`;
      const tempOutputPath = join(tempDirectory, fileName);

      await runAndCapture('ffmpeg', [
        '-y',
        '-hide_banner',
        '-loglevel', 'error',
        '-i', inputPath,
        '-map', `0:${stream.index}`,
        '-c:s', 'webvtt',
        tempOutputPath
      ]);

      tracks.push({
        id: `stream-${stream.index}`,
        streamIndex: stream.index,
        sourceCodec: stream.codecName,
        language: stream.tags.language || 'und',
        title: stream.tags.title || null,
        label: subtitleLabel(stream, ordinal),
        default: stream.disposition.default,
        forced: stream.disposition.forced,
        hearingImpaired: stream.disposition.hearingImpaired,
        format: 'webvtt',
        fileName
      });
    }

    const manifest = {
      version: 1,
      kind: 'open-watch-cinema-subtitle-bundle',
      sourceFileName: basename(inputPath),
      targetMediaFileName: basename(outputMediaPath),
      createdAt: new Date().toISOString(),
      tracks
    };
    await writeFile(
      join(tempDirectory, 'manifest.json'),
      `${JSON.stringify(manifest, null, 2)}\n`,
      'utf8'
    );
    await replaceBundleDirectory(tempDirectory, targetDirectory);

    return {
      status: 'ready',
      subtitleStreams,
      tracks: tracks.map((track) => ({
        ...track,
        absolutePath: resolve(targetDirectory, track.fileName)
      })),
      bundleDirectory: targetDirectory
    };
  } catch (error) {
    await rm(tempDirectory, { recursive: true, force: true });
    throw error;
  }
}

export async function readSubtitleBundle(mediaPath) {
  const bundleDirectory = subtitleBundleDirectory(mediaPath);
  let manifest;
  try {
    manifest = JSON.parse(await readFile(join(bundleDirectory, 'manifest.json'), 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }

  if (manifest?.kind !== 'open-watch-cinema-subtitle-bundle' || !Array.isArray(manifest.tracks)) {
    return [];
  }

  const tracks = [];
  for (const track of manifest.tracks) {
    const fileName = String(track.fileName || '');
    if (!fileName || basename(fileName) !== fileName || !fileName.toLowerCase().endsWith('.vtt')) continue;
    const absolutePath = resolve(bundleDirectory, fileName);
    if (dirname(absolutePath) !== resolve(bundleDirectory) || !await pathExists(absolutePath)) continue;
    tracks.push({
      id: String(track.id || ''),
      streamIndex: Number(track.streamIndex),
      sourceCodec: String(track.sourceCodec || ''),
      language: String(track.language || 'und'),
      title: track.title ? String(track.title) : null,
      label: String(track.label || track.title || track.language || 'Subtitle'),
      default: Boolean(track.default),
      forced: Boolean(track.forced),
      hearingImpaired: Boolean(track.hearingImpaired),
      format: 'webvtt',
      fileName,
      absolutePath
    });
  }
  return tracks;
}
