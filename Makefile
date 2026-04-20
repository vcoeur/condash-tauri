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
CM_THEME_ONE_DARK_VERSION     := 6.1.2
ESBUILD_VERSION               := 0.24.0
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
	               @codemirror/language @codemirror/lang-yaml @codemirror/theme-one-dark; do \
	        echo "  - $$pkg"; \
	    done; \
	    echo ""; \
	    echo "======= codemirror LICENSE ======="; \
	    cat "$$WORK/node_modules/codemirror/LICENSE"; \
	} > "$$DEST/LICENSE"; \
	rm -rf "$$WORK"; \
	echo "Vendored CodeMirror 6:"; \
	du -sh "$$DEST"

.PHONY: help install dev-install run test coverage lint format update-pdfjs update-codemirror
