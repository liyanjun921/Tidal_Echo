import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import {
  addSessionMessage,
  addSessionObservations,
  deleteMediaCascadeRecords,
  endSession,
  getMediaCascadeSummary,
  listIndexedMedia,
  listSessions,
  openDatabase,
  openSession,
  syncMediaIndex
} from '../src/database.mjs';

test('default media deletion cascades rooms, messages and observations', async () => {
  const root = await mkdtemp(join(tmpdir(), 'owc-delete-policy-'));
  const db = openDatabase(join(root, 'cinema.sqlite'));
  const mediaId = 'd'.repeat(24);

  try {
    syncMediaIndex(db, [{
      id: mediaId,
      title: 'Fixture Film',
      relativePath: 'Fixture Film.mp4',
      extension: '.mp4',
      size: 100,
      modifiedAt: '2026-08-05T00:00:00.000Z'
    }]);
    const room = openSession(db, { mediaId, mediaTitle: 'Fixture Film' });
    addSessionMessage(db, room.id, {
      senderName: 'Viewer',
      content: 'A retained thought.',
      mediaTimeMs: 1_000
    });
    addSessionObservations(db, room.id, {
      engine: 'fixture',
      observations: [{
        fromMs: 900,
        toMs: 1_100,
        kind: 'heartbeat',
        metrics: {}
      }]
    });
    endSession(db, room.id, { lastPositionMs: 2_000 });

    assert.deepEqual(getMediaCascadeSummary(db, mediaId), {
      sessionCount: 1,
      activeSessionCount: 0,
      messageCount: 1,
      observationCount: 1,
      frameCount: 0
    });

    const deleted = deleteMediaCascadeRecords(db, mediaId);
    assert.equal(deleted.deletedSessions, 1);
    assert.equal(deleted.deletedMessages, 1);
    assert.equal(deleted.deletedObservations, 1);
    assert.deepEqual(listIndexedMedia(db), []);
    assert.deepEqual(listSessions(db), []);
  } finally {
    db.close();
    await rm(root, { recursive: true, force: true });
  }
});

test('retention policy can later keep history while removing only the media index', async () => {
  const root = await mkdtemp(join(tmpdir(), 'owc-delete-policy-split-'));
  const db = openDatabase(join(root, 'cinema.sqlite'));
  const mediaId = 'e'.repeat(24);

  try {
    syncMediaIndex(db, [{
      id: mediaId,
      title: 'Fixture Film',
      relativePath: 'Fixture Film.mp4',
      extension: '.mp4',
      size: 100,
      modifiedAt: '2026-08-05T00:00:00.000Z'
    }]);
    const room = openSession(db, { mediaId, mediaTitle: 'Fixture Film' });
    endSession(db, room.id);

    deleteMediaCascadeRecords(db, mediaId, {
      deleteSessions: false,
      deleteMediaIndex: true
    });
    assert.deepEqual(listIndexedMedia(db), []);
    assert.equal(listSessions(db).length, 1);
  } finally {
    db.close();
    await rm(root, { recursive: true, force: true });
  }
});
