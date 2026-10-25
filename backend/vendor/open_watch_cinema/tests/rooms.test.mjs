import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import {
  addSessionMessage,
  endSession,
  getActiveSession,
  listSessionMessages,
  listSessions,
  openDatabase,
  openSession
} from '../src/database.mjs';

test('room messages bind to film time and archived rooms reject new writes', async () => {
  const root = await mkdtemp(join(tmpdir(), 'open-watch-cinema-room-'));
  const databasePath = join(root, 'cinema.sqlite');
  const db = openDatabase(databasePath);

  try {
    const room = openSession(db, {
      mediaId: 'a'.repeat(24),
      mediaTitle: 'Test Film'
    });
    assert.equal(room.status, 'active');
    assert.equal(getActiveSession(db).id, room.id);

    const message = addSessionMessage(db, room.id, {
      senderName: 'Viewer',
      senderKind: 'user',
      content: 'This belongs at twelve seconds.',
      mediaTimeMs: 12_345
    });
    assert.equal(message.mediaTimeMs, 12_345);
    const secondMessage = addSessionMessage(db, room.id, {
      senderName: 'Elias',
      senderKind: 'ai',
      content: 'I saw it too.',
      mediaTimeMs: 13_000
    });
    assert.equal(listSessionMessages(db, room.id).length, 2);
    assert.deepEqual(
      listSessionMessages(db, room.id, { afterId: message.id, limit: 1 }).map((item) => item.id),
      [secondMessage.id]
    );

    const ended = endSession(db, room.id, { lastPositionMs: 22_000 });
    assert.equal(ended.status, 'ended');
    assert.equal(getActiveSession(db), null);
    assert.equal(listSessions(db)[0].messageCount, 2);

    assert.throws(
      () => addSessionMessage(db, room.id, {
        senderName: 'Viewer',
        content: 'This must not be accepted.',
        mediaTimeMs: 23_000
      }),
      /read-only/i
    );
  } finally {
    db.close();
    await rm(root, { recursive: true, force: true });
  }
});
