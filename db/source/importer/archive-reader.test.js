'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const { openArchiveEntry } = require('./archive-reader');

test('observes archive-process completion even when a tiny entry exits before its stream is consumed', async (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'source-import-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const sqlFile = path.join(directory, 'tiny.sql');
  const archive = path.join(directory, 'tiny.zip');
  fs.writeFileSync(sqlFile, "INSERT INTO `Tiny` VALUES (1,'ok');\n", 'utf8');
  const packed = spawnSync('tar', ['-a', '-cf', archive, '-C', directory, 'tiny.sql'], { encoding: 'utf8' });
  assert.equal(packed.status, 0, packed.stderr);

  const opened = openArchiveEntry(archive, 'tiny.sql');
  let text = '';
  for await (const chunk of opened.readable) text += chunk;

  await assert.doesNotReject(() => Promise.race([
    opened.completed,
    new Promise((_, reject) => setTimeout(() => reject(new Error('missed process completion')), 1000)),
  ]));
  assert.match(text, /INSERT INTO `Tiny`/);
});
