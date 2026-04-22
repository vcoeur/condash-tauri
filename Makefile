PYTHONPATH := $(shell pwd)

# Vendored Mozilla PDF.js version — bumped by `make update-pdfjs`. The
# live assets live under src/condash/assets/vendor/pdfjs/ (see app.py's
# /vendor/pdfjs route and dashboard.html's PDF.js ES module block).
PDFJS_VERSION := 5.6.205

# Vendored CodeMirror 6 pins — bumped by `make update-codemirror`. The
# live bundle is a single minified IIFE at
# src/condash/assets/vendor/codemirror/codemirror.min.js, built from
# tools/codemirror-entry.js via esbuild. CM6 is deeply modular ESM;
# we ship one file so dashboard.html needs only one <script> tag and
# condash stays offline-first.
CODEMIRROR_VERSION            := 6.0.2
CM_STATE_VERSION              := 6.6.0
CM_VIEW_VERSION               := 6.41.1
CM_COMMANDS_VERSION           := 6.7.0
CM_LANGUAGE_VERSION           := 6.10.3
CM_LANG_YAML_VERSION          := 6.1.1
CM_LANG_MARKDOWN_VERSION      := 6.5.0
CM_THEME_ONE_DARK_VERSION     := 6.1.2
ESBUILD_VERSION               := 0.24.0

# Vendored Mermaid version — bumped by `make update-mermaid`. The live
# bundle is the upstream-published UMD file at
# src/condash/assets/vendor/mermaid/mermaid.min.js, served by app.py's
# /vendor/mermaid route and loaded unconditionally by dashboard.html
# so the note preview modal can render mermaid code blocks offline.
MERMAID_VERSION               := 11.14.0
# NOTE: state/view versions must match what @codemirror/lint and
# @codemirror/search (transitive deps of basicSetup) require at top
# level — otherwise npm nests a second copy and the bundle loads two
# @codemirror/state modules, which breaks CM's instanceof extension
# checks with "Unrecognized extension value in extension set".

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "%-16s %s\n", $$1, $$2}'

install: ## Install dependencies into a uv-managed venv
	uv sync

dev-install: ## Install dev dependencies too
	uv sync --all-extras

run: ## Run the condash CLI (pass args after --, e.g. make run -- init)
	uv run condash

# Rust + Tauri port (Phase 0). The rustup-managed toolchain at
# ~/.rustup/toolchains/*/bin is picked up explicitly because the user
# does not have ~/.cargo/bin on PATH. Once cargo-tauri is installed it
# lives under that same toolchain's bin dir, so the same prefix works.
RUSTUP_BIN := $(HOME)/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin
CARGO      := $(RUSTUP_BIN)/cargo

run-tauri: ## Phase 0 exit gate — open the Tauri window against dashboard.html with stub (404) API
	cd src-tauri && PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) tauri dev

build-tauri: ## Bundle Tauri release artefacts (requires Linux system deps)
	cd src-tauri && PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) tauri build

install-tauri-cli: ## One-shot: install cargo-tauri CLI into the rustup toolchain
	# Prepend RUSTUP_BIN to PATH so cargo finds the rustup-managed rustc
	# (1.93+) instead of Ubuntu's /usr/bin/rustc (1.75), which is too old
	# for tauri-cli.
	PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) install tauri-cli --version '^2'

test-rust: ## Run cargo tests across the workspace (condash-parser, src-tauri, …)
	PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) test --workspace

check-rust: ## cargo check across the workspace (fast, no codegen)
	PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) check --workspace

fmt-rust: ## cargo fmt across the workspace
	PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) fmt --all

# Phase 1 exit gate. Override CONCEPTION= to diff against a different tree.
CONCEPTION ?= $(HOME)/src/vcoeur/conception

diff-parser: diff-parser-per-readme diff-parser-collect diff-parser-fingerprints ## Run every parser-diff mode against the conception corpus

diff-parser-per-readme: ## Diff per-README parse output Rust-vs-Python (Phase 1 exit gate)
	PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) run -q -p condash-parser --bin parser-diff -- \
	    --conception $(CONCEPTION) \
	    --condash-src $(CURDIR)/src \
	    --driver $(CURDIR)/crates/condash-parser/tools/py_driver.py \
	    --python python3 \
	    --mode per-readme

diff-parser-collect: ## Diff collect_items + collect_knowledge Rust-vs-Python (Phase 2 slice 1 exit gate)
	PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) run -q -p condash-parser --bin parser-diff -- \
	    --conception $(CONCEPTION) \
	    --condash-src $(CURDIR)/src \
	    --driver $(CURDIR)/crates/condash-parser/tools/py_driver.py \
	    --python python3 \
	    --mode collect

diff-parser-fingerprints: ## Diff /check-updates fingerprints Rust-vs-Python (Phase 2 slice 2 exit gate)
	PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) run -q -p condash-parser --bin parser-diff -- \
	    --conception $(CONCEPTION) \
	    --condash-src $(CURDIR)/src \
	    --driver $(CURDIR)/crates/condash-parser/tools/py_driver.py \
	    --python python3 \
	    --mode fingerprints

test: ## Run the fast in-process pytest suite (skips tests/e2e/)
	uv run pytest; RET=$$?; if [ $$RET -eq 5 ]; then exit 0; else exit $$RET; fi

test-e2e: ## Run the Playwright browser smoke tests (uses system Chrome)
	uv run --extra e2e pytest tests/e2e -v; RET=$$?; if [ $$RET -eq 5 ]; then exit 0; else exit $$RET; fi

test-all: test test-e2e ## Run both suites

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
	cp -r "$$WORK/extracted/web/cmaps" "$$WORK/extracted/web/standard_fonts" \
	      "$$WORK/extracted/web/wasm" "$$WORK/extracted/web/iccs" "$$DEST/"; \
	cp "$$WORK/extracted/LICENSE" "$$DEST/"; \
	find "$$DEST" -name '*.map' -delete; \
	echo "Minifying pdf.mjs + pdf.worker.mjs via esbuild"; \
	NPM_CONFIG_CACHE="$${TMPDIR:-/tmp}/.npm-cache" npx --yes esbuild@$(ESBUILD_VERSION) \
	    "$$WORK/extracted/build/pdf.mjs" \
	    --bundle --minify --format=esm --target=es2022 --legal-comments=none \
	    --outfile="$$DEST/build/pdf.mjs" --log-level=warning; \
	NPM_CONFIG_CACHE="$${TMPDIR:-/tmp}/.npm-cache" npx --yes esbuild@$(ESBUILD_VERSION) \
	    "$$WORK/extracted/build/pdf.worker.mjs" \
	    --bundle --minify --format=esm --target=es2022 --legal-comments=none \
	    --outfile="$$DEST/build/pdf.worker.mjs" --log-level=warning; \
	rm -rf "$$WORK"; \
	echo "Vendored PDF.js $(PDFJS_VERSION) (minified):"; \
	du -sh "$$DEST"

update-codemirror: ## Re-vendor CodeMirror 6 into src/condash/assets/vendor/codemirror/
	@set -e; \
	WORK=$$(mktemp -d); \
	DEST=src/condash/assets/vendor/codemirror; \
	ENTRY=$$(pwd)/tools/codemirror-entry.js; \
	echo "Building CodeMirror bundle in $$WORK"; \
	python3 -c "import json; open('$$WORK/package.json','w').write(json.dumps({\
	 'name':'condash-cm-bundle','private':True,\
	 'dependencies':{\
	  'codemirror':'$(CODEMIRROR_VERSION)',\
	  '@codemirror/state':'$(CM_STATE_VERSION)',\
	  '@codemirror/view':'$(CM_VIEW_VERSION)',\
	  '@codemirror/commands':'$(CM_COMMANDS_VERSION)',\
	  '@codemirror/language':'$(CM_LANGUAGE_VERSION)',\
	  '@codemirror/lang-yaml':'$(CM_LANG_YAML_VERSION)',\
	  '@codemirror/lang-markdown':'$(CM_LANG_MARKDOWN_VERSION)',\
	  '@codemirror/theme-one-dark':'$(CM_THEME_ONE_DARK_VERSION)'},\
	 'devDependencies':{'esbuild':'$(ESBUILD_VERSION)'}},indent=2))"; \
	cp "$$ENTRY" "$$WORK/entry.js"; \
	( cd "$$WORK" && NPM_CONFIG_CACHE="$${TMPDIR:-/tmp}/.npm-cache" npm install --no-audit --no-fund --loglevel=error ); \
	( cd "$$WORK" && npx esbuild entry.js --bundle --minify --format=iife --target=es2019 \
	    --outfile=codemirror.min.js --log-level=warning ); \
	rm -rf "$$DEST"; \
	mkdir -p "$$DEST"; \
	cp "$$WORK/codemirror.min.js" "$$DEST/codemirror.min.js"; \
	{ \
	    echo "CodeMirror 6 vendored bundle — MIT"; \
	    echo ""; \
	    echo "Built from the following packages (version pins in condash/Makefile):"; \
	    for pkg in codemirror @codemirror/state @codemirror/view @codemirror/commands \
	               @codemirror/language @codemirror/lang-yaml @codemirror/lang-markdown \
	               @codemirror/theme-one-dark; do \
	        echo "  - $$pkg"; \
	    done; \
	    echo ""; \
	    echo "======= codemirror LICENSE ======="; \
	    cat "$$WORK/node_modules/codemirror/LICENSE"; \
	} > "$$DEST/LICENSE"; \
	rm -rf "$$WORK"; \
	echo "Vendored CodeMirror 6:"; \
	du -sh "$$DEST"

frontend: ## Bundle the dashboard source (src/condash/assets/src/) into dist/bundle.{js,css}
	@set -e; \
	SRC_JS=src/condash/assets/src/js/entry.js; \
	SRC_CSS=src/condash/assets/src/css/main.css; \
	DEST=src/condash/assets/dist; \
	mkdir -p "$$DEST"; \
	echo "Bundling $$SRC_JS → $$DEST/bundle.js (esbuild $(ESBUILD_VERSION))"; \
	NPM_CONFIG_CACHE="$${TMPDIR:-/tmp}/.npm-cache" npx --yes esbuild@$(ESBUILD_VERSION) \
	    "$$SRC_JS" \
	    --bundle --format=iife --global-name=Condash --target=es2019 \
	    --outfile="$$DEST/bundle.js" --log-level=warning; \
	echo "Bundling $$SRC_CSS → $$DEST/bundle.css"; \
	NPM_CONFIG_CACHE="$${TMPDIR:-/tmp}/.npm-cache" npx --yes esbuild@$(ESBUILD_VERSION) \
	    "$$SRC_CSS" \
	    --bundle --target=es2019 \
	    --outfile="$$DEST/bundle.css" --log-level=warning; \
	echo "Frontend bundle:"; \
	du -sh "$$DEST"

update-mermaid: ## Re-vendor Mermaid at $(MERMAID_VERSION) into src/condash/assets/vendor/mermaid/
	@set -e; \
	URL="https://cdn.jsdelivr.net/npm/mermaid@$(MERMAID_VERSION)/dist/mermaid.min.js"; \
	DEST=src/condash/assets/vendor/mermaid; \
	rm -rf "$$DEST"; \
	mkdir -p "$$DEST"; \
	echo "Downloading $$URL"; \
	curl -sSL -o "$$DEST/mermaid.min.js" "$$URL"; \
	{ \
	    echo "Mermaid $(MERMAID_VERSION) — MIT License"; \
	    echo "https://github.com/mermaid-js/mermaid"; \
	    echo ""; \
	    echo "Vendored from https://cdn.jsdelivr.net/npm/mermaid@$(MERMAID_VERSION)/dist/mermaid.min.js"; \
	} > "$$DEST/LICENSE"; \
	echo "Vendored Mermaid $(MERMAID_VERSION):"; \
	du -sh "$$DEST"

.PHONY: help install dev-install run test test-e2e test-all coverage lint format frontend update-pdfjs update-codemirror update-mermaid
