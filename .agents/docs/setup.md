# First-time setup

This repo ships neutral MCP configs. Enable the sources you need, then authenticate
personally to each one. Nothing in git carries credentials.

## Prerequisites

- `uv`
- Claude Code or Codex CLI, recent enough for native goals
- Access to the systems behind the sources you enable

Run `./scripts/setup-dev.sh`. Its checker may fail until you finish personal auth.

## Native goals

- **Claude Code:** run `/goal` once to confirm your version supports it.
- **Codex:** goals sit behind a flag. `research setup` and `research source enable` write
  `[features] goals = true` into `.codex/config.toml`. Confirm with `codex features list`.

There are no permission-bypass flags in this repo, so tool permissions prompt normally.

## Sources

1. Run `uv run research source enable <name>`. The
   [catalog](../../examples/sources/README.md) lists every bundle.
2. Follow that bundle's `SETUP.md` for credentials and its read-only control.
3. **Claude Code:** run `/mcp` and approve the server. **Codex:** mark this repo as a
   trusted project, then run `codex mcp login <server>` for HTTP servers. **Cursor:**
   complete OAuth in Settings, MCP.
4. Run `uv run research doctor`.

**Do the `credential` sources first.** For them, nothing in committed config can
guarantee read-only. The account or IAM role you connect is the only rule. Amplitude,
Mixpanel, and HubSpot servers are read+write with destructive tools and no read-only
flag. Verify that a write returns 403 before you leave a goal running unattended.

Do not commit enabled configs back to this repo. A test keeps `.mcp.json` neutral.

## Google APIs

`research gsc` and `research ga4` use Application Default Credentials with read-only
scopes. Set `GSC_SITE` or `GA4_PROPERTY_ID`. There is no default. `GCP_QUOTA_PROJECT` is
optional. See the `gsc` and `ga4` bundles' `SETUP.md`. For Snowflake, copy
[the example connection](examples/snowflake-config.toml.example).

## Verify

`uv run python scripts/check_agent_setup.py` checks `uv`, the goal prerequisites, and
`claude mcp get` for the servers you enabled. Having no servers is a pass: web-search and
`--context-path` cases need none.

## Add a source

Create `examples/sources/<name>/` with `source.json`, `SETUP.md`, and, for an MCP server,
`mcp.snippet.json`. Copy an existing bundle. List write tools only when `SETUP.md` names
them. Run `uv run python scripts/generate_source_docs.py`, then `make check`.
