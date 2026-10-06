SHELL := /bin/sh -e
IMAGE_NAME ?= app-bifrost
IMAGE_TAG ?= latest
CHART_DIR := charts/bifrost-app
PACKAGE_DIR := .apolo/src/apolo_apps_bifrost

.PHONY: all
all: lint test

.PHONY: test
test: test-unit test-helm test-chart

.PHONY: install setup
install setup:
	poetry config virtualenvs.in-project true
	poetry install --with dev
	poetry run pre-commit install;

.PHONY: format
format:
ifdef CI
	poetry run pre-commit run --all-files --show-diff-on-failure
else
	poetry run pre-commit run --all-files || poetry run pre-commit run --all-files
endif

.PHONY: lint
lint: format
	poetry run mypy .apolo

.PHONY: test-unit
test-unit:
	poetry run pytest -vvs --cov=.apolo --cov-report xml:.coverage.unit.xml .apolo/tests/unit

.PHONY: test-helm
test-helm:
	helm repo add bifrost https://maximhq.github.io/bifrost/helm-charts --force-update
	helm dependency build $(CHART_DIR)
	for values in $(CHART_DIR)/ci/*.yaml; do \
		helm lint $(CHART_DIR) -f $$values; \
		helm template bifrost $(CHART_DIR) -f $$values > /dev/null; \
	done

.PHONY: test-chart
test-chart:
	poetry run pytest -vv .apolo/tests/chart

.PHONY: build-hook-image
build-hook-image:
	docker build \
		-t $(IMAGE_NAME):latest \
		-f hooks.Dockerfile \
		.;

.PHONY: push-hook-image
push-hook-image:
	docker tag $(IMAGE_NAME):latest ghcr.io/neuro-inc/$(IMAGE_NAME):$(IMAGE_TAG)
	docker push ghcr.io/neuro-inc/$(IMAGE_NAME):$(IMAGE_TAG)

.PHONY: gen-types-schemas
gen-types-schemas:
	for schema in BifrostAppInputs BifrostAppOutputs; do \
		poetry run app-types dump-types-schema $(PACKAGE_DIR) "$$schema" "$(PACKAGE_DIR)/schemas/$$schema.json"; \
	done
