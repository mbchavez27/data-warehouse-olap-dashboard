'use strict';

const { spawn } = require('node:child_process');

function openArchiveEntry(archive, entry, options = {}) {
  const process = spawn('tar', ['-xOf', archive, entry], {
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    ...options,
  });
  let stderr = '';
  process.stderr.setEncoding('utf8');
  process.stderr.on('data', (chunk) => { stderr += chunk; });

  // Attach before returning. A tiny extraction can emit `close` before its
  // stdout consumer finishes, so attaching after iteration creates a race.
  const completed = new Promise((resolve, reject) => {
    process.once('error', reject);
    process.once('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`could not extract ${entry}: ${stderr.trim()}`));
    });
  });
  completed.catch(() => {});

  return {
    readable: process.stdout,
    completed,
    terminate: () => process.kill(),
  };
}

module.exports = { openArchiveEntry };
