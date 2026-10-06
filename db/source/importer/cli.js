#!/usr/bin/env node
'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');

const {
  parseMysqlRows,
  encodeCopyRow,
  assessDatabase,
  assessSourceSchema,
} = require('./source-import');
const { openArchiveEntry } = require('./archive-reader');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const SOURCE_SCHEMA = path.join(__dirname, 'source-schema.sql');
const DEFAULT_REPORT = path.join(REPO_ROOT, 'evidence', 'source-import-report.json');
const FAILURE_LOG = path.join(REPO_ROOT, 'evidence', 'source-import-failures.log');
const EXPECTED_SHA256 = 'a10f11865ef05253672090e4d73d15a3d7fad96adffe6dbc6fb8c09c8037e862';
const CONTAINER = 'stadvdb-mco1-source-db';

const TABLES = [
  {
    name: 'Couriers', file: 'faker_Couriers.sql', expected: 3,
    columns: ['id', 'name', 'createdAt', 'updatedAt'],
  },
  {
    name: 'Riders', file: 'faker_Riders.sql', expected: 100,
    columns: ['id', 'firstName', 'lastName', 'vehicleType', 'courierId', 'age', 'gender', 'createdAt', 'updatedAt'],
  },
  {
    name: 'Users', file: 'faker_Users.sql', expected: 100000,
    columns: ['id', 'username', 'firstName', 'lastName', 'address1', 'address2', 'city', 'country', 'zipCode', 'phoneNumber', 'dateOfBirth', 'gender', 'createdAt', 'updatedAt'],
  },
  {
    name: 'Products', file: 'faker_Products.sql', expected: 10000,
    columns: ['id', 'productCode', 'category', 'description', 'name', 'price', 'createdAt', 'updatedAt'],
  },
  {
    name: 'Orders', file: 'faker_Orders.sql', expected: 1000000,
    columns: ['id', 'orderNumber', 'userId', 'deliveryDate', 'deliveryRiderId', 'createdAt', 'updatedAt'],
  },
  {
    name: 'OrderItems', file: 'faker_OrderItems.sql', expected: 1999824,
    columns: ['quantity', 'notes', 'createdAt', 'updatedAt', 'OrderId', 'ProductId'],
  },
];

function parseArgs(argv) {
  const command = argv[0];
  const options = {};
  for (let i = 1; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) throw new Error(`unexpected argument: ${token}`);
    const key = token.slice(2);
    if (key === 'reset') {
      options.reset = true;
      continue;
    }
    if (i + 1 >= argv.length) throw new Error(`missing value for ${token}`);
    options[key] = argv[++i];
  }
  return { command, options };
}

function usage() {
  return [
    'Usage:',
    '  npm run source:verify -- --archive <MCO1_dataset_ecommerce.zip> [--output <report.json>]',
    '  npm run source:import -- --archive <MCO1_dataset_ecommerce.zip> --reset [--output <report.json>]',
    '  npm run source:validate -- [--output <report.json>]',
    '',
    'The --reset flag is mandatory for import because it drops and recreates all six source tables.',
  ].join('\n');
}

function loadEnv(file) {
  const values = {};
  if (!fs.existsSync(file)) return values;
  for (const rawLine of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const equals = line.indexOf('=');
    if (equals < 1) continue;
    values[line.slice(0, equals).trim()] = line.slice(equals + 1).trim();
  }
  return values;
}

function child(command, args, options = {}) {
  return spawn(command, args, {
    cwd: REPO_ROOT,
    windowsHide: true,
    ...options,
  });
}

async function capture(command, args, options = {}) {
  const process = child(command, args, { stdio: ['ignore', 'pipe', 'pipe'], ...options });
  let stdout = '';
  let stderr = '';
  process.stdout.setEncoding('utf8');
  process.stderr.setEncoding('utf8');
  process.stdout.on('data', (chunk) => { stdout += chunk; });
  process.stderr.on('data', (chunk) => { stderr += chunk; });
  const [code] = await once(process, 'close');
  if (code !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed (${code}): ${stderr.trim()}`);
  }
  return stdout.trim();
}

async function sha256(file) {
  const hash = crypto.createHash('sha256');
  const stream = fs.createReadStream(file);
  stream.on('data', (chunk) => hash.update(chunk));
  await once(stream, 'end');
  return hash.digest('hex');
}

async function archiveEntries(archive) {
  const output = await capture('tar', ['-tf', archive]);
  return output.split(/\r?\n/).filter(Boolean);
}

function matchEntries(entries) {
  const matches = {};
  for (const table of TABLES) {
    const found = entries.filter((entry) => path.posix.basename(entry.replaceAll('\\', '/')) === table.file);
    if (found.length !== 1) {
      throw new Error(`${table.file}: expected exactly one archive entry, found ${found.length}`);
    }
    matches[table.name] = found[0];
  }
  return matches;
}

async function forEachArchiveRow(archive, entry, table, onRow) {
  const opened = openArchiveEntry(archive, entry, { cwd: REPO_ROOT });
  let count = 0;
  try {
    for await (const row of parseMysqlRows(opened.readable, {
      table: table.name,
      columnCount: table.columns.length,
    })) {
      count += 1;
      await onRow(row, count);
    }
  } catch (error) {
    opened.terminate();
    throw error;
  }
  await opened.completed;
  return count;
}

async function verifyArchive(archive) {
  const resolved = path.resolve(archive);
  const stat = await fsp.stat(resolved);
  if (!stat.isFile()) throw new Error(`archive is not a file: ${resolved}`);

  const digest = await sha256(resolved);
  const entries = matchEntries(await archiveEntries(resolved));
  const counts = {};
  const duplicateIds = {};
  const archiveOrphans = {
    riderCourier: 0,
    orderUser: 0,
    orderRider: 0,
    itemOrder: 0,
    itemProduct: 0,
  };
  const ids = {
    Couriers: new Set(), Riders: new Set(), Users: new Set(), Products: new Set(), Orders: new Set(),
  };

  for (const table of TABLES) {
    if (ids[table.name]) duplicateIds[table.name] = 0;
    counts[table.name] = await forEachArchiveRow(resolved, entries[table.name], table, (row) => {
      if (ids[table.name]) {
        if (ids[table.name].has(row[0])) duplicateIds[table.name] += 1;
        ids[table.name].add(row[0]);
      }
      if (table.name === 'Riders' && row[4] !== null && !ids.Couriers.has(row[4])) archiveOrphans.riderCourier += 1;
      if (table.name === 'Orders') {
        if (row[2] !== null && !ids.Users.has(row[2])) archiveOrphans.orderUser += 1;
        if (row[4] !== null && !ids.Riders.has(row[4])) archiveOrphans.orderRider += 1;
      }
      if (table.name === 'OrderItems') {
        if (!ids.Orders.has(row[4])) archiveOrphans.itemOrder += 1;
        if (!ids.Products.has(row[5])) archiveOrphans.itemProduct += 1;
      }
    });
    process.stdout.write(`Verified ${table.name}: ${counts[table.name].toLocaleString()} rows\n`);
  }

  const expectedCounts = Object.fromEntries(TABLES.map((table) => [table.name, table.expected]));
  const assessment = assessDatabase({ counts, orphans: archiveOrphans }, expectedCounts);
  const duplicateViolations = Object.entries(duplicateIds)
    .filter(([, count]) => count > 0)
    .map(([table, count]) => ({ table, count }));
  const hashMatches = digest === EXPECTED_SHA256;

  return {
    file: path.basename(resolved),
    bytes: stat.size,
    sha256: digest,
    expectedSha256: EXPECTED_SHA256,
    hashMatches,
    entries,
    counts,
    expectedCounts,
    countMismatches: assessment.countMismatches,
    orphans: archiveOrphans,
    duplicateIds,
    passed: hashMatches && assessment.passed && duplicateViolations.length === 0,
  };
}

async function writeChunk(stream, value) {
  if (!stream.write(value)) await once(stream, 'drain');
}

function quotedColumns(columns) {
  return columns.map((column) => `"${column}"`).join(', ');
}

async function requireHealthyContainer() {
  let status;
  try {
    status = await capture('docker', ['inspect', '-f', '{{.State.Health.Status}}', CONTAINER]);
  } catch (error) {
    throw new Error(`${CONTAINER} is unavailable. Run: docker compose up -d --wait source_db\n${error.message}`);
  }
  if (status !== 'healthy') {
    throw new Error(`${CONTAINER} is ${JSON.stringify(status)}; expected "healthy"`);
  }
}

async function importArchive(archive, entries, db) {
  await requireHealthyContainer();
  const schemaSql = await fsp.readFile(SOURCE_SCHEMA, 'utf8');
  const args = ['exec', '-i', CONTAINER, 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', db.user, '-d', db.name];
  const psql = child('docker', args, { stdio: ['pipe', 'pipe', 'pipe'] });
  let stdout = '';
  let stderr = '';
  psql.stdout.setEncoding('utf8');
  psql.stderr.setEncoding('utf8');
  psql.stdout.on('data', (chunk) => { stdout += chunk; });
  psql.stderr.on('data', (chunk) => { stderr += chunk; });
  const closed = once(psql, 'close');

  try {
    await writeChunk(psql.stdin, '\\set ON_ERROR_STOP on\nBEGIN;\n');
    await writeChunk(psql.stdin, `${schemaSql}\n`);

    for (const table of TABLES) {
      const command = `COPY "${table.name}" (${quotedColumns(table.columns)}) FROM STDIN WITH (FORMAT text, DELIMITER E'\\t', NULL '\\N');\n`;
      await writeChunk(psql.stdin, command);
      const count = await forEachArchiveRow(archive, entries[table.name], table, async (row) => {
        await writeChunk(psql.stdin, encodeCopyRow(row));
      });
      if (count !== table.expected) {
        throw new Error(`${table.name}: refusing import because ${count} rows were parsed; expected ${table.expected}`);
      }
      await writeChunk(psql.stdin, '\\.\n');
      process.stdout.write(`Imported ${table.name}: ${count.toLocaleString()} rows\n`);
    }

    for (const table of TABLES.filter((item) => item.name !== 'OrderItems')) {
      const sql = `SELECT setval(pg_get_serial_sequence('"${table.name}"', 'id'), COALESCE(MAX("id"), 1), MAX("id") IS NOT NULL) FROM "${table.name}";\n`;
      await writeChunk(psql.stdin, sql);
    }
    await writeChunk(psql.stdin, 'COMMIT;\n');
    psql.stdin.end();
  } catch (error) {
    psql.stdin.destroy();
    psql.kill();
    await closed;
    throw error;
  }

  const [code] = await closed;
  if (code !== 0) throw new Error(`atomic PostgreSQL import failed (${code}): ${stderr.trim()}`);
  return { transaction: 'committed', psqlOutput: stdout.trim().split(/\r?\n/).slice(-20) };
}

function validationSql() {
  return `
SELECT json_build_object(
  'counts', json_build_object(
    'Couriers', (SELECT count(*) FROM "Couriers"),
    'Riders', (SELECT count(*) FROM "Riders"),
    'Users', (SELECT count(*) FROM "Users"),
    'Products', (SELECT count(*) FROM "Products"),
    'Orders', (SELECT count(*) FROM "Orders"),
    'OrderItems', (SELECT count(*) FROM "OrderItems")
  ),
  'orphans', json_build_object(
    'riderCourier', (SELECT count(*) FROM "Riders" child LEFT JOIN "Couriers" parent ON parent."id" = child."courierId" WHERE child."courierId" IS NOT NULL AND parent."id" IS NULL),
    'orderUser', (SELECT count(*) FROM "Orders" child LEFT JOIN "Users" parent ON parent."id" = child."userId" WHERE child."userId" IS NOT NULL AND parent."id" IS NULL),
    'orderRider', (SELECT count(*) FROM "Orders" child LEFT JOIN "Riders" parent ON parent."id" = child."deliveryRiderId" WHERE child."deliveryRiderId" IS NOT NULL AND parent."id" IS NULL),
    'itemOrder', (SELECT count(*) FROM "OrderItems" child LEFT JOIN "Orders" parent ON parent."id" = child."OrderId" WHERE parent."id" IS NULL),
    'itemProduct', (SELECT count(*) FROM "OrderItems" child LEFT JOIN "Products" parent ON parent."id" = child."ProductId" WHERE parent."id" IS NULL)
  ),
  'schema', json_build_object(
    'tableCount', (SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ANY (ARRAY['Couriers','Riders','Users','Products','Orders','OrderItems'])),
    'columnCounts', json_build_object(
      'Couriers', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'Couriers'),
      'Riders', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'Riders'),
      'Users', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'Users'),
      'Products', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'Products'),
      'Orders', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'Orders'),
      'OrderItems', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'OrderItems')
    ),
    'primaryKeyCount', (SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace WHERE n.nspname = 'public' AND r.relname = ANY (ARRAY['Couriers','Riders','Users','Products','Orders','OrderItems']) AND c.contype = 'p'),
    'foreignKeyCount', (SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace WHERE n.nspname = 'public' AND r.relname = ANY (ARRAY['Couriers','Riders','Users','Products','Orders','OrderItems']) AND c.contype = 'f'),
    'identityColumnCount', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = ANY (ARRAY['Couriers','Riders','Users','Products','Orders']) AND is_identity = 'YES'),
    'productIdIndex', (to_regclass('public."OrderItems_ProductId_idx"') IS NOT NULL)
  )
)::text;
`;
}

async function validateDatabase(db) {
  await requireHealthyContainer();
  const output = await capture('docker', [
    'exec', CONTAINER, 'psql', '-X', '-At', '-v', 'ON_ERROR_STOP=1',
    '-U', db.user, '-d', db.name, '-c', validationSql(),
  ]);
  const actual = JSON.parse(output);
  for (const group of [actual.counts, actual.orphans]) {
    for (const key of Object.keys(group)) group[key] = Number(group[key]);
  }
  actual.schema.tableCount = Number(actual.schema.tableCount);
  actual.schema.primaryKeyCount = Number(actual.schema.primaryKeyCount);
  actual.schema.foreignKeyCount = Number(actual.schema.foreignKeyCount);
  actual.schema.identityColumnCount = Number(actual.schema.identityColumnCount);
  for (const key of Object.keys(actual.schema.columnCounts)) {
    actual.schema.columnCounts[key] = Number(actual.schema.columnCounts[key]);
  }
  const expected = Object.fromEntries(TABLES.map((table) => [table.name, table.expected]));
  const expectedColumns = Object.fromEntries(TABLES.map((table) => [table.name, table.columns.length]));
  const dataAssessment = assessDatabase(actual, expected);
  const schemaAssessment = assessSourceSchema(actual.schema, expectedColumns, {
    primaryKeyCount: 6,
    foreignKeyCount: 2,
    identityColumnCount: 5,
  });
  return {
    ...actual,
    countMismatches: dataAssessment.countMismatches,
    orphanViolations: dataAssessment.orphanViolations,
    schemaViolations: schemaAssessment.violations,
    passed: dataAssessment.passed && schemaAssessment.passed,
  };
}

async function writeReport(file, report) {
  const resolved = path.resolve(file || DEFAULT_REPORT);
  await fsp.mkdir(path.dirname(resolved), { recursive: true });
  await fsp.writeFile(resolved, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  process.stdout.write(`Evidence written to ${path.relative(REPO_ROOT, resolved)}\n`);
}

async function recordFailure(command, error) {
  await fsp.mkdir(path.dirname(FAILURE_LOG), { recursive: true });
  const safe = String(error.stack || error).replaceAll(/\r?\n/g, ' | ');
  await fsp.appendFile(FAILURE_LOG, `${new Date().toISOString()}\t${command || 'unknown'}\t${safe}\n`, 'utf8');
}

async function main() {
  const { command, options } = parseArgs(process.argv.slice(2));
  if (!['verify', 'import', 'validate'].includes(command)) throw new Error(usage());
  if ((command === 'verify' || command === 'import') && !options.archive) {
    throw new Error(`--archive is required\n\n${usage()}`);
  }
  if (command === 'import' && !options.reset) {
    throw new Error(`import is destructive and requires explicit --reset\n\n${usage()}`);
  }

  const env = loadEnv(path.join(REPO_ROOT, '.env'));
  const db = { user: env.SOURCE_USER || 'postgres', name: env.SOURCE_DB || 'source_db' };
  const report = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    command,
    sourceDatabase: { engine: 'PostgreSQL', version: 16, container: CONTAINER, database: db.name },
    importFailures: [],
  };

  if (command === 'verify' || command === 'import') {
    report.archive = await verifyArchive(options.archive);
    if (!report.archive.passed) throw new Error('archive verification failed; inspect reported hash, counts, duplicates, and orphans');
  }
  if (command === 'import') {
    report.import = await importArchive(path.resolve(options.archive), report.archive.entries, db);
  }
  if (command === 'import' || command === 'validate') {
    report.database = await validateDatabase(db);
    if (!report.database.passed) throw new Error('database validation failed; row counts or orphan checks did not pass');
  }
  report.passed = (report.archive?.passed ?? true) && (report.database?.passed ?? true);
  await writeReport(options.output, report);
}

main().catch(async (error) => {
  const command = process.argv[2];
  try { await recordFailure(command, error); } catch { /* retain the primary error */ }
  process.stderr.write(`ERROR: ${error.message}\n`);
  process.exitCode = 1;
});
