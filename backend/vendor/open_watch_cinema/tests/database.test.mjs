import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { listIndexedMedia, openDatabase, syncMediaIndex } from '../src/database.mjs';

test('SQLite media index creates, updates, and hides missing entries', async () => {
  const root = await mkdtemp(join(tmpdir(), 'open-watch-cinema-db-'));
  const databasePath = join(root, 'cinema.sqlite');
  const db = openDatabase(databasePath);

  try {
    syncMediaIndex(db, [
      {
        id: 'a'.repeat(24),
        title: 'First Film',
        relativePath: 'First Film.mp4',
        extension: '.mp4',
        size: 123,
        modifiedAt: '2026-08-05T00:00:00.000Z'
      }
    ]);

    assert.equal(listIndexedMedia(db).length, 1);

    syncMediaIndex(db, []);
    assert.deepEqual(listIndexedMedia(db), []);
  } finally {
    db.close();
    await rm(root, { recursive: true, force: true });
  }
});
