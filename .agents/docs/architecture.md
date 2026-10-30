# Architecture

`agentic-research-loop` is a research kit for bounded investigations, not an agent
runtime. The client owns execution. The repo owns everything around it.

```text
/goal names research-goal (or research-spec)
  -> skill calls research init and research goal
  -> case artifacts -> research validate --strict
```

## Modules

`make boundaries` enforces these layers. A module imports only from layers below it.

| Layer | Modules | Job |
| --- | --- | --- |
| CLI | `cli` | Commands, printing, clean errors |
| Workflows | `research`, `validation`, `repo_setup`, `doctor`, `source_catalog` | Create, validate, set up, check, generate docs |
| Bundles | `source_bundles` | Find, enable, and disable bundles |
| Domain | `evidence`, `client_configs`, `templates`, `from_spec` | Evidence contract, client shapes, artifact text |
| Models | `sources`, `readonly_sql`, `strict_model` | Source registry, SQL parsing, the Pydantic base |
| I/O | `layout`, `io`, `google_api` | Paths, atomic writes, read-only API calls |

Skills, bundles, and the method and evidence contract live inside the package as data
(`src/agentic_research_loop/skills`, `.../bundles`, `.../contract`), so a consumer gets them from its
pin. `.agents/skills/*` and `examples/sources` are symlinks to them in this repo.

## Absolute paths

Every path in the goal contract is resolved, because a goal handed relative paths can write
a correct answer into the wrong directory and still look finished.
`resolve_case_path` refuses any case that is not a direct child of `research/`.

## Source boundary

A bundle has `source.json`, `SETUP.md`, and, for an MCP server, `mcp.snippet.json`. The
last holds one server definition. `client_configs` generates each client's shape and
deny list from it. It adds only what is missing and keeps every existing value. A server
name it did not add is a collision: the command fails and changes nothing.
`config/sources.json` records what it added, and disable removes only that.

`read_only_control` in `source.json` names one mechanism from a closed set:

- **Checked from config:** `url_suffix`, `server_flag`, `arg_absent`,
  `statement_allowlist`. `research doctor` fails when one does not hold.
- **Declared only:** `credential_scope`, `credential`, `native`. These live in a grant
  or an account that no file here can show. Doctor reports them as declared.

Doctor reads each client's wired entry and deny list. It never contacts a server, so a
pass says nothing about what the upstream server does. An unfilled placeholder reports
`needs-setup`. Deny lists cover only write tools a bundle's `SETUP.md` names.

`research init` records a case's allowed sources in its brief, and `research goal` reads them.

## SQL boundary

`readonly_sql` parses preserved SQL under eight dialect readings and requires every
reading that parses to be read-only. It rejects executable and nested block comments on
the raw text, because a comment is invisible to the parser. It cannot detect `SELECT side_effect_proc()`. The
read-only role on the connection is the real guard.

## Validation

`research validate` checks structure, read-only SQL, and evidence integrity, and is safe
at scaffold time. `--strict` is the goal's terminal condition. `evidence.json` owns
evidence, `review.json` owns the final challenge, and `notes.md` carries no gate. See
[the evidence contract](../../docs/evidence-contract.md).

## Deliberate omissions

The repo has no subprocess runners, cycle markers, retry loop, progress hash, stall
detector, machine challenge state, permission bypass flags, status renderer, or
publishing layer. See [the decision record](decisions/native-goals.md) and
[the canary](../../evals/native-goal/README.md).
