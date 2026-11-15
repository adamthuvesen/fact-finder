RUN := uv run --locked

.PHONY: check fix quick verify slow audit lock lint types deps dead boundaries rules test workflows secrets vulnerabilities

# Offline gate. CI runs the same targets.
check: lock lint types deps dead boundaries rules test

# Apply every auto-fixer: ruff lint fixes, then ruff format.
fix:
	$(RUN) ruff check --fix . .agents/skills/verify-fact-finder/verify
	$(RUN) ruff format . .agents/skills/verify-fact-finder/verify

# Only what changed, in about two seconds. The edit hook runs the same script on one file.
quick:
	@sh .agents/hooks/report-edit.sh

# Drives the CLI installed from a wheel. ARGS: all, list, control, or drive names.
verify:
	$(RUN) python .agents/skills/verify-fact-finder/verify $(ARGS)

# Everything offline that check leaves out: every verify drive, then the control. CI runs it after check.
slow:
	$(MAKE) --no-print-directory verify ARGS=all
	$(MAKE) --no-print-directory verify ARGS=control

# Needs the network for the vulnerability database.
audit: workflows secrets vulnerabilities

lock:
	uv lock --check

lint:
	$(RUN) ruff check . .agents/skills/verify-fact-finder/verify
	$(RUN) ruff format --check . .agents/skills/verify-fact-finder/verify

types:
	$(RUN) basedpyright
	$(RUN) basedpyright --project .agents/skills/verify-fact-finder

deps:
	$(RUN) deptry .

dead:
	$(RUN) vulture

boundaries:
	$(RUN) lint-imports

rules:
	$(RUN) ast-grep test --skip-snapshot-tests
	$(RUN) ast-grep scan --error

test:
	$(RUN) pytest --quiet -n auto --cov --cov-fail-under=95

workflows:
	$(RUN) zizmor --offline .github/workflows
	$(RUN) actionlint

secrets:
	gitleaks git --no-banner --redact

vulnerabilities:
	uv export --quiet --frozen --all-extras --all-groups --no-hashes --no-emit-project --output-file .audit-requirements.txt
	$(RUN) pip-audit --requirement .audit-requirements.txt --no-deps --disable-pip --progress-spinner off; status=$$?; rm -f .audit-requirements.txt; exit $$status
