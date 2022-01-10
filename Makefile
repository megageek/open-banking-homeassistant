.PHONY: build
build:
	rm dist/* || true
	python setup.py sdist

.PHONY: isort
isort:
	isort ./custom_components/open_banking ./tests --check-only

.PHONY: black
black:
	black --check ./custom_components/open_banking ./tests

.PHONY: flake8
flake8:
	flake8 ./custom_components/open_banking ./tests

.PHONY: test
test:
	pytest -vv -x

.PHONY: ci
ci: isort black flake8 test

.PHONY: ci-fix
ci-fix:
	isort ./custom_components/open_banking ./tests
	black ./custom_components/open_banking ./tests

.PHONY: dev
dev:
	$(MAKE) ci-fix
	$(MAKE) ci

.PHONY: install-pip
install-pip:
	python -m pip install --upgrade pip==23.1 setuptools wheel

.PHONY: install-dev
install-dev: install-pip
	pip install -e ".[dev]"

.PHONY: install-publish
install-publish: install-pip
	pip install -e ".[publish]"

.PHONY: publish
publish: build
	twine upload --verbose dist/*

.PHONY: venv
venv:
	python3 -m venv .venv
	. .venv/bin/activate