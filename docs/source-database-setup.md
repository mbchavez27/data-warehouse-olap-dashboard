# Source Database Setup and Validation

## Requirement coverage

This implementation satisfies the stated requirement to download and import the assigned public dataset into a local MySQL or PostgreSQL source database. PostgreSQL 16 is used. Synthetic rows are not added because the supplied archive already contains 3,109,927 rows.

| Required outcome | Implementation and evidence |
|---|---|
| PostgreSQL runs locally | `source_db` in `docker-compose.yml`, exposed on port 5433 by default, with a health check |
| Dataset is downloaded and identified | The external ZIP is required at runtime; SHA-256 must equal `a10f11865ef05253672090e4d73d15a3d7fad96adffe6dbc6fb8c09c8037e862` |
| All six source tables are imported | The importer streams each MySQL dump from the ZIP to PostgreSQL `COPY`; it does not load the 238 MB uncompressed dataset into memory |
| Actual rows match the dataset | Archive counts are checked before import and database counts are re-queried after import |
| Import is safe | Schema creation and six table loads occur in one transaction; parsing, `COPY`, or constraint failure rolls the transaction back |
| Orphans are documented | Five relationship counts are calculated from the archive and independently queried in PostgreSQL |
| Failures are documented | Command failures append timestamped diagnostics to `evidence/source-import-failures.log`; the successful report records `importFailures: []` |
| Another member can reproduce it | Only Docker, Node.js, `tar`, the repository, and the official ZIP are needed; commands are below |

## Expected official-dataset results

| Table | Exact rows |
|---|---:|
| Couriers | 3 |
| Riders | 100 |
| Users | 100,000 |
| Products | 10,000 |
| Orders | 1,000,000 |
| OrderItems | 1,999,824 |
| **Total** | **3,109,927** |

Expected orphan counts are zero for `Riders.courierId`, `Orders.userId`, `Orders.deliveryRiderId`, `OrderItems.OrderId`, and `OrderItems.ProductId`.

## Reproduce from a fresh clone

1. Install and start Docker Desktop. Install Node.js 18 or newer. The importer requires bsdtar/libarchive available as `tar` (built into Windows 10/11 and macOS; Debian/Ubuntu package: `libarchive-tools`). Confirm these commands work:

   ```powershell
   docker version
   docker compose version
   node --version
   tar --version
   ```

2. Clone or copy the repository. Keep `MCO1_dataset_ecommerce.zip` outside Git; do not extract or rename its contents.

3. From the repository root, run the importer tests and verify the ZIP without touching a database:

   ```powershell
   npm run test:source
   npm run source:verify -- --archive "C:\absolute\path\MCO1_dataset_ecommerce.zip"
   ```

4. Create the local ignored environment file, then start only the source database and wait for its health check:

   ```powershell
   Copy-Item .env.example .env
   docker compose up -d --wait source_db
   ```

   Defaults are `source_db`, user `postgres`, password `postgres`, host port `5433`. Edit the local `.env` before starting the service if overrides are needed. Do not commit it.

5. Import and validate. The explicit `--reset` acknowledges that the six source tables will be replaced:

   ```powershell
   npm run source:import -- --archive "C:\absolute\path\MCO1_dataset_ecommerce.zip" --reset
   ```

6. Open `evidence/source-import-report.json`. Completion requires all of the following:

   - top-level `passed` is `true`;
   - `archive.hashMatches` is `true`;
   - `archive.countMismatches` is empty;
   - every value in `archive.orphans` and `archive.duplicateIds` is zero (the composite `OrderItems` key is enforced by PostgreSQL during import);
   - `import.transaction` is `committed`;
   - `database.countMismatches` and `database.orphanViolations` are empty;
   - `database.schemaViolations` is empty;
   - `database.passed` is `true`.

7. Any member can independently re-query the populated database without reimporting:

   ```powershell
   npm run source:validate
   ```

The repository's pre-existing `db/scripts/init_source.sh` is a schema-only scaffold and does not import the dataset. For complete source-database reproduction on every platform, use the `npm run source:import` command above.

## Failure and recovery rules

- A hash mismatch means the ZIP is not the verified course dataset. Obtain the official file again; do not bypass the check.
- A count, duplicate, malformed-row, or orphan failure means the source archive is inconsistent with the accepted dataset. Preserve the failure log and do not continue to data warehouse design.
- A Docker health failure means PostgreSQL is unavailable. Run `docker compose logs source_db`, correct the local Docker issue, and retry.
- An import failure is atomic: the transaction does not commit a partially loaded database. After correcting the cause, rerun the same command with `--reset`.
- Do not run `docker compose down -v` unless intentionally deleting the local database volume.

## Current Source Database Acceptance Checklist

- [x] `npm run test:source` passes (9 tests).
- [x] Offline archive verification passes with the expected SHA-256.
- [x] The PostgreSQL container reports `healthy`.
- [x] The import transaction reports `committed`.
- [x] All six PostgreSQL counts exactly match the table above.
- [x] All five PostgreSQL orphan counts are zero.
- [x] The source schema-fidelity checks have no violations.
- [x] `evidence/source-import-report.json` and the independent `evidence/source-db-revalidation.json` have top-level `passed: true`.
- [ ] A second team member successfully follows the fresh-clone procedure.
- [x] The ZIP and local `.env` database credentials are not committed to Git.

Do not claim the source database setup complete until every item is checked. The second-member item is a team process requirement and must be performed by another member rather than inferred from one machine.
