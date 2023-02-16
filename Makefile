SHELL=/bin/bash
DATETIME:=$(shell date -u +%Y%m%dT%H%M%SZ)

### Dependency commands ###

install: ## Install dependencies and CLI app
	pipenv install --dev

update: install ## Update all Python dependencies
	pipenv clean
	pipenv update --dev

### Test commands ###

test: ## Run tests and print a coverage report
	pipenv run coverage run --source=sapinvoices -m pytest -vv
	pipenv run coverage report -m

coveralls: test
	pipenv run coverage lcov -o ./coverage/lcov.info

### Code quality and safety commands ###

lint: bandit black mypy pylama safety ## Run linting, code quality, and safety checks

bandit:
	pipenv run bandit -r sapinvoices

black:
	pipenv run black --check --diff .

mypy:
	pipenv run mypy sapinvoices

pylama:
	pipenv run pylama --options setup.cfg

safety:
	pipenv check
	pipenv verify
