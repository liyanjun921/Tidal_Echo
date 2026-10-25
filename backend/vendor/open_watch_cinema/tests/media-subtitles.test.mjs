import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createDialogueTrackState,
  describeDialogueSource
} from '../src/media-subtitles.mjs';

test('embedded subtitle streams become an extractable but not-yet-built dialogue source', () => {
  const assessment = describeDialogueSource([{
    index: 2,
    codecName: 'mov_text',
    codecLongName: 'MOV text',
    tags: { language: 'eng' },
    disposition: { default: true, forced: false, hearingImpaired: false }
  }]);
  const track = createDialogueTrackState(assessment);

  assert.equal(assessment.mode, 'embedded_subtitle_stream');
  assert.equal(track.status, 'source_detected');
  assert.equal(track.extractable, true);
  assert.equal(track.subtitleStreams.length, 1);
  assert.equal(track.resultRef, null);
});

test('videos without a subtitle stream explicitly report a missing dialogue source', () => {
  const assessment = describeDialogueSource([]);
  const track = createDialogueTrackState(assessment);

  assert.equal(assessment.mode, 'no_embedded_subtitle_stream');
  assert.equal(track.status, 'source_missing');
  assert.equal(track.extractable, false);
  assert.deepEqual(track.subtitleStreams, []);
});

test('synthetic callers may leave dialogue source unassessed without pretending it is ready', () => {
  const track = createDialogueTrackState(null);
  assert.equal(track.status, 'unassessed');
  assert.equal(track.resultRef, null);
});
