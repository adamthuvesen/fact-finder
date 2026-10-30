# First-time setup

## Prerequisites

`uv`, plus Claude Code or Codex CLI recent enough for native goals. Run `./scripts/setup-dev.sh`. Its
checker may fail until you finish personal auth. `uv run python scripts/check_agent_setup.py` checks
again later. Having no servers is a pass.

## Sources

1. Run `uv run research source enable <name>`.
2. Run `uv run research source show <name>`, and follow it for credentials and its read-only control.
3. **Claude Code:** run `/mcp`. **Codex:** trust this repo, then run `codex mcp login <server>`.
   **Cursor:** complete OAuth in Settings, MCP.
4. Run `uv run research doctor`.

Deny rules go in the untracked `.claude/settings.local.json`. Claude Code merges them with shared settings.
A claude.ai connector is the exception. Every clone can reach one, so `research setup` writes the
`[[connectors]]` rules of every bundle to the committed `.claude/settings.json`. `doctor` fails when
one is missing. Commit that file after setup adds rules.

**Do the `credential` sources first.** For them, the account or IAM role you connect is the only
rule. Verify that a write returns 403 before you leave a goal running unattended.

## Google APIs

`research gsc` and `research ga4` use Application Default Credentials with read-only scopes. Set
`GSC_SITE` or `GA4_PROPERTY_ID`. `GCP_QUOTA_PROJECT` is optional. For Snowflake, copy
[the example connection](examples/snowflake-config.toml.example).

## Add a source

Run `uv run research source new <name>`. It writes one file. Replace each `TODO`.

## Develop a consumer against a local engine

From the consumer repo, run `uv add --editable ../fact-finder`, then `uv run research setup`.
Skills, bundles, and hooks come through the editable install, so an engine edit reaches the consumer
at once. Pin a git SHA again before you ship.

## Agent hooks

`research setup` adds an edit hook to `.claude/settings.json`, `.codex/hooks.json`, and
`.cursor/hooks.json`. It reports, and never blocks. Codex asks you to review new hooks with `/hooks`,
and loads project hooks only in a trusted project.
