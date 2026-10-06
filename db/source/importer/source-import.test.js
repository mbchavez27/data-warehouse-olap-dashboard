'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { Readable } = require('node:stream');

const {
  parseMysqlRows,
  encodeCopyRow,
  assessDatabase,
  assessSourceSchema,
} = require('./source-import');

async function collect(sql, options) {
  const rows = [];
  for await (const row of parseMysqlRows(Readable.from([sql]), options)) {
    rows.push(row);
  }
  return rows;
}

test('parses multiple INSERT statements without treating dump metadata as data', async () => {
  const sql = [
    '-- MySQL dump header',
    'LOCK TABLES `Couriers` WRITE;',
    "INSERT INTO `Couriers` VALUES (1,'JNT','2025-09-22 16:56:36','2025-09-22 16:56:36'),",
    "(2,'LBCD','2025-09-22 16:56:36','2025-09-22 16:56:36');",
    'UNLOCK TABLES;',
    "INSERT INTO `Couriers` VALUES (3,NULL,'2025-09-22 16:56:36','2025-09-22 16:56:36');",
  ].join('\n');

  assert.deepEqual(await collect(sql, { table: 'Couriers', columnCount: 4 }), [
    ['1', 'JNT', '2025-09-22 16:56:36', '2025-09-22 16:56:36'],
    ['2', 'LBCD', '2025-09-22 16:56:36', '2025-09-22 16:56:36'],
    ['3', null, '2025-09-22 16:56:36', '2025-09-22 16:56:36'],
  ]);
});

test('decodes MySQL escapes while preserving commas, parentheses, and unicode in strings', async () => {
  const tick = '`';
  const sql = String.raw`INSERT INTO ${tick}Users${tick} VALUES (99,'O\'Connell','comma, (paren)','slash\\tab\tline\nzero\0quote\"','address1','address2','Makati','PH','1000','0917','2000-01-01','F','2025-01-01 00:00:00','2025-01-01 00:00:00'),(100,'José','ok',NULL,'x','y','city','z','1','2','2001-01-01','M','2025-01-01 00:00:00','2025-01-01 00:00:00');`;

  const rows = await collect(sql, { table: 'Users', columnCount: 14 });
  assert.equal(rows[0][1], "O'Connell");
  assert.equal(rows[0][2], 'comma, (paren)');
  assert.equal(rows[0][3], 'slash\\tab\tline\nzero\0quote"');
  assert.equal(rows[1][1], 'José');
  assert.equal(rows[1][3], null);
});

test('rejects a row whose field count does not match the source table contract', async () => {
  const sql = "INSERT INTO `Couriers` VALUES (1,'missing timestamps');";

  await assert.rejects(
    async () => collect(sql, { table: 'Couriers', columnCount: 4 }),
    /Couriers row 1 has 2 fields; expected 4/,
  );
});

test('encodes PostgreSQL COPY text without confusing null with the string NULL', () => {
  assert.equal(
    encodeCopyRow(['a\tb', 'line\nnext', 'slash\\value', null, 'NULL']),
    'a\\tb\tline\\nnext\tslash\\\\value\t\\N\tNULL\n',
  );
});

test('database assessment passes only exact row counts with zero orphans', () => {
  const expected = { Couriers: 3, Riders: 100 };

  assert.deepEqual(
    assessDatabase({ counts: { Couriers: 3, Riders: 100 }, orphans: { riderCourier: 0 } }, expected),
    { passed: true, countMismatches: [], orphanViolations: [] },
  );
});

test('database assessment reports count mismatches and every orphan relationship', () => {
  const assessment = assessDatabase(
    {
      counts: { Couriers: 2, Riders: 100 },
      orphans: { riderCourier: 4, orderUser: 0, itemProduct: 7 },
    },
    { Couriers: 3, Riders: 100 },
  );

  assert.equal(assessment.passed, false);
  assert.deepEqual(assessment.countMismatches, [
    { table: 'Couriers', expected: 3, actual: 2 },
  ]);
  assert.deepEqual(assessment.orphanViolations, [
    { relationship: 'riderCourier', count: 4 },
    { relationship: 'itemProduct', count: 7 },
  ]);
});

test('source-schema assessment accepts only the replicated table and constraint shape', () => {
  const expectedColumns = { Couriers: 4, Riders: 9 };
  const valid = {
    tableCount: 2,
    columnCounts: { Couriers: 4, Riders: 9 },
    primaryKeyCount: 2,
    foreignKeyCount: 2,
    identityColumnCount: 2,
    productIdIndex: true,
  };

  assert.deepEqual(assessSourceSchema(valid, expectedColumns, {
    primaryKeyCount: 2,
    foreignKeyCount: 2,
    identityColumnCount: 2,
  }), { passed: true, violations: [] });
});

test('source-schema assessment reports missing tables, wrong columns, and missing index', () => {
  const assessment = assessSourceSchema({
    tableCount: 1,
    columnCounts: { Couriers: 3, Riders: 9 },
    primaryKeyCount: 1,
    foreignKeyCount: 2,
    identityColumnCount: 2,
    productIdIndex: false,
  }, { Couriers: 4, Riders: 9 }, {
    primaryKeyCount: 2,
    foreignKeyCount: 2,
    identityColumnCount: 2,
  });

  assert.equal(assessment.passed, false);
  assert.deepEqual(assessment.violations, [
    { check: 'tableCount', expected: 2, actual: 1 },
    { check: 'Couriers.columnCount', expected: 4, actual: 3 },
    { check: 'primaryKeyCount', expected: 2, actual: 1 },
    { check: 'OrderItems.ProductIdIndex', expected: true, actual: false },
  ]);
});
