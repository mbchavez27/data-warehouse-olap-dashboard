'use strict';

/**
 * Stream rows from the extended INSERT statements emitted by mysqldump.
 * The parser deliberately ignores DDL/LOCK metadata and never buffers a full
 * INSERT statement, which matters for the multi-million-row OrderItems dump.
 */
async function* parseMysqlRows(readable, { table, columnCount }) {
  if (!table || !Number.isInteger(columnCount) || columnCount < 1) {
    throw new TypeError('table and a positive integer columnCount are required');
  }

  const marker = `INSERT INTO \`${table}\` VALUES`;
  readable.setEncoding('utf8');

  let buffer = '';
  let state = 'search';
  let fieldState = 'start';
  let row = [];
  let field = '';
  let rowNumber = 0;
  let sawInsert = false;

  const mysqlEscapes = {
    '0': '\0',
    b: '\b',
    n: '\n',
    r: '\r',
    t: '\t',
    Z: '\x1a',
    "'": "'",
    '"': '"',
    '\\': '\\',
    '%': '%',
    _: '_',
  };

  function finishField(quoted) {
    if (!quoted) {
      field = field.trim();
    }
    row.push(!quoted && field.toUpperCase() === 'NULL' ? null : field);
    field = '';
    fieldState = 'start';
  }

  function finishRow() {
    rowNumber += 1;
    if (row.length !== columnCount) {
      throw new Error(`${table} row ${rowNumber} has ${row.length} fields; expected ${columnCount}`);
    }
    const completed = row;
    row = [];
    return completed;
  }

  for await (const chunk of readable) {
    buffer += chunk;
    let offset = 0;

    while (offset < buffer.length) {
      if (state === 'search') {
        const found = buffer.indexOf(marker, offset);
        if (found === -1) {
          const keep = Math.min(marker.length - 1, buffer.length - offset);
          buffer = buffer.slice(buffer.length - keep);
          offset = 0;
          break;
        }
        sawInsert = true;
        offset = found + marker.length;
        state = 'betweenRows';
        continue;
      }

      const ch = buffer[offset];

      if (state === 'betweenRows') {
        if (/\s/.test(ch) || ch === ',') {
          offset += 1;
          continue;
        }
        if (ch === '(') {
          row = [];
          field = '';
          fieldState = 'start';
          state = 'inRow';
          offset += 1;
          continue;
        }
        if (ch === ';') {
          state = 'search';
          offset += 1;
          continue;
        }
        throw new Error(`${table}: expected row or statement terminator, found ${JSON.stringify(ch)}`);
      }

      if (fieldState === 'start') {
        if (/\s/.test(ch)) {
          offset += 1;
          continue;
        }
        if (ch === "'") {
          fieldState = 'quoted';
          offset += 1;
          continue;
        }
        fieldState = 'unquoted';
        continue;
      }

      if (fieldState === 'unquoted') {
        if (ch === ',') {
          finishField(false);
          offset += 1;
          continue;
        }
        if (ch === ')') {
          finishField(false);
          const completed = finishRow();
          state = 'betweenRows';
          offset += 1;
          yield completed;
          continue;
        }
        field += ch;
        offset += 1;
        continue;
      }

      if (fieldState === 'quoted') {
        if (ch === '\\') {
          fieldState = 'escape';
          offset += 1;
          continue;
        }
        if (ch === "'") {
          fieldState = 'afterQuote';
          offset += 1;
          continue;
        }
        field += ch;
        offset += 1;
        continue;
      }

      if (fieldState === 'escape') {
        field += Object.hasOwn(mysqlEscapes, ch) ? mysqlEscapes[ch] : ch;
        fieldState = 'quoted';
        offset += 1;
        continue;
      }

      if (fieldState === 'afterQuote') {
        if (ch === "'") {
          field += "'";
          fieldState = 'quoted';
          offset += 1;
          continue;
        }
        if (/\s/.test(ch)) {
          offset += 1;
          continue;
        }
        if (ch === ',') {
          finishField(true);
          offset += 1;
          continue;
        }
        if (ch === ')') {
          finishField(true);
          const completed = finishRow();
          state = 'betweenRows';
          offset += 1;
          yield completed;
          continue;
        }
        throw new Error(`${table} row ${rowNumber + 1}: unexpected ${JSON.stringify(ch)} after quoted field`);
      }
    }

    if (offset >= buffer.length) {
      buffer = '';
    }
  }

  if (!sawInsert) {
    throw new Error(`${table}: no matching INSERT statement found`);
  }
  if (state !== 'search') {
    throw new Error(`${table}: unexpected end of dump while parsing ${state}`);
  }
}

function encodeCopyRow(row) {
  const encoded = row.map((value) => {
    if (value === null) return '\\N';
    return value
      .replaceAll('\\', '\\\\')
      .replaceAll('\t', '\\t')
      .replaceAll('\n', '\\n')
      .replaceAll('\r', '\\r');
  });
  return `${encoded.join('\t')}\n`;
}

function assessDatabase(actual, expectedCounts) {
  const countMismatches = Object.entries(expectedCounts)
    .filter(([table, expected]) => actual.counts[table] !== expected)
    .map(([table, expected]) => ({ table, expected, actual: actual.counts[table] }));

  const orphanViolations = Object.entries(actual.orphans)
    .filter(([, count]) => count !== 0)
    .map(([relationship, count]) => ({ relationship, count }));

  return {
    passed: countMismatches.length === 0 && orphanViolations.length === 0,
    countMismatches,
    orphanViolations,
  };
}

function assessSourceSchema(actual, expectedColumns, expectedShape) {
  const violations = [];
  const check = (name, expected, value) => {
    if (value !== expected) violations.push({ check: name, expected, actual: value });
  };

  check('tableCount', Object.keys(expectedColumns).length, actual.tableCount);
  for (const [table, count] of Object.entries(expectedColumns)) {
    check(`${table}.columnCount`, count, actual.columnCounts[table]);
  }
  check('primaryKeyCount', expectedShape.primaryKeyCount, actual.primaryKeyCount);
  check('foreignKeyCount', expectedShape.foreignKeyCount, actual.foreignKeyCount);
  check('identityColumnCount', expectedShape.identityColumnCount, actual.identityColumnCount);
  check('OrderItems.ProductIdIndex', true, actual.productIdIndex);

  return { passed: violations.length === 0, violations };
}

module.exports = {
  parseMysqlRows,
  encodeCopyRow,
  assessDatabase,
  assessSourceSchema,
};
