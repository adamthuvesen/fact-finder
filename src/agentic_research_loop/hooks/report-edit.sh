#!/bin/sh
# With a client name: a client's edit hook. It reads the hook JSON on stdin, reports to the
# agent, and always exits 0, because a hook reports and does not block.
# With no argument: `make quick`. It checks every file git sees as changed, and every local case
# under research/ for hard failures. It exits 1 on a problem, and 2 when it cannot check.
client=${1:-}
SETUP_FIX='Fix: run `uv sync --dev`.'

run() { uv run --quiet --no-sync "$@"; }
has() { run "$1" --version >/dev/null 2>&1; }
each() { tr '\n' '\0' | xargs -0 uv run --quiet --no-sync "$@"; }

if [ -n "$client" ]; then
  changed=$(run research hook files 2>/dev/null) || exit 0
else
  if ! run research --help >/dev/null 2>&1; then
    echo "make quick: the project environment is not ready. $SETUP_FIX" >&2
    exit 2
  fi
  changed=$(git status --porcelain -z --no-renames --untracked-files=all | tr '\0' '\n' | cut -c4-)
fi
existing=$(printf '%s\n' "$changed" | while IFS= read -r file; do
  if [ -f "$file" ]; then printf '%s\n' "$file"; fi
done)
python_files=$(printf '%s\n' "$existing" | grep '\.py$')
other_files=$(printf '%s\n' "$existing" | grep -v '\.py$')

if [ -z "$client" ] && [ -n "$python_files" ]; then
  for tool in ruff basedpyright; do
    if ! has "$tool"; then
      echo "make quick: $tool is missing, so Python files stay unchecked. $SETUP_FIX" >&2
      exit 2
    fi
  done
fi

report=$(
  if [ -n "$python_files" ]; then
    if has ruff; then
      printf '%s\n' "$python_files" | each ruff format --quiet
      printf '%s\n' "$python_files" | each ruff check --quiet --output-format=concise
    fi
    if has basedpyright; then
      types=$(printf '%s\n' "$python_files" | each basedpyright)
      status=$?
      problems=$(printf '%s\n' "$types" | grep -E ' - (error|warning):')
      if [ -n "$problems" ]; then
        printf '%s\n' "$problems"
      elif [ "$status" -ne 0 ]; then
        printf '%s\n' "$types"
      fi
    fi
  fi
  if [ -n "$other_files" ]; then
    printf '%s\n' "$other_files" | each research lint
  fi
  if [ -z "$client" ]; then
    run research lint --local-cases
  fi
) 2>&1

[ -n "$report" ] || exit 0
if [ -n "$client" ]; then
  printf '%s\n' "$report" | run research hook report "$client"
  exit 0
fi
printf '%s\n' "$report"
exit 1
