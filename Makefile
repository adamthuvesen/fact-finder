RUN := uv run --locked

.PHONY: check fix quick verify audit lock lint types deps dead boundaries rules test workflows secrets vulnerabilities

# Offline gate. CI runs the same targets.
check: lock lint types deps dead boundaries rules test

# Apply every auto-fixer: ruff lint fixes, then ruff format.
fix:
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

# Only what changed, in about two seconds. The edit hook runs the same script on one file.
quick:
	@sh .agents/hooks/report-edit.sh

# Drives the CLI installed from a wheel. ARGS: all, list, control, or drive names.
verify:
	$(RUN) python .agents/skills/verify-fact-finder/verify $(ARGS)

# Needs the network for the vulnerability database.
audit: workflows secrets vulnerabilities

lock:
	uv lock --check

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

types:
	$(RUN) basedpyright

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
