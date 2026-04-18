PYTHONPATH := $(shell pwd)

# Vendored Mozilla PDF.js version — bumped by `make update-pdfjs`. The
# live assets live under src/condash/assets/vendor/pdfjs/ (see app.py's
# /vendor/pdfjs route and dashboard.html's PDF.js ES module block).
PDFJS_VERSION := 5.6.205

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "%-16s %s\n", $$1, $$2}'

install: ## Install dependencies into a uv-managed venv
	uv sync

dev-install: ## Install dev dependencies too
	uv sync --all-extras

run: ## Run the condash CLI (pass args after --, e.g. make run -- init)
	uv run condash

test: ## Run pytest
	uv run pytest; RET=$$?; if [ $$RET -eq 5 ]; then exit 0; else exit $$RET; fi

coverage: ## Run pytest with line-coverage report
	uv run pytest --cov=condash --cov-report=term-missing --cov-report=html

lint: ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Ruff auto-fix + format
	uv run ruff check --fix .
	uv run ruff format .

update-pdfjs: ## Re-vendor Mozilla PDF.js at $(PDFJS_VERSION) into src/condash/assets/vendor/pdfjs/
	@set -e; \
	URL="https://github.com/mozilla/pdf.js/releases/download/v$(PDFJS_VERSION)/pdfjs-$(PDFJS_VERSION)-legacy-dist.zip"; \
	WORK=$$(mktemp -d); \
	DEST=src/condash/assets/vendor/pdfjs; \
	echo "Downloading $$URL"; \
	curl -sSL -o "$$WORK/pdfjs.zip" "$$URL"; \
	unzip -q "$$WORK/pdfjs.zip" -d "$$WORK/extracted"; \
	rm -rf "$$DEST"; \
	mkdir -p "$$DEST/build"; \
	cp "$$WORK/extracted/build/pdf.mjs" "$$WORK/extracted/build/pdf.worker.mjs" "$$DEST/build/"; \
	cp -r "$$WORK/extracted/web/cmaps" "$$WORK/extracted/web/standard_fonts" \
	      "$$WORK/extracted/web/wasm" "$$WORK/extracted/web/iccs" "$$DEST/"; \
	cp "$$WORK/extracted/LICENSE" "$$DEST/"; \
	find "$$DEST" -name '*.map' -delete; \
	rm -rf "$$WORK"; \
	echo "Vendored PDF.js $(PDFJS_VERSION):"; \
	du -sh "$$DEST"

.PHONY: help install dev-install run test coverage lint format update-pdfjs
