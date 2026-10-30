RUN := uv run --locked

.PHONY: check audit lock lint types deps dead test workflows secrets vulnerabilities

# Offline gate. CI runs the same targets.
check: lock lint types deps dead test

# Needs the network for the vulnerability database.
audit: workflows secrets vulnerabilities

lock:
	uv lock --check

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

types:
	$(RUN) basedpyright --level error

deps:
	$(RUN) deptry .

dead:
	$(RUN) vulture

test:
	$(RUN) pytest --quiet --cov --cov-fail-under=88

workflows:
	$(RUN) zizmor --offline .github/workflows
	$(RUN) actionlint

secrets:
	gitleaks git --no-banner --redact

vulnerabilities:
	uv export --quiet --frozen --all-extras --all-groups --no-hashes --no-emit-project --output-file .audit-requirements.txt
	$(RUN) pip-audit --requirement .audit-requirements.txt --no-deps --disable-pip --progress-spinner off; status=$$?; rm -f .audit-requirements.txt; exit $$status
