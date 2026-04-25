# Vendored Mozilla PDF.js version — bumped by `make update-pdfjs`. The
# live assets live under frontend/vendor/pdfjs/ and are embedded into
# the Tauri binary via rust-embed (see src-tauri/src/assets.rs).
PDFJS_VERSION := 5.6.205

# Vendored CodeMirror 6 pins — bumped by `make update-codemirror`. The
# live bundle is a single minified IIFE at
# frontend/vendor/codemirror/codemirror.min.js, built from
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
# frontend/vendor/mermaid/mermaid.min.js, loaded unconditionally by
# dashboard.html so the note preview modal can render mermaid code
# blocks offline.
MERMAID_VERSION               := 11.14.0

# Vendored xterm.js pins — bumped by `make update-xterm`. The xterm@5 line
# is the last under the unscoped name (v6+ moved to @xterm/xterm); we
# stay on 5.x until we have a reason to cross that break.
XTERM_VERSION                 := 5.3.0
XTERM_FIT_VERSION             := 0.8.0

# Vendored htmx version — bumped by `make update-htmx`. Drives the
# History pane's server-fragment refresh + SSE-driven re-render. Loaded
# unconditionally by dashboard.html alongside the SSE extension.
HTMX_VERSION                  := 2.0.4
HTMX_SSE_EXT_VERSION          := 2.2.3
IDIOMORPH_VERSION             := 0.7.4
# NOTE: state/view versions must match what @codemirror/lint and
# @codemirror/search (transitive deps of basicSetup) require at top
# level — otherwise npm nests a second copy and the bundle loads two
# @codemirror/state modules, which breaks CM's instanceof extension
# checks with "Unrecognized extension value in extension set".

# The rustup-managed toolchain at ~/.rustup/toolchains/*/bin is picked
# up explicitly because the user does not have ~/.cargo/bin on PATH.
# Once cargo-tauri is installed it lives under that same toolchain's
# bin dir, so the same prefix works.
RUSTUP_BIN := $(HOME)/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin
CARGO      := $(RUSTUP_BIN)/cargo

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "%-20s %s\n", $$1, $$2}'

setup: ## One-shot: install cargo-tauri CLI into the rustup toolchain
	# Prepend RUSTUP_BIN to PATH so cargo finds the rustup-managed rustc
	# (1.93+) instead of Ubuntu's /usr/bin/rustc (1.75), which is too old
	# for tauri-cli.
	PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) install tauri-cli --version '^2'

# AppImageKit's AppRun injects PYTHONHOME / LD_LIBRARY_PATH / APPDIR / …
# into every child process, including any shell launched from a condash
# terminal. That leak steers ld.so to the AppImage-bundled webkit at
# exec time (before condash's in-binary env scrub runs), and the
# bundled libwebkit2gtk resolves WebKitNetworkProcess via a broken
# relative libexec path. Unset the leaks here so `cargo tauri dev`
# links against the system webkit. Harmless when running from a
# non-AppImage shell. See projects/2026-04-22-condash-appimage-env-leak.
APPIMAGE_LEAK_VARS := APPDIR APPIMAGE APPIMAGE_UUID ARGV0 OWD \
    LD_LIBRARY_PATH XDG_DATA_DIRS GSETTINGS_SCHEMA_DIR \
    GIO_EXTRA_MODULES GDK_PIXBUF_MODULE_FILE GTK_PATH \
    GST_PLUGIN_SYSTEM_PATH GST_PLUGIN_SYSTEM_PATH_1_0 GST_PLUGIN_PATH \
    PYTHONHOME PYTHONPATH PERLLIB QT_PLUGIN_PATH

run: frontend ## Open the Tauri window against dashboard.html
	cd src-tauri && unset $(APPIMAGE_LEAK_VARS) && \
	    PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) tauri dev

serve: frontend ## Run the Rust HTTP server headless (no GUI deps needed). Override CONCEPTION= to point elsewhere.
	PATH="$(RUSTUP_BIN):$$PATH" CONDASH_CONCEPTION_PATH=$(CONCEPTION) \
	    $(CARGO) run -q --bin condash-serve

build: ## Bundle Tauri release artefacts (requires Linux system deps)
	cd src-tauri && PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) tauri build

check: check-inline-handlers ## cargo check across the workspace (fast, no codegen)
	PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) check --workspace

check-inline-handlers: ## Guard against inline named on*= handlers (data-* + addEventListener instead)
	@bash tools/check-inline-handlers.sh

test: ## Run cargo tests across the workspace
	PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) test --workspace

# Default fixture for `make smoke` — a self-contained conception tree
# under examples/ with one project per priority bucket. Override with
# CONDASH_SMOKE_FIXTURE=... if you need to point at a different tree.
SMOKE_FIXTURE ?= $(CURDIR)/examples/conception-demo
SMOKE_PORT    ?= 3911

smoke: frontend ## End-to-end Playwright smoke against condash-serve (boots cargo run, opens dashboard, asserts SSE + dispatch)
	@set -e; \
	cd tests/smoke; \
	NPM_CONFIG_CACHE="$${TMPDIR:-/tmp}/.npm-cache" npm install --no-audit --no-fund --loglevel=error; \
	NPM_CONFIG_CACHE="$${TMPDIR:-/tmp}/.npm-cache" npx --yes playwright install --with-deps chromium >/tmp/condash-smoke-pw-install.log 2>&1 || \
	    (echo "playwright install failed — see /tmp/condash-smoke-pw-install.log" >&2; exit 1); \
	CONDASH_SMOKE_PORT=$(SMOKE_PORT) \
	    CONDASH_SMOKE_FIXTURE=$(SMOKE_FIXTURE) \
	    CARGO=$(CARGO) \
	    npx --yes playwright test

format: ## cargo fmt across the workspace
	PATH="$(RUSTUP_BIN):$$PATH" $(CARGO) fmt --all

frontend: ## Bundle the dashboard source (frontend/src/) into dist/bundle.{js,css}
	@set -e; \
	SRC_JS=frontend/src/js/entry.js; \
	SRC_CSS=frontend/src/css/main.css; \
	DEST=frontend/dist; \
	mkdir -p "$$DEST"; \
	echo "Bundling $$SRC_JS → $$DEST/bundle.js (esbuild $(ESBUILD_VERSION))"; \
	NPM_CONFIG_CACHE="$${TMPDIR:-/tmp}/.npm-cache" npx --yes esbuild@$(ESBUILD_VERSION) \
	    "$$SRC_JS" \
	    --bundle --format=iife --global-name=Condash --target=es2019 \
	    --minify --sourcemap \
	    --outfile="$$DEST/bundle.js" --log-level=warning; \
	echo "Bundling $$SRC_CSS → $$DEST/bundle.css"; \
	NPM_CONFIG_CACHE="$${TMPDIR:-/tmp}/.npm-cache" npx --yes esbuild@$(ESBUILD_VERSION) \
	    "$$SRC_CSS" \
	    --bundle --target=es2019 \
	    --minify --sourcemap \
	    --external:'/vendor/*' \
	    --outfile="$$DEST/bundle.css" --log-level=warning; \
	echo "Frontend bundle:"; \
	du -sh "$$DEST"

CONCEPTION ?= $(HOME)/src/vcoeur/conception

update-pdfjs: ## Re-vendor Mozilla PDF.js at $(PDFJS_VERSION) into frontend/vendor/pdfjs/
	@set -e; \
	URL="https://github.com/mozilla/pdf.js/releases/download/v$(PDFJS_VERSION)/pdfjs-$(PDFJS_VERSION)-legacy-dist.zip"; \
	WORK=$$(mktemp -d); \
	DEST=frontend/vendor/pdfjs; \
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

update-codemirror: ## Re-vendor CodeMirror 6 into frontend/vendor/codemirror/
	@set -e; \
	WORK=$$(mktemp -d); \
	DEST=frontend/vendor/codemirror; \
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

update-mermaid: ## Re-vendor Mermaid at $(MERMAID_VERSION) into frontend/vendor/mermaid/
	@set -e; \
	URL="https://cdn.jsdelivr.net/npm/mermaid@$(MERMAID_VERSION)/dist/mermaid.min.js"; \
	DEST=frontend/vendor/mermaid; \
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

update-xterm: ## Re-vendor xterm.js at $(XTERM_VERSION) + xterm-addon-fit at $(XTERM_FIT_VERSION) into frontend/vendor/xterm/
	@set -e; \
	DEST=frontend/vendor/xterm; \
	rm -rf "$$DEST"; \
	mkdir -p "$$DEST/lib" "$$DEST/css"; \
	echo "Downloading xterm $(XTERM_VERSION) + xterm-addon-fit $(XTERM_FIT_VERSION)"; \
	curl -sSL -o "$$DEST/lib/xterm.min.js" \
	    "https://cdn.jsdelivr.net/npm/xterm@$(XTERM_VERSION)/lib/xterm.js"; \
	curl -sSL -o "$$DEST/lib/xterm-addon-fit.min.js" \
	    "https://cdn.jsdelivr.net/npm/xterm-addon-fit@$(XTERM_FIT_VERSION)/lib/xterm-addon-fit.js"; \
	curl -sSL -o "$$DEST/css/xterm.min.css" \
	    "https://cdn.jsdelivr.net/npm/xterm@$(XTERM_VERSION)/css/xterm.min.css"; \
	sed -i -e '/\/\/# sourceMappingURL=/d' "$$DEST/lib/xterm.min.js" "$$DEST/lib/xterm-addon-fit.min.js"; \
	sed -i -e 's|/\*# sourceMappingURL=[^*]*\*/||' "$$DEST/css/xterm.min.css"; \
	curl -sSL -o "$$DEST/LICENSE" \
	    "https://cdn.jsdelivr.net/npm/xterm@$(XTERM_VERSION)/LICENSE"; \
	echo "Vendored xterm $(XTERM_VERSION) + addon-fit $(XTERM_FIT_VERSION):"; \
	du -sh "$$DEST"

update-htmx: ## Re-vendor htmx + sse + idiomorph extensions into frontend/vendor/htmx/
	@set -e; \
	DEST=frontend/vendor/htmx; \
	rm -rf "$$DEST"; \
	mkdir -p "$$DEST"; \
	echo "Downloading htmx $(HTMX_VERSION) + sse ext $(HTMX_SSE_EXT_VERSION) + idiomorph $(IDIOMORPH_VERSION)"; \
	curl -sSL -o "$$DEST/htmx.min.js" \
	    "https://unpkg.com/htmx.org@$(HTMX_VERSION)/dist/htmx.min.js"; \
	curl -sSL -o "$$DEST/htmx-ext-sse.src.js" \
	    "https://unpkg.com/htmx-ext-sse@$(HTMX_SSE_EXT_VERSION)/sse.js"; \
	NPM_CONFIG_CACHE="$${TMPDIR:-/tmp}/.npm-cache" npx --yes esbuild@$(ESBUILD_VERSION) \
	    "$$DEST/htmx-ext-sse.src.js" --minify --target=es2019 --legal-comments=none \
	    --outfile="$$DEST/htmx-ext-sse.js" --log-level=warning; \
	rm "$$DEST/htmx-ext-sse.src.js"; \
	curl -sSL -o "$$DEST/idiomorph-ext.min.js" \
	    "https://unpkg.com/idiomorph@$(IDIOMORPH_VERSION)/dist/idiomorph-ext.min.js"; \
	{ \
	    echo "htmx $(HTMX_VERSION) + htmx-ext-sse $(HTMX_SSE_EXT_VERSION) — both BSD 2-Clause License"; \
	    echo "Idiomorph $(IDIOMORPH_VERSION) + htmx-ext-idiomorph (bundled in idiomorph-ext.min.js) — BSD 2-Clause License"; \
	    echo ""; \
	    echo "https://github.com/bigskysoftware/htmx"; \
	    echo "https://github.com/bigskysoftware/htmx-extensions/tree/main/src/sse"; \
	    echo "https://github.com/bigskysoftware/idiomorph"; \
	    echo ""; \
	    echo "Vendored from:"; \
	    echo "  https://unpkg.com/htmx.org@$(HTMX_VERSION)/dist/htmx.min.js"; \
	    echo "  https://unpkg.com/htmx-ext-sse@$(HTMX_SSE_EXT_VERSION)/sse.js"; \
	    echo "  https://unpkg.com/idiomorph@$(IDIOMORPH_VERSION)/dist/idiomorph-ext.min.js"; \
	} > "$$DEST/LICENSE"; \
	echo "Vendored htmx $(HTMX_VERSION):"; \
	du -sh "$$DEST"

# Vendored web fonts. The dashboard runs a single coherent family —
# Lexend — across everything UI. Lexend is engineered for reading
# speed (variable axes for inter-letter spacing); we ship the static
# weights we use. Hierarchy comes from weight + size, not from a
# secondary serif. Falls back to system sans if the woff2 files are
# absent.
#
# Source: @fontsource (npm), served by jsdelivr — same pattern as the
# CodeMirror / Mermaid / xterm vendoring above. SIL Open Font 1.1.
LEXEND_FONTSOURCE_VERSION := 5

update-fonts: ## Re-vendor Lexend woff2 weights into frontend/vendor/fonts/
	@set -e; \
	DEST=frontend/vendor/fonts; \
	rm -rf "$$DEST"; \
	mkdir -p "$$DEST"; \
	BASE_L="https://cdn.jsdelivr.net/npm/@fontsource/lexend@$(LEXEND_FONTSOURCE_VERSION)/files"; \
	echo "Downloading Lexend (latin, 300 + 400 + 500 + 600 + 700 + 800)"; \
	curl -sSLf -o "$$DEST/lexend-300-normal.woff2" "$$BASE_L/lexend-latin-300-normal.woff2"; \
	curl -sSLf -o "$$DEST/lexend-400-normal.woff2" "$$BASE_L/lexend-latin-400-normal.woff2"; \
	curl -sSLf -o "$$DEST/lexend-500-normal.woff2" "$$BASE_L/lexend-latin-500-normal.woff2"; \
	curl -sSLf -o "$$DEST/lexend-600-normal.woff2" "$$BASE_L/lexend-latin-600-normal.woff2"; \
	curl -sSLf -o "$$DEST/lexend-700-normal.woff2" "$$BASE_L/lexend-latin-700-normal.woff2"; \
	curl -sSLf -o "$$DEST/lexend-800-normal.woff2" "$$BASE_L/lexend-latin-800-normal.woff2"; \
	{ \
	    echo "Vendored web fonts — SIL Open Font License 1.1"; \
	    echo ""; \
	    echo "Lexend — https://fonts.google.com/specimen/Lexend"; \
	    echo "  Source: @fontsource/lexend@$(LEXEND_FONTSOURCE_VERSION) via jsdelivr"; \
	    echo "  Files:  lexend-{300,400,500,600,700,800}-normal.woff2"; \
	    echo ""; \
	    echo "Bumped via condash/Makefile — see LEXEND_FONTSOURCE_VERSION."; \
	} > "$$DEST/LICENSE"; \
	echo "Vendored fonts:"; \
	du -sh "$$DEST"

# MkDocs site build — the GitHub Action at .github/workflows/docs.yml
# pins mkdocs-material to this same version, so local builds match CI.
MKDOCS_MATERIAL_VERSION := 9.5.49

docs: ## Build the mkdocs-material site into ./site/ (matches .github/workflows/docs.yml)
	uv run --with "mkdocs-material==$(MKDOCS_MATERIAL_VERSION)" mkdocs build --strict

docs-serve: ## Live-reload preview of the mkdocs site on http://127.0.0.1:8000/
	uv run --with "mkdocs-material==$(MKDOCS_MATERIAL_VERSION)" mkdocs serve

docs-clean: ## Remove the generated ./site/ directory
	rm -rf site

.PHONY: help setup run serve build check test smoke format frontend docs docs-serve docs-clean update-pdfjs update-codemirror update-mermaid update-xterm update-htmx update-fonts
