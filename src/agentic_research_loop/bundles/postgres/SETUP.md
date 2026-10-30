# Postgres (read-only)

**Server:** Postgres MCP Pro (Crystal DBA) - stdio, run via `uvx postgres-mcp`
(also `pipx install postgres-mcp` or the `crystaldba/postgres-mcp` Docker image).

**Read-only enforcement (`server-flag:--access-mode=restricted`):** restricted
mode parses every statement with `pglast`, runs it inside a **read-only
transaction**, rejects `COMMIT`/`ROLLBACK`, and caps execution time. This is a
genuine server-side read-only mode, stronger than first-keyword checks.

## Enable

1. `uv run research source enable postgres`.
3. **Provide the connection string via your environment - never commit it.**
   `.mcp.json` is tracked by git, so do **not** paste a password into it. Export
   `DATABASE_URI` in your shell (or a secret manager) before launching the agent:
   ```bash
   export DATABASE_URI="$(op read 'op://vault/postgres-readonly/uri')"
   # or: export DATABASE_URI="postgresql://readonly:***@host:5432/dbname"
   ```
   The stdio server inherits this from the environment.
4. **Defense in depth (recommended):** point `DATABASE_URI` at a role with only
   `SELECT` + `USAGE` grants. The restricted flag blocks writes; a read-only role
   means the credential can't write either.
