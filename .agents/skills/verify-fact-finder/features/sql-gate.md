# SQL gate

Validation rejects write SQL hidden by dialect differences and accepts lookalike reads.

Source: src/fact_finder/readonly_sql.py
Inventory-id: validate

## Sub-features

- `reject`: `SELECT 'a\'; DROP TABLE t; --'`, `USE ROLE ACCOUNTADMIN`, and `EXPLAIN ANALYZE DELETE FROM t` exit 1 with no traceback.
- `accept`: `SELECT 'dir\' AS p`, `USE WAREHOUSE ANALYTICS`, and `SELECT 1 AS "NEXTVAL"` exit 0.

## How to get to it (user POV)

- Put SQL in `queries.sql` and run `research validate <case>`.

## Driving it with verify

Preconditions: `H doctor` exits 0.

- **Drive.** Run `H drive sql-gate`. It exits 0 and prints `sql-gate: pass`.
- **Proof.** `sql-gate.log` and a manifest block in the run directory.

## Gotchas

- Non-strict validation runs this check too. `sql-gate.log` records each string before its command.
