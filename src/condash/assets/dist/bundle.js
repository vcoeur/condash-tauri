var Condash = (() => {
  var __create = Object.create;
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __getProtoOf = Object.getPrototypeOf;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __require = /* @__PURE__ */ ((x) => typeof require !== "undefined" ? require : typeof Proxy !== "undefined" ? new Proxy(x, {
    get: (a, b) => (typeof require !== "undefined" ? require : a)[b]
  }) : x)(function(x) {
    if (typeof require !== "undefined") return require.apply(this, arguments);
    throw Error('Dynamic require of "' + x + '" is not supported');
  });
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
    // If the importer is in node compatibility mode or this is not an ESM
    // file that has been converted to a CommonJS file using a Babel-
    // compatible transform (i.e. "__esModule" has not been set), then set
    // "default" to the CommonJS "module.exports" for node compatibility.
    isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
    mod
  ));

  // src/condash/assets/src/js/dashboard-main.js
  function getPreferredTheme() {
    var saved = localStorage.getItem("dashboard-theme");
    if (saved) return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var icon = document.getElementById("theme-icon");
    var label = document.getElementById("theme-label");
    if (theme === "dark") {
      icon.innerHTML = "&#9790;";
      label.textContent = "Dark";
    } else {
      icon.innerHTML = "&#9788;";
      label.textContent = "Light";
    }
    if (window.CondashCM && typeof _cmViews === "object") {
      Object.keys(_cmViews).forEach(function(which) {
        var view = _cmViews[which];
        var ta = document.querySelector('#config-form textarea[data-yaml-file="' + which + '"]');
        var comp = ta && ta._cmThemeComp;
        if (view && comp) {
          view.dispatch({ effects: comp.reconfigure(_currentCmTheme()) });
        }
      });
    }
  }
  function toggleTheme() {
    var current = document.documentElement.getAttribute("data-theme") || "light";
    var next = current === "dark" ? "light" : "dark";
    localStorage.setItem("dashboard-theme", next);
    applyTheme(next);
  }
  applyTheme(getPreferredTheme());
  function _setField(form, name, value) {
    var el = form.elements[name];
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!value;
    else el.value = value == null ? "" : value;
  }
  function _listToLines(list) {
    return (list || []).join("\n");
  }
  function _reposToLines(entries) {
    return (entries || []).map(function(entry) {
      if (!entry || !entry.name) return "";
      var subs = entry.submodules || [];
      return subs.length ? entry.name + ": " + subs.join(", ") : entry.name;
    }).filter(function(s) {
      return s.length;
    }).join("\n");
  }
  function _setSlotFields(form, slotKey, slot) {
    var container = form.querySelector('[data-slot="' + slotKey + '"]');
    if (!container || !slot) return;
    container.querySelector('[data-field="label"]').value = slot.label || "";
    container.querySelector('[data-field="commands"]').value = _listToLines(slot.commands);
  }
  function switchConfigTab(name) {
    var tabs = document.querySelectorAll("#config-form .config-tab");
    tabs.forEach(function(t) {
      t.classList.toggle("active", t.getAttribute("data-config-tab") === name);
    });
    var panes = document.querySelectorAll("#config-form .config-tab-pane");
    panes.forEach(function(p) {
      p.classList.toggle("active", p.getAttribute("data-config-pane") === name);
    });
    var modal = document.querySelector("#config-modal .config-modal");
    if (modal) {
      modal.classList.toggle("config-modal-wide", name !== "general");
    }
  }
  function _setYamlSourceHint(elId, source, expected, label) {
    var el = document.getElementById(elId);
    if (!el) return;
    if (source) {
      el.innerHTML = "These fields are stored in <code>" + source + "</code>.";
    } else if (expected) {
      el.innerHTML = "These fields migrate to <code>" + expected + "</code> on the next Save.";
    } else {
      el.innerHTML = "Set a <code>conception_path</code> on the General tab to move these fields into <code>" + label + "</code>.";
    }
    el.style.display = "";
  }
  async function openConfigModal() {
    var modal = document.getElementById("config-modal");
    var form = document.getElementById("config-form");
    var errEl = document.getElementById("config-error");
    var warnEl = document.getElementById("config-restart-warning");
    errEl.style.display = "none";
    warnEl.style.display = "none";
    switchConfigTab("general");
    modal.style.display = "flex";
    try {
      var res = await fetch("/config");
      if (!res.ok) throw new Error("HTTP " + res.status);
      var cfg = await res.json();
      _setField(form, "conception_path", cfg.conception_path);
      _setField(form, "workspace_path", cfg.workspace_path);
      _setField(form, "worktrees_path", cfg.worktrees_path);
      _setField(form, "port", cfg.port);
      _setField(form, "native", cfg.native);
      form.elements["repositories_primary"].value = _reposToLines(cfg.repositories_primary);
      form.elements["repositories_secondary"].value = _reposToLines(cfg.repositories_secondary);
      var ow = cfg.open_with || {};
      _setSlotFields(form, "main_ide", ow.main_ide);
      _setSlotFields(form, "secondary_ide", ow.secondary_ide);
      _setSlotFields(form, "terminal", ow.terminal);
      form.elements["pdf_viewer"].value = _listToLines(cfg.pdf_viewer || []);
      var term = cfg.terminal || {};
      _setField(form, "terminal_shell", term.shell);
      _setField(form, "terminal_shortcut", term.shortcut);
      _setField(form, "terminal_screenshot_dir", term.screenshot_dir);
      _setField(form, "terminal_screenshot_paste_shortcut", term.screenshot_paste_shortcut);
      var resolvedNote = document.getElementById("term-shell-resolved");
      if (resolvedNote) {
        resolvedNote.textContent = term.resolved_shell ? "Currently resolved: " + term.resolved_shell : "";
      }
      var resolvedDirNote = document.getElementById("term-screenshot-dir-resolved");
      if (resolvedDirNote) {
        resolvedDirNote.textContent = term.resolved_screenshot_dir ? "Currently resolved: " + term.resolved_screenshot_dir : "";
      }
      form.dataset.loadedPort = String(cfg.port);
      form.dataset.loadedNative = String(cfg.native);
      _setYamlSourceHint(
        "config-repositories-source",
        cfg.repositories_yaml_source,
        cfg.repositories_yaml_expected_path,
        "config/repositories.yml"
      );
      _setYamlSourceHint(
        "config-preferences-source",
        cfg.preferences_yaml_source,
        cfg.preferences_yaml_expected_path,
        "config/preferences.yml"
      );
      _populateYamlEditor("repositories", cfg.repositories_yaml_body || "");
      _populateYamlEditor("preferences", cfg.preferences_yaml_body || "");
    } catch (e) {
      errEl.textContent = "Could not load config: " + e;
      errEl.style.display = "block";
    }
  }
  var _cmViews = {};
  function _populateYamlEditor(which, body, preserveDirty) {
    var ta = document.querySelector('#config-form textarea[data-yaml-file="' + which + '"]');
    if (!ta) return;
    var dirty = ta.classList.contains("config-yaml-dirty");
    if (preserveDirty && dirty) return;
    if (window.CondashCM) {
      _populateYamlEditorCM(which, ta, body);
      return;
    }
    ta.value = body;
    ta.dataset.pristine = body;
    ta.classList.remove("config-yaml-dirty");
    _setYamlStatus(which, "synced");
    if (!ta.dataset.boundInput) {
      ta.addEventListener("input", function() {
        var pristine = ta.dataset.pristine || "";
        if (ta.value !== pristine) {
          ta.classList.add("config-yaml-dirty");
          _setYamlStatus(which, "edited \u2014 unsaved");
        } else {
          ta.classList.remove("config-yaml-dirty");
          _setYamlStatus(which, "synced");
        }
      });
      ta.dataset.boundInput = "1";
    }
  }
  function _populateYamlEditorCM(which, ta, body) {
    var CM = window.CondashCM;
    var view = _cmViews[which];
    var themeComp = ta._cmThemeComp;
    if (!view) {
      ta.style.display = "none";
      themeComp = new CM.Compartment();
      ta._cmThemeComp = themeComp;
      var wrap = document.createElement("div");
      wrap.className = "config-yaml-editor config-yaml-cm";
      ta.parentNode.insertBefore(wrap, ta.nextSibling);
      var extensions = [
        CM.basicSetup,
        CM.yamlLang(),
        themeComp.of(_currentCmTheme()),
        CM.EditorView.updateListener.of(function(update) {
          if (!update.docChanged) return;
          ta.value = update.state.doc.toString();
          var pristine = ta.dataset.pristine || "";
          if (ta.value !== pristine) {
            ta.classList.add("config-yaml-dirty");
            wrap.classList.add("config-yaml-dirty");
            _setYamlStatus(which, "edited \u2014 unsaved");
          } else {
            ta.classList.remove("config-yaml-dirty");
            wrap.classList.remove("config-yaml-dirty");
            _setYamlStatus(which, "synced");
          }
        })
      ];
      try {
        view = new CM.EditorView({
          doc: body,
          extensions,
          parent: wrap
        });
        _cmViews[which] = view;
      } catch (err) {
        console.warn("[condash] CodeMirror mount failed for", which, err);
        ta.style.display = "";
        wrap.remove();
        return;
      }
    } else {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: body }
      });
      if (themeComp) {
        view.dispatch({ effects: themeComp.reconfigure(_currentCmTheme()) });
      }
    }
    ta.value = body;
    ta.dataset.pristine = body;
    ta.classList.remove("config-yaml-dirty");
    view.dom.classList.remove("config-yaml-dirty");
    _setYamlStatus(which, "synced");
  }
  function _currentCmTheme() {
    var theme = document.documentElement.getAttribute("data-theme") || "light";
    return theme === "dark" ? window.CondashCM.oneDark : [];
  }
  function _setYamlStatus(which, label) {
    var badge = document.querySelector('[data-yaml-status="' + which + '"]');
    if (badge) badge.textContent = label;
  }
  function _getDirtyYamlFile() {
    var dirtyTa = document.querySelector("#config-form textarea.config-yaml-editor.config-yaml-dirty");
    if (!dirtyTa) return null;
    return {
      file: dirtyTa.getAttribute("data-yaml-file"),
      body: dirtyTa.value
    };
  }
  function closeConfigModal() {
    document.getElementById("config-modal").style.display = "none";
  }
  function openAboutModal() {
    document.getElementById("about-modal").style.display = "flex";
  }
  function closeAboutModal() {
    document.getElementById("about-modal").style.display = "none";
  }
  document.addEventListener("click", function(ev) {
    var a = ev.target.closest && ev.target.closest("#about-modal a[data-about-link]");
    if (!a) return;
    ev.preventDefault();
    fetch("/open-external", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: a.getAttribute("href") })
    });
  });
  function _deriveSlug(title) {
    return (title || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  }
  function openNewItemModal() {
    var modal = document.getElementById("new-item-modal");
    var form = document.getElementById("new-item-form");
    if (!modal || !form) return;
    form.reset();
    document.getElementById("new-item-error").style.display = "none";
    var k = form.querySelector('input[name="kind"][value="project"]');
    if (k) k.checked = true;
    var s = form.querySelector('input[name="status"][value="now"]');
    if (s) s.checked = true;
    _syncNewItemKindFields();
    modal.style.display = "flex";
    setTimeout(function() {
      var title = document.getElementById("new-item-title");
      if (title) title.focus();
    }, 40);
  }
  function closeNewItemModal() {
    document.getElementById("new-item-modal").style.display = "none";
  }
  function _syncNewItemKindFields() {
    var form = document.getElementById("new-item-form");
    if (!form) return;
    var kindEl = form.querySelector('input[name="kind"]:checked');
    var kind = kindEl ? kindEl.value : "project";
    form.querySelectorAll("[data-kind-fields]").forEach(function(fs) {
      fs.style.display = fs.getAttribute("data-kind-fields") === kind ? "" : "none";
    });
  }
  (function _wireNewItemForm() {
    document.addEventListener("DOMContentLoaded", function() {
      var form = document.getElementById("new-item-form");
      if (!form) return;
      form.querySelectorAll('input[name="kind"]').forEach(function(el) {
        el.addEventListener("change", _syncNewItemKindFields);
      });
      var title = document.getElementById("new-item-title");
      var slug = document.getElementById("new-item-slug");
      if (title && slug) {
        slug.addEventListener("input", function() {
          slug.dataset.manual = "1";
        });
        title.addEventListener("input", function() {
          if (slug.dataset.manual === "1" && slug.value.trim() !== "") return;
          slug.value = _deriveSlug(title.value);
          delete slug.dataset.manual;
        });
      }
    });
  })();
  function openInTerminal(ev, path) {
    if (ev) {
      ev.stopPropagation();
      ev.preventDefault();
    }
    var pane = document.getElementById("term-pane");
    if (pane.hasAttribute("hidden")) {
      pane.removeAttribute("hidden");
      _termSyncOpenFlag(true);
      localStorage.setItem("term-open", "1");
    }
    var side = _termLastFocused === "right" ? "right" : "left";
    var basename = String(path).replace(/\/+$/, "").split("/").pop() || "";
    _termCreateTab(side, { cwd: path, customName: basename });
    setTimeout(function() {
      var tab = _termActiveTab();
      if (tab) {
        _termSendResize(tab);
        tab.term.focus();
      }
    }, 0);
  }
  function workOn(ev, slug) {
    if (ev) {
      ev.stopPropagation();
      ev.preventDefault();
    }
    var text = "work on " + slug;
    var active = _termActiveTab();
    if (active && active.ws && active.ws.readyState === WebSocket.OPEN) {
      active.ws.send(new TextEncoder().encode(text));
      active.term.focus();
      return;
    }
    var pane = document.getElementById("term-pane");
    if (pane.hasAttribute("hidden")) {
      pane.removeAttribute("hidden");
      _termSyncOpenFlag(true);
      localStorage.setItem("term-open", "1");
    }
    if (_termTabs.length === 0) _termCreateTab("left");
    var tries = 0;
    (function trySend() {
      var tab = _termActiveTab();
      if (tab && tab.ws && tab.ws.readyState === WebSocket.OPEN) {
        tab.ws.send(new TextEncoder().encode(text));
        tab.term.focus();
        return;
      }
      if (++tries < 40) setTimeout(trySend, 75);
    })();
  }
  async function openFolder(ev, relPath) {
    if (ev) {
      ev.stopPropagation();
      ev.preventDefault();
    }
    var btn = ev.currentTarget;
    var originalHtml = btn.innerHTML;
    btn.disabled = true;
    function restore() {
      btn.innerHTML = originalHtml;
      btn.classList.remove("is-ok", "is-err");
      btn.disabled = false;
    }
    function flash(cls, label, ms) {
      btn.classList.add(cls);
      btn.textContent = label;
      setTimeout(restore, ms);
    }
    try {
      var res = await fetch("/open-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: relPath })
      });
      if (!res.ok) {
        flash("is-err", "err", 1200);
        return;
      }
      flash("is-ok", "ok", 800);
    } catch (e) {
      flash("is-err", "err", 1200);
    }
  }
  function togglePriMenu(wrap) {
    var menu = wrap.querySelector(".pri-menu");
    var isOpen = menu.classList.contains("open");
    closePriMenus();
    if (!isOpen) menu.classList.add("open");
  }
  function closePriMenus() {
    document.querySelectorAll(".pri-menu.open").forEach(function(m) {
      m.classList.remove("open");
    });
  }
  function toggleCard(card) {
    card.classList.toggle("collapsed");
  }
  var PRI_ORDER = { now: 0, soon: 1, later: 2, backlog: 3, review: 4, done: 5 };
  function sortCards() {
    var ct = document.getElementById("cards");
    var items = [].slice.call(ct.querySelectorAll(":scope > .card, :scope > .group-heading"));
    items.sort(function(a, b) {
      var pa, pb, ha, hb;
      if (a.classList.contains("group-heading")) {
        pa = PRI_ORDER[a.getAttribute("data-group")];
        ha = 0;
      } else {
        pa = a.getAttribute("data-priority") in PRI_ORDER ? PRI_ORDER[a.getAttribute("data-priority")] : 9;
        ha = 1;
      }
      if (b.classList.contains("group-heading")) {
        pb = PRI_ORDER[b.getAttribute("data-group")];
        hb = 0;
      } else {
        pb = b.getAttribute("data-priority") in PRI_ORDER ? PRI_ORDER[b.getAttribute("data-priority")] : 9;
        hb = 1;
      }
      if (pa !== pb) return pa - pb;
      if (ha !== hb) return ha - hb;
      return b.id.slice(0, 10).localeCompare(a.id.slice(0, 10));
    });
    items.forEach(function(c) {
      ct.appendChild(c);
    });
  }
  var TAB_MAP = {
    current: ["now", "review"],
    next: ["soon", "later"],
    backlog: ["backlog"],
    done: ["done"]
  };
  var TAB_SHOWS_HEADINGS = { current: true, next: true };
  var PRIMARY_TABS = ["projects", "code", "knowledge", "history"];
  var SUBTABS = ["current", "next", "backlog", "done"];
  var _activeTab = "projects";
  var _activeSubtab = "current";
  var LEGACY_TAB_ALIAS = {
    current: ["projects", "current"],
    next: ["projects", "next"],
    backlog: ["projects", "backlog"],
    done: ["projects", "done"],
    knowledge: ["knowledge", null]
  };
  function _persistTabState() {
    var url = new URL(location.href);
    url.searchParams.set("tab", _activeTab);
    if (_activeTab === "projects") url.searchParams.set("sub", _activeSubtab);
    else url.searchParams.delete("sub");
    history.replaceState(null, "", url);
  }
  function switchTab(tab) {
    if (!PRIMARY_TABS.includes(tab)) tab = "projects";
    var clickedSameTab = tab === _activeTab;
    _deriveLegacyFlags();
    var clickedTabStale = (tab === "projects" || tab === "history") && _itemsStale || tab === "code" && _gitStale || tab === "knowledge" && _knowledgeStale;
    if (!clickedSameTab && clickedTabStale) {
      _activeTab = tab;
      _reloadInPlace();
      return;
    }
    _activeTab = tab;
    document.querySelectorAll(".tabs-primary .tab").forEach(function(t) {
      t.classList.toggle("active", t.getAttribute("data-tab") === tab);
    });
    document.getElementById("projects-pane").style.display = tab === "projects" ? "" : "none";
    document.getElementById("code-pane").style.display = tab === "code" ? "" : "none";
    document.getElementById("knowledge-pane").style.display = tab === "knowledge" ? "" : "none";
    document.getElementById("history-pane").style.display = tab === "history" ? "" : "none";
    document.getElementById("projects-subtabs").style.display = tab === "projects" ? "" : "none";
    if (tab === "projects") _applySubtab(_activeSubtab);
    _persistTabState();
    if (typeof _renderStale === "function") _renderStale();
  }
  function switchSubtab(sub) {
    if (!SUBTABS.includes(sub)) sub = "current";
    _activeSubtab = sub;
    _applySubtab(sub);
    _persistTabState();
  }
  function _applySubtab(sub) {
    document.querySelectorAll("#projects-subtabs .tab").forEach(function(t) {
      t.classList.toggle("active", t.getAttribute("data-subtab") === sub);
    });
    var allowed = TAB_MAP[sub] || [];
    document.querySelectorAll(".card").forEach(function(card) {
      card.classList.toggle("hidden", allowed.indexOf(card.getAttribute("data-priority")) === -1);
    });
    document.querySelectorAll(".group-heading").forEach(function(h) {
      var pri = h.getAttribute("data-group");
      var show = TAB_SHOWS_HEADINGS[sub] && allowed.indexOf(pri) !== -1;
      if (show) {
        var any = document.querySelector('.card[data-priority="' + pri + '"]');
        if (!any) show = false;
      }
      h.classList.toggle("hidden", !show);
    });
  }
  async function pickPriority(file, val, wrap) {
    closePriMenus();
    var card = wrap.closest(".card");
    var cur = wrap.querySelector(".pri-current");
    var res = await fetch("/set-priority", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file, priority: val })
    });
    if (!res.ok) return;
    var result = await res.json();
    if (result.moved) {
      _reloadInPlace();
      return;
    }
    cur.className = "pri-current pri-" + val;
    cur.textContent = val;
    card.setAttribute("data-priority", val);
    sortCards();
    switchTab(_activeTab);
    if (_activeTab === "projects") switchSubtab(_activeSubtab);
    updateTabCounts();
    updateBaseline();
  }
  document.addEventListener("click", function(e) {
    if (!e.target.closest(".pri-wrap")) closePriMenus();
  });
  var _reloadInPlaceInFlight = false;
  var _reloadInPlacePending = false;
  async function _reloadInPlace() {
    if (_reloadInPlaceInFlight) {
      _reloadInPlacePending = true;
      return;
    }
    _reloadInPlaceInFlight = true;
    try {
      var prefetched = _consumeShadowCache();
      var html = prefetched;
      if (!html) {
        var res = await fetch("/", { cache: "no-store" });
        if (!res.ok) {
          location.reload();
          return;
        }
        html = await res.text();
      }
      var fresh = new DOMParser().parseFromString(html, "text/html").getElementById("dash-main");
      var current = document.getElementById("dash-main");
      if (!fresh || !current) {
        location.reload();
        return;
      }
      var result = focusSafeSwap(current, fresh);
      if (result.skipped) {
        _pendingReloadInPlace = true;
        return;
      }
      _dirtyNodes = /* @__PURE__ */ new Set();
      _rebindDashHandlers();
    } catch (e) {
      location.reload();
    } finally {
      _reloadInPlaceInFlight = false;
      if (_reloadInPlacePending) {
        _reloadInPlacePending = false;
        _reloadInPlace();
      }
    }
  }
  var _shadowCache = null;
  async function _refreshShadowCache() {
    if (_shadowCache && _shadowCache.inflight) return;
    _shadowCache = { inflight: true };
    try {
      var res = await fetch("/", { cache: "no-store" });
      if (!res.ok) {
        _shadowCache = null;
        return;
      }
      var html = await res.text();
      _shadowCache = { html, at: Date.now() };
    } catch (e) {
      _shadowCache = null;
    }
  }
  function _consumeShadowCache() {
    if (!_shadowCache || _shadowCache.inflight || !_shadowCache.html) return null;
    var html = _shadowCache.html;
    _shadowCache = null;
    return html;
  }
  function _tabForNodeId(id) {
    if (id === "projects" || id.indexOf("projects/") === 0) return "projects";
    if (id === "code" || id.indexOf("code/") === 0) return "code";
    if (id === "knowledge" || id.indexOf("knowledge/") === 0) return "knowledge";
    return null;
  }
  function _rebindDashHandlers() {
    switchTab(_activeTab);
    if (_activeTab === "projects") switchSubtab(_activeSubtab);
    updateTabCounts();
    updateBaseline();
    _reapplySearches();
    restoreNotesTreeState();
  }
  document.addEventListener("DOMContentLoaded", function() {
    var params = new URLSearchParams(location.search);
    var tab = params.get("tab") || "";
    var sub = params.get("sub") || "";
    var alias = LEGACY_TAB_ALIAS[tab];
    if (alias) {
      tab = alias[0];
      sub = alias[1] || sub;
    }
    if (tab === "projects" && sub === "history") {
      tab = "history";
      sub = "";
    }
    if (PRIMARY_TABS.indexOf(tab) === -1) tab = "projects";
    if (tab === "projects" && SUBTABS.indexOf(sub) !== -1) _activeSubtab = sub;
    switchTab(tab);
    restoreNotesTreeState();
    _restorePreservedSearches();
  });
  function _restorePreservedSearches() {
    var mapping = {
      "condash.search.knowledge": { id: "knowledge-search", fn: "filterKnowledge" },
      "condash.search.history": { id: "history-search", fn: "filterHistory" }
    };
    Object.keys(mapping).forEach(function(key) {
      var raw = null;
      try {
        raw = sessionStorage.getItem(key);
      } catch (e) {
        return;
      }
      if (!raw) return;
      var payload;
      try {
        payload = JSON.parse(raw);
      } catch (e) {
        return;
      }
      if (!payload || payload.value == null || payload.value === "") return;
      var input = document.getElementById(mapping[key].id);
      if (!input) return;
      input.value = payload.value;
      if (typeof window[mapping[key].fn] === "function") {
        window[mapping[key].fn](payload.value);
      }
    });
  }
  var _NOTES_OPEN_KEY = "condash:notes-open:";
  function restoreNotesTreeState() {
    document.querySelectorAll(".notes-group[data-subdir-key]").forEach(function(d) {
      var key = d.getAttribute("data-subdir-key");
      var saved = null;
      try {
        saved = localStorage.getItem(_NOTES_OPEN_KEY + key);
      } catch (e) {
      }
      d.open = saved === "open";
    });
  }
  document.addEventListener("toggle", function(ev) {
    var target = ev.target;
    if (!target || !target.classList || !target.classList.contains("notes-group")) return;
    var key = target.getAttribute("data-subdir-key");
    if (!key) return;
    try {
      localStorage.setItem(_NOTES_OPEN_KEY + key, target.open ? "open" : "closed");
    } catch (e) {
    }
  }, true);
  function _cardNodeIdFor(readmePath) {
    var parts = (readmePath || "").split("/");
    if (parts.length < 4) return null;
    var slug = parts[2];
    var card = document.getElementById(slug);
    return card ? card.getAttribute("data-node-id") : null;
  }
  function uploadToNotes(readmePath, subdirRelToItem) {
    var input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.style.display = "none";
    document.body.appendChild(input);
    input.addEventListener("change", async function() {
      if (!input.files || !input.files.length) {
        document.body.removeChild(input);
        return;
      }
      var fd = new FormData();
      fd.append("item_readme", readmePath);
      if (subdirRelToItem) fd.append("subdir", subdirRelToItem);
      for (var i = 0; i < input.files.length; i++) {
        fd.append("file", input.files[i], input.files[i].name);
      }
      try {
        var res = await fetch("/note/upload", { method: "POST", body: fd });
        var data = await res.json().catch(function() {
          return {};
        });
        if (!res.ok) {
          alert("Upload failed: " + (data.reason || data.error || "HTTP " + res.status));
          return;
        }
        if ((data.rejected || []).length) {
          alert("Some files were rejected:\n" + data.rejected.map(function(r) {
            return "  " + (r.filename || "?") + ": " + r.reason;
          }).join("\n"));
        }
        if (subdirRelToItem) {
          var parts = readmePath.split("/");
          if (parts.length >= 4) {
            var slug = parts[2];
            try {
              localStorage.setItem(_NOTES_OPEN_KEY + slug + "/" + subdirRelToItem, "open");
            } catch (e) {
            }
          }
        }
        var nodeId = _cardNodeIdFor(readmePath);
        if (nodeId) reloadNode(nodeId);
        else _reloadInPlace();
      } catch (e) {
        alert("Network error: " + e);
      } finally {
        document.body.removeChild(input);
      }
    });
    input.click();
  }
  async function createNotesSubdir(readmePath, parentRelToItem) {
    var promptLabel = parentRelToItem ? "New subdirectory inside " + parentRelToItem + "/ (e.g. drafts):" : "New folder at the item root (sibling of notes/, e.g. drawings):";
    var raw = prompt(promptLabel, "");
    if (!raw) return;
    raw = raw.trim().replace(/^\/+|\/+$/g, "");
    if (!raw) return;
    if (!/^[\w.-]+(\/[\w.-]+)*$/.test(raw)) {
      alert('Invalid name: only letters, digits, dot, dash, underscore, and "/" for nesting.');
      return;
    }
    var subpath = parentRelToItem ? parentRelToItem + "/" + raw : raw;
    try {
      var res = await fetch("/note/mkdir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_readme: readmePath, subpath })
      });
      var data = await res.json().catch(function() {
        return {};
      });
      if (!res.ok) {
        var msg = data.reason === "exists" ? "A folder with that name already exists." : data.reason || data.error || "HTTP " + res.status;
        alert("Could not create folder: " + msg);
        return;
      }
      if (data.subdir_key) {
        try {
          localStorage.setItem(_NOTES_OPEN_KEY + data.subdir_key, "open");
        } catch (e) {
        }
      }
      var nodeId = _cardNodeIdFor(readmePath);
      if (nodeId) reloadNode(nodeId);
      else _reloadInPlace();
    } catch (e) {
      alert("Network error: " + e);
    }
  }
  function updateTabCounts() {
    var projectsCount = document.querySelectorAll("#cards .card").length;
    var projectsTab = document.querySelector('.tabs-primary .tab[data-tab="projects"] .tab-count');
    if (projectsTab) projectsTab.textContent = "(" + projectsCount + ")";
    document.querySelectorAll("#projects-subtabs .tab").forEach(function(t) {
      var tab = t.getAttribute("data-subtab");
      var allowed = TAB_MAP[tab] || [];
      var count = [].slice.call(document.querySelectorAll(".card")).filter(function(c) {
        return allowed.indexOf(c.getAttribute("data-priority")) !== -1;
      }).length;
      var span = t.querySelector(".tab-count");
      if (span) span.textContent = "(" + count + ")";
    });
  }
  function _searchTokens(q) {
    q = (q || "").trim().toLowerCase();
    if (!q) return [];
    return q.split(/\s+/);
  }
  function _cardMatches(el, tokens) {
    if (tokens.length === 0) return true;
    var hay = (el.textContent || "").toLowerCase();
    for (var i = 0; i < tokens.length; i++) {
      if (hay.indexOf(tokens[i]) === -1) return false;
    }
    return true;
  }
  function _setEmpty(panel, cls, text) {
    var el = panel.querySelector("." + cls);
    if (text == null) {
      if (el) el.remove();
      return;
    }
    if (!el) {
      el = document.createElement("p");
      el.className = cls;
      panel.appendChild(el);
    }
    el.textContent = text;
  }
  var _historySearchQ = "";
  var _knowledgeSearchQ = "";
  function _escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function _escapeRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  function _buildSnippet(text, tokens, radius) {
    if (!tokens.length || !text) return "";
    var hay = text.toLowerCase();
    var pos = -1, hitLen = 0;
    for (var i = 0; i < tokens.length; i++) {
      var p = hay.indexOf(tokens[i]);
      if (p >= 0 && (pos < 0 || p < pos)) {
        pos = p;
        hitLen = tokens[i].length;
      }
    }
    if (pos < 0) return "";
    var start = Math.max(0, pos - radius);
    var end = Math.min(text.length, pos + hitLen + radius);
    if (start > 0) {
      var ws = text.lastIndexOf(" ", start);
      if (ws >= 0 && start - ws < 20) start = ws + 1;
    }
    if (end < text.length) {
      var we = text.indexOf(" ", end);
      if (we >= 0 && we - end < 20) end = we;
    }
    var frag = text.substring(start, end).replace(/\s+/g, " ").trim();
    var html = _escapeHtml(frag);
    var re = new RegExp("(" + tokens.map(_escapeRegExp).join("|") + ")", "gi");
    html = html.replace(re, "<mark>$1</mark>");
    return (start > 0 ? "\u2026" : "") + html + (end < text.length ? "\u2026" : "");
  }
  function _setSnippet(card, tokens) {
    var existing = card.querySelector(":scope > .match-snippet");
    if (tokens.length === 0) {
      if (existing) existing.remove();
      return;
    }
    var titleEl = card.querySelector(":scope > .knowledge-title");
    var titleText = titleEl ? titleEl.textContent : "";
    var full = card.textContent || "";
    var body = titleText && full.indexOf(titleText) === 0 ? full.substring(titleText.length) : full;
    var html = _buildSnippet(body, tokens, 60);
    if (!html) {
      if (existing) existing.remove();
      return;
    }
    if (!existing) {
      existing = document.createElement("div");
      existing.className = "match-snippet";
      card.appendChild(existing);
    }
    existing.innerHTML = html;
  }
  function _filterTree(panel, tokens, qTrim, emptyCls, emptyMsg) {
    var groups = panel.querySelectorAll(".knowledge-group");
    var cards = panel.querySelectorAll(".knowledge-card");
    if (tokens.length === 0) {
      groups.forEach(function(g) {
        g.style.display = "";
      });
      cards.forEach(function(c) {
        c.style.display = "";
        _setSnippet(c, tokens);
      });
      _setEmpty(panel, emptyCls, null);
      return;
    }
    groups.forEach(function(g) {
      g.style.display = "none";
    });
    var totalVisible = 0;
    cards.forEach(function(c) {
      var match = _cardMatches(c, tokens);
      c.style.display = match ? "" : "none";
      _setSnippet(c, match ? tokens : []);
      if (!match) return;
      totalVisible += 1;
      var anc = c.parentElement;
      while (anc && anc !== panel) {
        if (anc.classList && anc.classList.contains("knowledge-group")) {
          anc.style.display = "";
          anc.setAttribute("open", "");
        }
        anc = anc.parentElement;
      }
    });
    _setEmpty(panel, emptyCls, totalVisible === 0 ? emptyMsg : null);
  }
  function filterKnowledge(q) {
    _knowledgeSearchQ = q || "";
    _persistSearch("condash.search.knowledge", _knowledgeSearchQ);
    var panel = document.getElementById("knowledge");
    if (!panel) return;
    var qTrim = (q || "").trim();
    _filterTree(
      panel,
      _searchTokens(q),
      qTrim,
      "knowledge-empty",
      'No knowledge pages match "' + qTrim + '".'
    );
  }
  function _persistSearch(key, value) {
    try {
      if (!value) sessionStorage.removeItem(key);
      else sessionStorage.setItem(key, JSON.stringify({ value }));
    } catch (e) {
    }
  }
  var _historySearchTimer = null;
  var _historySearchAbort = null;
  function filterHistory(q) {
    _historySearchQ = q || "";
    _persistSearch("condash.search.history", _historySearchQ);
    var pane = document.getElementById("history-pane");
    var tree = document.getElementById("history");
    var results = document.getElementById("history-results");
    if (!pane || !tree || !results) return;
    var qTrim = _historySearchQ.trim();
    if (!qTrim) {
      if (_historySearchTimer) {
        clearTimeout(_historySearchTimer);
        _historySearchTimer = null;
      }
      if (_historySearchAbort) {
        _historySearchAbort.abort();
        _historySearchAbort = null;
      }
      pane.classList.remove("history-pane--query");
      results.hidden = true;
      results.innerHTML = "";
      tree.hidden = false;
      return;
    }
    pane.classList.add("history-pane--query");
    tree.hidden = true;
    results.hidden = false;
    if (_historySearchTimer) clearTimeout(_historySearchTimer);
    _historySearchTimer = setTimeout(function() {
      _runHistorySearch(qTrim);
    }, 150);
  }
  async function _runHistorySearch(q) {
    if (_historySearchAbort) _historySearchAbort.abort();
    _historySearchAbort = new AbortController();
    var results = document.getElementById("history-results");
    if (!results) return;
    try {
      var res = await fetch(
        "/search-history?q=" + encodeURIComponent(q),
        { signal: _historySearchAbort.signal }
      );
      if (!res.ok) throw new Error("HTTP " + res.status);
      var hits = await res.json();
      if (_historySearchQ.trim() !== q) return;
      _renderHistoryResults(hits, q);
    } catch (err) {
      if (err && err.name === "AbortError") return;
      results.innerHTML = '<p class="history-empty">Search failed: ' + _escapeHtml(String(err && err.message || err)) + "</p>";
    }
  }
  function _renderHistoryResults(hits, q) {
    var results = document.getElementById("history-results");
    if (!results) return;
    if (!hits || !hits.length) {
      results.innerHTML = '<p class="history-empty">No projects match "' + _escapeHtml(q) + '".</p>';
      return;
    }
    var out = [];
    for (var i = 0; i < hits.length; i++) {
      out.push(_historyResultBlock(hits[i]));
    }
    results.innerHTML = out.join("");
  }
  function _historyResultBlock(row) {
    var hitsHtml = "";
    for (var i = 0; i < row.hits.length; i++) {
      var h = row.hits[i];
      var pathAttr = _escapeHtml(h.path || "");
      var labelAttr = _escapeHtml(h.label || "");
      var snippetHtml = h.snippet || "";
      hitsHtml += '<li class="history-hit" data-path="' + pathAttr + '" data-label="' + labelAttr + '" onclick="_openHistoryHit(this)"><span class="hit-src hit-src-' + _escapeHtml(h.source) + '">' + _escapeHtml(h.label || h.source) + '</span><span class="hit-snippet">' + snippetHtml + "</span></li>";
    }
    return '<div class="history-result" data-slug="' + _escapeHtml(row.slug) + '" data-status="' + _escapeHtml(row.status || "") + '" data-subtab="' + _escapeHtml(row.subtab || "current") + '"><div class="history-result-header"><span class="history-result-title">' + _escapeHtml(row.title) + '</span><span class="pill">' + _escapeHtml(row.kind) + '</span><span class="pill pri-' + _escapeHtml(row.status) + '">' + _escapeHtml(row.status) + '</span><span class="history-result-month">' + _escapeHtml(row.month) + '</span><button class="history-jump" onclick="jumpToProject(this)" title="Open in Projects tab" aria-label="Jump to project"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/></svg></button></div><ul class="history-result-hits">' + hitsHtml + "</ul></div>";
  }
  function _openHistoryHit(el) {
    var path = el.getAttribute("data-path");
    var label = el.getAttribute("data-label");
    if (path) openNotePreview(path, label || path);
  }
  function jumpToProject(btn) {
    var row = btn.closest(".history-result");
    if (!row) return;
    var slug = row.getAttribute("data-slug");
    var sub = row.getAttribute("data-subtab") || "current";
    switchTab("projects");
    switchSubtab(sub);
    var card = document.getElementById(slug);
    if (!card) return;
    card.classList.remove("collapsed");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.remove("focus-flash");
    void card.offsetWidth;
    card.classList.add("focus-flash");
    setTimeout(function() {
      card.classList.remove("focus-flash");
    }, 1800);
  }
  function _reapplySearches() {
    if (_historySearchQ) {
      var h = document.getElementById("history-search");
      if (h) h.value = _historySearchQ;
      filterHistory(_historySearchQ);
    }
    if (_knowledgeSearchQ) {
      var k = document.getElementById("knowledge-search");
      if (k) k.value = _knowledgeSearchQ;
      filterKnowledge(_knowledgeSearchQ);
    }
  }
  function toggleSection(el) {
    var items = el.nextElementSibling;
    if (items.style.display === "none") {
      items.style.display = "block";
      el.classList.add("open");
    } else {
      items.style.display = "none";
      el.classList.remove("open");
    }
  }
  function _renderMermaidIn(container) {
    if (!window.mermaid) return;
    var blocks = container.querySelectorAll("pre.mermaid, pre > code.language-mermaid");
    if (!blocks.length) return;
    var nodes = [];
    blocks.forEach(function(block) {
      var pre = block.tagName === "PRE" ? block : block.parentElement;
      var code = pre.querySelector("code") || pre;
      var src = code.textContent;
      var div = document.createElement("div");
      div.className = "mermaid";
      div.textContent = src;
      pre.replaceWith(div);
      nodes.push(div);
    });
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    try {
      window.mermaid.initialize({
        startOnLoad: false,
        theme: isDark ? "dark" : "default",
        securityLevel: "strict"
      });
      window.mermaid.run({ nodes }).catch(function() {
      });
    } catch (e) {
    }
  }
  function _mountPdfsIn(container) {
    if (!container) return;
    var hosts = container.querySelectorAll(".note-pdf-host");
    for (var i = 0; i < hosts.length; i++) {
      var host = hosts[i];
      if (host.dataset.mounted === "1") continue;
      if (window.__pdfjs && window.__pdfjs.ready) {
        window.__pdfjs.mount(host);
      } else if (window.__pdfjs && window.__pdfjs.error) {
        host.innerHTML = '<div class="pdf-error">PDF viewer failed to load.</div>';
      } else {
        host.dataset.pdfPending = "1";
        host.innerHTML = '<div class="pdf-loading">Loading PDF viewer\u2026</div>';
      }
    }
  }
  var _noteNavStack = [];
  var _noteModal = {
    path: null,
    editable: false,
    // false when kind is pdf/image/binary — edit modes disabled
    kind: null,
    // from /note-raw
    mtime: null,
    renderedHtml: "",
    // last server render shown in the view pane
    /* Canonical text shared between CM6 and the plain textarea. Updated
       whenever the user switches away from an edit mode so the other
       mode can start from the same buffer. Reset on open and on save. */
    text: "",
    /* Which edit mode was last active. Ctrl-E from view returns here. */
    lastEditMode: "cm",
    /* Unsaved-changes flag. Set on every CM6/textarea edit, cleared on
       open and successful save. Drives the Save button's disabled state
       and the close/beforeunload confirms. */
    dirty: false
  };
  function _setDirty(value) {
    var next = !!value;
    if (_noteModal.dirty === next) return;
    _noteModal.dirty = next;
    _syncSaveButton();
    if (!next && typeof _flushPendingReloads === "function") {
      _flushPendingReloads();
    }
  }
  function _syncSaveButton() {
    var btn = document.getElementById("note-save-btn");
    if (!btn) return;
    var inner = document.getElementById("note-modal-inner");
    var mode = inner ? inner.getAttribute("data-mode") : "view";
    var editing = mode === "cm" || mode === "plain";
    btn.disabled = !editing || !_noteModal.editable || !_noteModal.dirty;
    btn.title = btn.disabled && editing && _noteModal.editable ? "No unsaved changes" : "Save (Ctrl+S)";
  }
  async function openNotePreview(path, name) {
    var modal = document.getElementById("note-modal");
    var inner = document.getElementById("note-modal-inner");
    var title = document.getElementById("note-modal-title");
    var viewPane = document.getElementById("note-pane-view");
    var ta = document.getElementById("note-edit-textarea");
    noteSearchClose();
    _destroyCm();
    title.textContent = name;
    _noteModal.path = path;
    _noteModal.editable = false;
    _noteModal.kind = null;
    _noteModal.mtime = null;
    _noteModal.text = "";
    _noteModal.renderedHtml = "";
    _noteModal.dirty = false;
    _noteShowExternalBanner(false);
    _noteReconcileSuppressedUntilMtime = null;
    ta.value = "";
    viewPane.innerHTML = '<p class="note-loading">Loading\u2026</p>';
    _setNoteModeAttr(inner, "view");
    _syncModeControls();
    _hideSaveError();
    modal.classList.add("open");
    var viewP = fetch("/note?path=" + encodeURIComponent(path)).then(function(res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.text();
    });
    var rawP = fetch("/note-raw?path=" + encodeURIComponent(path)).then(function(res) {
      if (!res.ok) return null;
      return res.json();
    }).catch(function() {
      return null;
    });
    try {
      var html = await viewP;
      if (_noteModal.path !== path) return;
      viewPane.innerHTML = html;
      viewPane.scrollTop = 0;
      _noteModal.renderedHtml = html;
      _renderMermaidIn(viewPane);
      _wireNoteLinks(viewPane, path);
      _mountPdfsIn(viewPane);
    } catch (e) {
      if (_noteModal.path !== path) return;
      viewPane.innerHTML = '<p class="note-error">Failed to load note.</p>';
    }
    var raw = await rawP;
    if (_noteModal.path !== path) return;
    if (raw && typeof raw.content === "string") {
      _noteModal.editable = true;
      _noteModal.kind = raw.kind || null;
      _noteModal.mtime = raw.mtime != null ? Number(raw.mtime) : null;
      _noteModal.text = raw.content;
      ta.value = raw.content;
    }
    _syncModeControls();
    _syncNoteBack();
  }
  async function _navigateToNote(path, name, anchor) {
    if (_noteModal.path) {
      var titleEl = document.getElementById("note-modal-title");
      var currentName = titleEl ? titleEl.textContent : _noteModal.path;
      _noteNavStack.push({ path: _noteModal.path, name: currentName });
    }
    await openNotePreview(path, name);
    if (anchor) _scrollNoteToAnchor(anchor);
  }
  function _syncNoteBack() {
    var btn = document.getElementById("note-modal-back");
    if (!btn) return;
    if (_noteNavStack.length > 0) btn.removeAttribute("hidden");
    else btn.setAttribute("hidden", "");
  }
  async function noteNavBack() {
    if (_noteNavStack.length === 0) return;
    var entry = _noteNavStack.pop();
    await openNotePreview(entry.path, entry.name);
  }
  function _resolveNotePath(baseDir, rel) {
    if (rel.startsWith("/")) rel = rel.replace(/^\/+/, "");
    var parts = ((baseDir ? baseDir + "/" : "") + rel).split("/");
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (!p || p === ".") continue;
      if (p === "..") out.pop();
      else out.push(p);
    }
    return out.join("/");
  }
  function _scrollNoteToAnchor(anchor) {
    if (!anchor) return;
    var pane = document.getElementById("note-pane-view");
    if (!pane) return;
    var el = null;
    try {
      el = pane.querySelector("#" + CSS.escape(anchor));
    } catch (_) {
    }
    if (el) el.scrollIntoView({ block: "start" });
  }
  function _wireNoteLinks(body, notePath) {
    var noteDir = notePath.lastIndexOf("/") >= 0 ? notePath.substring(0, notePath.lastIndexOf("/")) : "";
    body.querySelectorAll("a.wikilink[href]").forEach(function(a) {
      a.addEventListener("click", function(ev) {
        ev.preventDefault();
        var href = a.getAttribute("href");
        var label = a.textContent || href;
        _navigateToNote(href, label);
      });
    });
    body.querySelectorAll("a.wikilink-missing").forEach(function(a) {
      a.addEventListener("click", function(ev) {
        ev.preventDefault();
      });
    });
    body.querySelectorAll("a[href]:not(.wikilink):not(.wikilink-missing)").forEach(function(a) {
      var href = a.getAttribute("href");
      if (!href) return;
      if (/^https?:\/\//i.test(href)) {
        a.addEventListener("click", function(ev) {
          ev.preventDefault();
          fetch("/open-external", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: href })
          });
        });
        return;
      }
      if (href.startsWith("#") || href.startsWith("mailto:")) {
        return;
      }
      var hashIdx = href.indexOf("#");
      var pathPart = hashIdx >= 0 ? href.substring(0, hashIdx) : href;
      var anchor = hashIdx >= 0 ? href.substring(hashIdx + 1) : "";
      if (pathPart && /\.md$/i.test(pathPart)) {
        var resolvedMd = _resolveNotePath(noteDir, pathPart);
        a.addEventListener("click", function(ev) {
          ev.preventDefault();
          var label = a.textContent || resolvedMd;
          _navigateToNote(resolvedMd, label, anchor);
        });
        return;
      }
      var resolved = _resolveNotePath(noteDir, pathPart || href);
      a.addEventListener("click", function(ev) {
        ev.preventDefault();
        fetch("/open-doc", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: resolved })
        });
      });
    });
  }
  function closeNotePreview() {
    if (_noteModal.editable) _captureActiveBuffer();
    if (_noteModal.dirty) {
      if (!confirm("You have unsaved changes. Discard them?")) return;
    }
    document.getElementById("note-modal").classList.remove("open");
    _destroyCm();
    _hideSaveError();
    _noteModal.path = null;
    _noteModal.dirty = false;
    _noteNavStack = [];
    _syncNoteBack();
    noteSearchClose();
    _noteShowExternalBanner(false);
    _noteReconcileSuppressedUntilMtime = null;
    if (typeof _flushPendingReloads === "function") _flushPendingReloads();
  }
  var _noteSearch = { matches: [], idx: -1 };
  function _clearNoteMarks() {
    var pane = document.getElementById("note-pane-view");
    if (!pane) return;
    pane.querySelectorAll("mark.note-match").forEach(function(m) {
      var parent = m.parentNode;
      while (m.firstChild) parent.insertBefore(m.firstChild, m);
      parent.removeChild(m);
    });
    pane.normalize();
  }
  function _notePdfFind() {
    var modal = document.getElementById("note-modal");
    if (!modal || !modal.classList.contains("open")) return null;
    var host = modal.querySelector('.note-pdf-host[data-mounted="1"]');
    return host && host.__pdfFind ? host.__pdfFind : null;
  }
  function _setSearchCount(state, q) {
    var countEl = document.getElementById("note-search-count");
    if (!countEl) return;
    if (!state || !state.matches.length) {
      countEl.textContent = q ? "0/0" : "";
    } else {
      countEl.textContent = state.idx + 1 + "/" + state.matches.length;
    }
  }
  function noteSearchRun() {
    var input = document.getElementById("note-search-input");
    var q = input ? input.value : "";
    var countEl = document.getElementById("note-search-count");
    var pdfFind = _notePdfFind();
    if (pdfFind) {
      _clearNoteMarks();
      _noteSearch.matches = [];
      _noteSearch.idx = -1;
      pdfFind.run(q).then(function(state) {
        _setSearchCount(state, q);
      });
      return;
    }
    _clearNoteMarks();
    _noteSearch.matches = [];
    _noteSearch.idx = -1;
    if (!q) {
      if (countEl) countEl.textContent = "";
      return;
    }
    var pane = document.getElementById("note-pane-view");
    if (!pane) return;
    var qLow = q.toLowerCase();
    var qLen = q.length;
    var walker = document.createTreeWalker(pane, NodeFilter.SHOW_TEXT, {
      acceptNode: function(n) {
        var tag = n.parentNode && n.parentNode.nodeName;
        if (tag === "SCRIPT" || tag === "STYLE") return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var textNodes = [];
    var node;
    while (node = walker.nextNode()) textNodes.push(node);
    textNodes.forEach(function(n) {
      var low = n.nodeValue.toLowerCase();
      var positions = [];
      var pos = 0;
      while ((pos = low.indexOf(qLow, pos)) !== -1) {
        positions.push(pos);
        pos += qLen;
      }
      for (var i = positions.length - 1; i >= 0; i--) {
        var start = positions[i];
        var matchNode = n.splitText(start);
        matchNode.splitText(qLen);
        var mark = document.createElement("mark");
        mark.className = "note-match";
        matchNode.parentNode.replaceChild(mark, matchNode);
        mark.appendChild(matchNode);
        _noteSearch.matches.push(mark);
      }
    });
    _noteSearch.matches.sort(function(a, b) {
      var cmp = a.compareDocumentPosition(b);
      if (cmp & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
      if (cmp & Node.DOCUMENT_POSITION_PRECEDING) return 1;
      return 0;
    });
    if (_noteSearch.matches.length) {
      _noteSearch.idx = 0;
      _noteSearch.matches[0].classList.add("active");
      _noteSearch.matches[0].scrollIntoView({ block: "center" });
    }
    if (countEl) {
      countEl.textContent = _noteSearch.matches.length ? _noteSearch.idx + 1 + "/" + _noteSearch.matches.length : "0/0";
    }
  }
  function noteSearchStep(dir) {
    var pdfFind = _notePdfFind();
    if (pdfFind) {
      var state = pdfFind.step(dir);
      _setSearchCount(state, "");
      return;
    }
    var n = _noteSearch.matches.length;
    if (!n) return;
    if (_noteSearch.idx >= 0) {
      _noteSearch.matches[_noteSearch.idx].classList.remove("active");
    }
    _noteSearch.idx = (_noteSearch.idx + dir + n) % n;
    var m = _noteSearch.matches[_noteSearch.idx];
    m.classList.add("active");
    m.scrollIntoView({ block: "center" });
    var countEl = document.getElementById("note-search-count");
    if (countEl) countEl.textContent = _noteSearch.idx + 1 + "/" + n;
  }
  function noteSearchOpen() {
    var bar = document.getElementById("note-search-bar");
    if (!bar) return;
    bar.hidden = false;
    var input = document.getElementById("note-search-input");
    if (input) {
      input.focus();
      input.select();
    }
    if (input && input.value) noteSearchRun();
  }
  function noteSearchClose() {
    var pdfFind = _notePdfFind();
    if (pdfFind) pdfFind.close();
    var bar = document.getElementById("note-search-bar");
    if (bar) bar.hidden = true;
    _clearNoteMarks();
    _noteSearch.matches = [];
    _noteSearch.idx = -1;
    var input = document.getElementById("note-search-input");
    if (input) input.value = "";
    var countEl = document.getElementById("note-search-count");
    if (countEl) countEl.textContent = "";
  }
  document.addEventListener("keydown", function(ev) {
    var modal = document.getElementById("note-modal");
    if (!modal || !modal.classList.contains("open")) return;
    var inner = document.getElementById("note-modal-inner");
    var mode = inner ? inner.getAttribute("data-mode") : "view";
    var editing = mode === "cm" || mode === "plain";
    var isFindKey = (ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key === "f" || ev.key === "F");
    if (isFindKey) {
      if (editing) return;
      ev.preventDefault();
      ev.stopPropagation();
      noteSearchOpen();
      return;
    }
    if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key === "e" || ev.key === "E")) {
      if (!_noteModal.editable) return;
      ev.preventDefault();
      ev.stopPropagation();
      setNoteMode(mode === "view" ? _noteModal.lastEditMode || "cm" : "view");
      return;
    }
    var bar = document.getElementById("note-search-bar");
    if (!bar || bar.hidden) return;
    var activeInSearch = document.activeElement && document.activeElement.id === "note-search-input";
    if (ev.key === "Escape") {
      ev.preventDefault();
      ev.stopPropagation();
      noteSearchClose();
    } else if (ev.key === "Enter" && activeInSearch) {
      ev.preventDefault();
      noteSearchStep(ev.shiftKey ? -1 : 1);
    } else if (ev.key === "F3") {
      ev.preventDefault();
      noteSearchStep(ev.shiftKey ? -1 : 1);
    }
  }, true);
  function openDeliverable(path) {
    fetch("/open-doc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path })
    }).catch(function() {
    });
  }
  var _cm = { view: null, themeC: null };
  function _mountCm() {
    if (!window.__cm6) return;
    var host = document.getElementById("note-pane-cm");
    if (!host) return;
    if (_cm.view) return;
    host.innerHTML = "";
    var cm6 = window.__cm6;
    _cm.themeC = new cm6.Compartment();
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    var exts = [
      cm6.basicSetup,
      cm6.markdown(),
      cm6.EditorView.lineWrapping,
      cm6.keymap.of([
        { key: "Mod-s", preventDefault: true, run: function() {
          saveEdit();
          return true;
        } }
      ]),
      _cm.themeC.of(cm6.buildTheme(isDark)),
      cm6.EditorView.updateListener.of(function(u) {
        if (u.docChanged) {
          _noteModal.text = u.state.doc.toString();
          _setDirty(true);
        }
      })
    ];
    _cm.view = new cm6.EditorView({
      doc: _noteModal.text || "",
      parent: host,
      extensions: exts
    });
    _cm.view.dispatch({ selection: { anchor: 0 } });
    _cm.view.scrollDOM.scrollTop = 0;
    _cm.view.focus();
  }
  function _destroyCm() {
    if (_cm.view) {
      try {
        _cm.view.destroy();
      } catch (e) {
      }
    }
    _cm.view = null;
    _cm.themeC = null;
    var host = document.getElementById("note-pane-cm");
    if (host) host.innerHTML = "";
  }
  function _cmRetheme() {
    if (!_cm.view || !_cm.themeC || !window.__cm6) return;
    var isDark = document.documentElement.getAttribute("data-theme") === "dark";
    _cm.view.dispatch({
      effects: _cm.themeC.reconfigure(window.__cm6.buildTheme(isDark))
    });
  }
  function _setNoteModeAttr(inner, mode) {
    inner.setAttribute("data-mode", mode);
  }
  function _hideSaveError() {
    var err = document.getElementById("note-edit-error");
    if (err) {
      err.textContent = "";
      err.classList.remove("visible");
    }
  }
  function _showSaveError(msg) {
    var err = document.getElementById("note-edit-error");
    if (!err) return;
    err.textContent = msg;
    err.classList.add("visible");
  }
  function _syncModeControls() {
    var inner = document.getElementById("note-modal-inner");
    var mode = inner ? inner.getAttribute("data-mode") : "view";
    var toggle = document.getElementById("note-mode-toggle");
    var saveBtn = document.getElementById("note-save-btn");
    if (toggle) {
      toggle.querySelector('[data-mode="cm"]').disabled = !_noteModal.editable || !window.__cm6;
      toggle.querySelector('[data-mode="plain"]').disabled = !_noteModal.editable;
      if (!window.__cm6) {
        toggle.querySelector('[data-mode="cm"]').title = "Loading editor\u2026";
      } else if (!_noteModal.editable) {
        toggle.querySelector('[data-mode="cm"]').title = "This file is not editable (binary/preview-only)";
      } else {
        toggle.querySelector('[data-mode="cm"]').title = "Edit with syntax highlighting (Ctrl+E)";
      }
    }
    if (saveBtn) saveBtn.style.display = mode === "cm" || mode === "plain" ? "" : "none";
    _syncSaveButton();
  }
  function _captureActiveBuffer() {
    var inner = document.getElementById("note-modal-inner");
    var mode = inner.getAttribute("data-mode");
    if (mode === "cm" && _cm.view) {
      _noteModal.text = _cm.view.state.doc.toString();
    } else if (mode === "plain") {
      var ta = document.getElementById("note-edit-textarea");
      if (ta) _noteModal.text = ta.value;
    }
  }
  function _hydratePane(mode) {
    if (mode === "plain") {
      var ta = document.getElementById("note-edit-textarea");
      if (!ta) return;
      if (ta.value !== _noteModal.text) ta.value = _noteModal.text;
      ta.setSelectionRange(0, 0);
      ta.scrollTop = 0;
    } else if (mode === "cm") {
      if (!_cm.view) {
        _mountCm();
        return;
      }
      var cur = _cm.view.state.doc.toString();
      if (cur !== _noteModal.text) {
        _cm.view.dispatch({
          changes: { from: 0, to: cur.length, insert: _noteModal.text }
        });
      }
      _cm.view.dispatch({ selection: { anchor: 0 } });
      _cm.view.scrollDOM.scrollTop = 0;
    } else if (mode === "view") {
      var pane = document.getElementById("note-pane-view");
      if (pane) pane.scrollTop = 0;
    }
  }
  function setNoteMode(next) {
    if (next !== "view" && next !== "cm" && next !== "plain") return;
    if ((next === "cm" || next === "plain") && !_noteModal.editable) return;
    if (next === "cm" && !window.__cm6) return;
    var inner = document.getElementById("note-modal-inner");
    var prev = inner.getAttribute("data-mode");
    if (prev === next) return;
    if (prev === "cm" || prev === "plain") _captureActiveBuffer();
    _setNoteModeAttr(inner, next);
    if (next === "cm" || next === "plain") _noteModal.lastEditMode = next;
    _hideSaveError();
    _hydratePane(next);
    _syncModeControls();
    if (next === "cm" && _cm.view) {
      setTimeout(function() {
        _cm.view.focus();
      }, 0);
    } else if (next === "plain") {
      var ta = document.getElementById("note-edit-textarea");
      if (ta) setTimeout(function() {
        ta.focus();
      }, 0);
    }
  }
  async function saveEdit() {
    var inner = document.getElementById("note-modal-inner");
    var mode = inner.getAttribute("data-mode");
    if (mode !== "cm" && mode !== "plain") return;
    if (!_noteModal.path) return;
    _captureActiveBuffer();
    _hideSaveError();
    try {
      var res = await fetch("/note", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: _noteModal.path,
          content: _noteModal.text,
          expected_mtime: _noteModal.mtime
        })
      });
      var data = await res.json().catch(function() {
        return {};
      });
      if (!res.ok) {
        if (res.status === 409 && data.mtime) _noteModal.mtime = Number(data.mtime);
        _showSaveError(data.reason || data.error || "HTTP " + res.status);
        return;
      }
      if (data.mtime != null) _noteModal.mtime = Number(data.mtime);
      _setDirty(false);
      var name = document.getElementById("note-modal-title").textContent;
      await _reloadNotePreview(_noteModal.path, name);
    } catch (e) {
      _showSaveError("Save failed: " + e);
    }
  }
  async function createNoteFor(readmePath, subRelToNotes) {
    var raw = prompt("New note filename (e.g. plan.md, decision.txt):", "new-note.md");
    if (!raw) return;
    raw = raw.trim();
    if (!raw) return;
    if (raw.indexOf(".") < 0) raw = raw + ".md";
    try {
      var res = await fetch("/note/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          item_readme: readmePath,
          filename: raw,
          subdir: subRelToNotes || ""
        })
      });
      var data = await res.json().catch(function() {
        return {};
      });
      if (!res.ok) {
        alert("Could not create note: " + (data.reason || data.error || "HTTP " + res.status));
        return;
      }
      await openNotePreview(data.path, raw);
      if (_noteModal.editable) {
        setNoteMode(window.__cm6 ? "cm" : "plain");
      }
    } catch (e) {
      alert("Network error: " + e);
    }
  }
  var _NOTES_RENAMEABLE_RE = /^projects\/\d{4}-\d{2}\/\d{4}-\d{2}-\d{2}-[\w.\-]+\/notes\//;
  function startRenameNote() {
    var titleEl = document.getElementById("note-modal-title");
    var path = _noteModal.path || "";
    if (!_NOTES_RENAMEABLE_RE.test(path)) return;
    if (titleEl.querySelector(".note-rename-input")) return;
    var filename = path.substring(path.lastIndexOf("/") + 1);
    var dotIdx = filename.lastIndexOf(".");
    var stem = dotIdx > 0 ? filename.substring(0, dotIdx) : filename;
    var ext = dotIdx > 0 ? filename.substring(dotIdx) : "";
    var originalText = titleEl.textContent;
    var restored = false;
    var restore = function() {
      if (restored) return;
      restored = true;
      titleEl.textContent = originalText;
    };
    var input = document.createElement("input");
    input.type = "text";
    input.className = "note-rename-input";
    input.value = stem;
    var extEl = document.createElement("span");
    extEl.className = "note-rename-ext";
    extEl.textContent = ext;
    titleEl.textContent = "";
    titleEl.appendChild(input);
    titleEl.appendChild(extEl);
    input.focus();
    input.select();
    var commit = function() {
      var newStem = input.value.trim();
      if (!newStem || newStem === stem) {
        restore();
        return;
      }
      fetch("/note/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, new_stem: newStem })
      }).then(function(r) {
        return r.json().then(function(data) {
          return { ok: r.ok, data };
        });
      }).then(function(result) {
        if (!result.ok || !result.data.ok) {
          alert("Rename failed: " + (result.data.error || result.data.reason || "unknown"));
          restore();
          return;
        }
        _noteModal.path = result.data.path;
        if (result.data.mtime != null) _noteModal.mtime = Number(result.data.mtime);
        var newName = newStem + ext;
        titleEl.textContent = newName;
        restored = true;
      }).catch(function(err) {
        alert("Rename failed: " + err);
        restore();
      });
    };
    input.onkeydown = function(ev) {
      if (ev.key === "Enter") {
        ev.preventDefault();
        commit();
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        restore();
      }
      ev.stopPropagation();
    };
    input.onblur = commit;
    input.onclick = function(ev) {
      ev.stopPropagation();
    };
  }
  var _noteReconcileSuppressedUntilMtime = null;
  async function _reconcileNoteModal() {
    if (!_noteModal || !_noteModal.path) return;
    var path = _noteModal.path;
    try {
      var res = await fetch("/note-raw?path=" + encodeURIComponent(path));
      if (!res.ok) return;
      var data = await res.json();
      if (_noteModal.path !== path) return;
      var fresh = Number(data.mtime);
      var loaded = Number(_noteModal.mtime);
      if (!isFinite(fresh) || !isFinite(loaded)) return;
      if (fresh <= loaded) return;
      if (_noteReconcileSuppressedUntilMtime != null && fresh <= _noteReconcileSuppressedUntilMtime) {
        return;
      }
      if (_noteModal.editable) _captureActiveBuffer();
      if (_noteModal.dirty) {
        _noteShowExternalBanner(true);
      } else {
        await _noteSilentReload(data);
      }
    } catch (e) {
    }
  }
  function _noteShowExternalBanner(show) {
    var banner = document.getElementById("note-modal-external-banner");
    if (!banner) return;
    if (show) banner.removeAttribute("hidden");
    else banner.setAttribute("hidden", "");
  }
  function _noteReconcileDismiss() {
    _noteReconcileSuppressedUntilMtime = Number(_noteModal.mtime) || 0;
    _noteShowExternalBanner(false);
  }
  async function _noteReconcileReload() {
    try {
      var res = await fetch("/note-raw?path=" + encodeURIComponent(_noteModal.path));
      if (!res.ok) return;
      var data = await res.json();
      await _noteSilentReload(data);
      _noteShowExternalBanner(false);
      _noteReconcileSuppressedUntilMtime = null;
    } catch (e) {
    }
  }
  async function _noteSilentReload(rawData) {
    _noteModal.text = rawData.content;
    _noteModal.mtime = Number(rawData.mtime);
    _setDirty(false);
    if (_cm && _cm.view) {
      var prevSel = null;
      try {
        prevSel = _cm.view.state.selection;
      } catch (e) {
      }
      _cm.view.dispatch({
        changes: { from: 0, to: _cm.view.state.doc.length, insert: _noteModal.text }
      });
      if (prevSel) {
        try {
          var max = _cm.view.state.doc.length;
          var anchor = Math.min(prevSel.main.anchor, max);
          var head = Math.min(prevSel.main.head, max);
          _cm.view.dispatch({ selection: { anchor, head } });
        } catch (e) {
        }
      }
    }
    var ta = document.getElementById("note-edit-textarea");
    if (ta) ta.value = _noteModal.text;
    try {
      await _reloadNotePreview(_noteModal.path, null);
    } catch (e) {
    }
  }
  async function _reloadNotePreview(path, name) {
    var pane = document.getElementById("note-pane-view");
    if (name) document.getElementById("note-modal-title").textContent = name;
    pane.innerHTML = '<p class="note-loading">Loading\u2026</p>';
    var res = await fetch("/note?path=" + encodeURIComponent(path));
    if (!res.ok) {
      pane.innerHTML = '<p class="note-error">Failed to load note (' + res.status + ").</p>";
      return;
    }
    var html = await res.text();
    pane.innerHTML = html;
    _noteModal.renderedHtml = html;
    _renderMermaidIn(pane);
    _wireNoteLinks(pane, path);
    _mountPdfsIn(pane);
    pane.scrollTop = 0;
  }
  document.addEventListener("keydown", function(e) {
    if (e.key !== "Escape") return;
    var noteModal = document.getElementById("note-modal");
    if (noteModal && noteModal.classList.contains("open")) {
      closeNotePreview();
      return;
    }
    var newItemModal = document.getElementById("new-item-modal");
    if (newItemModal && newItemModal.style.display && newItemModal.style.display !== "none") {
      closeNewItemModal();
      return;
    }
    var cfgModal = document.getElementById("config-modal");
    if (cfgModal && cfgModal.style.display && cfgModal.style.display !== "none") {
      closeConfigModal();
      return;
    }
    var aboutModal = document.getElementById("about-modal");
    if (aboutModal && aboutModal.style.display && aboutModal.style.display !== "none") {
      closeAboutModal();
    }
  });
  window.addEventListener("beforeunload", function(e) {
    var modal = document.getElementById("note-modal");
    if (!modal || !modal.classList.contains("open")) return;
    if (_noteModal.editable) _captureActiveBuffer();
    if (!_noteModal.dirty) return;
    e.preventDefault();
    e.returnValue = "";
    return "";
  });
  async function cycle(file, line, el) {
    var res = await fetch("/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file, line })
    });
    if (!res.ok) return;
    var data = await res.json();
    el.className = "step " + data.status;
    var dot = el.querySelector(".status-dot");
    dot.className = "status-dot status-" + data.status;
    dot.textContent = { done: "\u2713", progress: "~", abandoned: "\u2014", open: "" }[data.status] || "";
    updateProgress(el.closest(".card"));
    updateBaseline();
  }
  async function removeStep(file, line, btn) {
    var res = await fetch("/remove-step", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file, line })
    });
    if (!res.ok) return;
    var step = btn.closest(".step");
    var card = step.closest(".card");
    var removedLine = parseInt(step.getAttribute("data-line"));
    step.remove();
    card.querySelectorAll(".step").forEach(function(s) {
      var ln = parseInt(s.getAttribute("data-line"));
      if (ln > removedLine) s.setAttribute("data-line", ln - 1);
    });
    updateProgress(card);
    updateBaseline();
  }
  function updateProgress(card) {
    var steps = card.querySelectorAll(".step");
    var done = [].filter.call(steps, function(s) {
      return s.classList.contains("done") || s.classList.contains("abandoned");
    }).length;
    var total = steps.length;
    var el = card.querySelector(".progress-text");
    if (el) {
      var pct = total ? Math.round(done / total * 100) : 0;
      var style = getComputedStyle(document.documentElement);
      var fill = pct === 100 ? style.getPropertyValue("--progress-done") : style.getPropertyValue("--progress-fill");
      var bg = style.getPropertyValue("--progress-track");
      el.innerHTML = done + "/" + total + ' <span class="progress-bar" style="background:' + bg + '"><span class="progress-fill" style="width:' + pct + "%;background:" + fill + '"></span></span>';
    }
    card.querySelectorAll(".sec-group").forEach(function(group) {
      var items = group.querySelectorAll(".step");
      var d = [].filter.call(items, function(s) {
        return s.classList.contains("done") || s.classList.contains("abandoned");
      }).length;
      var span = group.querySelector(".sec-count");
      if (span) span.textContent = "(" + d + "/" + items.length + ")";
    });
  }
  async function addStep(file, section, inputEl) {
    var text = inputEl.value.trim();
    if (!text) return;
    var res = await fetch("/add-step", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file, text, section })
    });
    if (!res.ok) return;
    var data = await res.json();
    var step = document.createElement("div");
    step.className = "step open";
    step.setAttribute("data-file", file);
    step.setAttribute("data-line", data.line);
    var handle = document.createElement("span");
    handle.className = "drag-handle";
    handle.textContent = "\u283F";
    handle.addEventListener("pointerdown", stepPointerDown);
    var dot = document.createElement("span");
    dot.className = "status-dot";
    dot.onmousedown = function(e) {
      e.stopPropagation();
      e.preventDefault();
    };
    dot.onclick = function() {
      var s = this.closest(".step");
      cycle(file, parseInt(s.getAttribute("data-line")), s);
    };
    var txt = document.createElement("span");
    txt.className = "text";
    txt.textContent = text;
    txt.onmousedown = function(e) {
      e.stopPropagation();
    };
    txt.onclick = function(e) {
      e.stopPropagation();
      startEditText(this);
    };
    var btn = document.createElement("button");
    btn.className = "remove-btn";
    btn.textContent = "\xD7";
    btn.onmousedown = function(e) {
      e.stopPropagation();
      e.preventDefault();
    };
    btn.onclick = function() {
      var s = this.closest(".step");
      removeStep(file, parseInt(s.getAttribute("data-line")), this);
    };
    step.appendChild(handle);
    step.appendChild(dot);
    step.appendChild(txt);
    step.appendChild(btn);
    inputEl.closest(".add-row").parentNode.insertBefore(step, inputEl.closest(".add-row"));
    var insertedLine = data.line;
    inputEl.closest(".card").querySelectorAll(".step").forEach(function(s) {
      if (s === step) return;
      var ln = parseInt(s.getAttribute("data-line"));
      if (ln >= insertedLine) s.setAttribute("data-line", ln + 1);
    });
    inputEl.value = "";
    inputEl.focus();
    updateProgress(inputEl.closest(".card"));
    updateBaseline();
  }
  var _stepDrag = null;
  var _STEP_DRAG_THRESHOLD_PX = 4;
  function stepPointerDown(ev) {
    if (ev.button !== void 0 && ev.button !== 0) return;
    var handle = ev.currentTarget;
    var step = handle.closest(".step");
    if (!step) return;
    _stepDrag = {
      step,
      container: step.closest(".sec-items"),
      pointerId: ev.pointerId,
      startX: ev.clientX,
      startY: ev.clientY,
      active: false,
      handle,
      ghost: null,
      ghostOffX: 0,
      ghostOffY: 0,
      drop: null
      // {target: <step>, before: bool}
    };
    try {
      handle.setPointerCapture(ev.pointerId);
    } catch (e) {
    }
    handle.addEventListener("pointermove", stepPointerMove);
    handle.addEventListener("pointerup", stepPointerUp);
    handle.addEventListener("pointercancel", stepPointerCancel);
    ev.preventDefault();
  }
  function stepPointerMove(ev) {
    if (!_stepDrag || ev.pointerId !== _stepDrag.pointerId) return;
    if (!_stepDrag.active) {
      var dx = ev.clientX - _stepDrag.startX;
      var dy = ev.clientY - _stepDrag.startY;
      if (Math.hypot(dx, dy) < _STEP_DRAG_THRESHOLD_PX) return;
      _stepBeginDrag();
    }
    _stepDrag.ghost.style.left = ev.clientX - _stepDrag.ghostOffX + "px";
    _stepDrag.ghost.style.top = ev.clientY - _stepDrag.ghostOffY + "px";
    _stepUpdateDropMarker(ev.clientX, ev.clientY);
  }
  function _stepBeginDrag() {
    var step = _stepDrag.step;
    _stepDrag.active = true;
    var rect = step.getBoundingClientRect();
    var ghost = step.cloneNode(true);
    ghost.classList.add("step-ghost");
    ghost.style.position = "fixed";
    ghost.style.left = rect.left + "px";
    ghost.style.top = rect.top + "px";
    ghost.style.width = rect.width + "px";
    ghost.style.height = rect.height + "px";
    ghost.style.pointerEvents = "none";
    ghost.style.zIndex = "9999";
    ghost.style.opacity = "0.85";
    document.body.appendChild(ghost);
    _stepDrag.ghost = ghost;
    _stepDrag.ghostOffX = _stepDrag.startX - rect.left;
    _stepDrag.ghostOffY = _stepDrag.startY - rect.top;
    step.classList.add("dragging");
  }
  function _stepUpdateDropMarker(x, y) {
    document.querySelectorAll(".step.is-drop-before, .step.is-drop-after").forEach(function(el) {
      el.classList.remove("is-drop-before");
      el.classList.remove("is-drop-after");
    });
    _stepDrag.drop = null;
    var under = document.elementFromPoint(x, y);
    if (!under) return;
    var target = under.closest && under.closest(".step");
    if (!target || target === _stepDrag.step) return;
    if (target.closest(".sec-items") !== _stepDrag.container) return;
    var rect = target.getBoundingClientRect();
    var before = y < rect.top + rect.height / 2;
    target.classList.toggle("is-drop-before", before);
    target.classList.toggle("is-drop-after", !before);
    _stepDrag.drop = { target, before };
  }
  function stepPointerUp(ev) {
    if (!_stepDrag || ev.pointerId !== _stepDrag.pointerId) return;
    var drag = _stepDrag;
    _stepCleanupDrag();
    if (!drag.active) return;
    if (!drag.drop) return;
    var drop = drag.drop;
    if (drop.before) {
      drag.container.insertBefore(drag.step, drop.target);
    } else {
      drag.container.insertBefore(drag.step, drop.target.nextSibling);
    }
    var steps = drag.container.querySelectorAll(".step");
    if (!steps.length) return;
    var file = steps[0].getAttribute("data-file");
    var lines = [].map.call(steps, function(s) {
      return parseInt(s.getAttribute("data-line"));
    });
    var sorted = lines.slice().sort(function(a, b) {
      return a - b;
    });
    if (lines.every(function(v, i) {
      return v === sorted[i];
    })) return;
    fetch("/reorder-all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file, order: lines })
    }).then(function(res) {
      if (!res.ok) return;
      [].forEach.call(steps, function(s, i) {
        s.setAttribute("data-line", sorted[i]);
      });
      updateBaseline();
    });
  }
  function stepPointerCancel(ev) {
    if (!_stepDrag || ev.pointerId !== _stepDrag.pointerId) return;
    _stepCleanupDrag();
  }
  function _stepCleanupDrag() {
    if (!_stepDrag) return;
    var handle = _stepDrag.handle;
    try {
      handle.releasePointerCapture(_stepDrag.pointerId);
    } catch (e) {
    }
    handle.removeEventListener("pointermove", stepPointerMove);
    handle.removeEventListener("pointerup", stepPointerUp);
    handle.removeEventListener("pointercancel", stepPointerCancel);
    if (_stepDrag.ghost && _stepDrag.ghost.parentNode) {
      _stepDrag.ghost.parentNode.removeChild(_stepDrag.ghost);
    }
    _stepDrag.step.classList.remove("dragging");
    document.querySelectorAll(".step.is-drop-before, .step.is-drop-after").forEach(function(el) {
      el.classList.remove("is-drop-before");
      el.classList.remove("is-drop-after");
    });
    _stepDrag = null;
  }
  function startEditText(el) {
    if (el.classList.contains("editing")) return;
    var original = el.textContent;
    var cancelled = false;
    el.classList.add("editing");
    el.contentEditable = "true";
    el.focus();
    var range = document.createRange();
    range.selectNodeContents(el);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    el.onpaste = function(e) {
      e.preventDefault();
      var text = (e.clipboardData || window.clipboardData).getData("text/plain");
      document.execCommand("insertText", false, text.replace(/\n/g, " "));
    };
    async function commit() {
      el.onblur = null;
      el.onkeydown = null;
      el.onpaste = null;
      el.contentEditable = "false";
      el.classList.remove("editing");
      if (cancelled) {
        el.textContent = original;
        return;
      }
      var newText = el.textContent.trim();
      if (!newText || newText === original) {
        el.textContent = original;
        return;
      }
      var step = el.closest(".step");
      var file = step.getAttribute("data-file");
      var line = parseInt(step.getAttribute("data-line"));
      var res = await fetch("/edit-step", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file, line, text: newText })
      });
      if (!res.ok) el.textContent = original;
      else updateBaseline();
    }
    el.onblur = commit;
    el.onkeydown = function(e) {
      if (e.key === "Enter") {
        e.preventDefault();
        el.blur();
      }
      if (e.key === "Escape") {
        cancelled = true;
        el.blur();
      }
    };
  }
  var _nodeBaseline = null;
  var _dirtyNodes = /* @__PURE__ */ new Set();
  var _lastFingerprint = null;
  var _lastGitFingerprint = null;
  function _deriveLegacyFlags() {
    var items = false, git = false, knowledge = false;
    _dirtyNodes.forEach(function(id) {
      if (id === "projects" || id.indexOf("projects/") === 0) items = true;
      else if (id === "code" || id.indexOf("code/") === 0) git = true;
      else if (id === "knowledge" || id.indexOf("knowledge/") === 0) knowledge = true;
    });
    _itemsStale = items;
    _gitStale = git;
    _knowledgeStale = knowledge;
  }
  function _renderStale() {
    document.querySelectorAll("[data-node-id].node-stale, [data-node-id].node-stale-hint").forEach(function(el) {
      el.classList.remove("node-stale");
      el.classList.remove("node-stale-hint");
    });
    document.querySelectorAll(".group-dirty-leader").forEach(function(el) {
      el.classList.remove("group-dirty-leader");
    });
    document.querySelectorAll(".node-reload-btn").forEach(function(btn) {
      btn.remove();
    });
    _deriveLegacyFlags();
    var staleByTab = {
      projects: _itemsStale,
      code: _gitStale,
      knowledge: _knowledgeStale,
      history: _itemsStale
    };
    document.querySelectorAll(".tabs-primary .tab").forEach(function(t) {
      var key = t.getAttribute("data-tab");
      var isStale = !!staleByTab[key] && key !== _activeTab;
      t.classList.toggle("stale", isStale);
      if (isStale) {
        t.title = "Click to refresh \u2014 data has changed on disk";
      } else {
        t.removeAttribute("title");
      }
    });
  }
  var _itemsStale = false;
  var _gitStale = false;
  var _knowledgeStale = false;
  function _diffNodes(baseline, current) {
    var dirty = /* @__PURE__ */ new Set();
    if (!baseline) return dirty;
    for (var id in current) {
      if (baseline[id] !== current[id]) dirty.add(id);
    }
    for (var id2 in baseline) {
      if (!(id2 in current)) dirty.add(id2);
    }
    return dirty;
  }
  var _checkUpdatesTimer = null;
  var _checkUpdatesInFlight = false;
  var _checkUpdatesPending = false;
  function _scheduleCheckUpdates() {
    if (_checkUpdatesInFlight) {
      _checkUpdatesPending = true;
      return;
    }
    if (_checkUpdatesTimer) return;
    _checkUpdatesTimer = setTimeout(function() {
      _checkUpdatesTimer = null;
      checkUpdates();
    }, 250);
  }
  async function checkUpdates() {
    if (_checkUpdatesInFlight) {
      _checkUpdatesPending = true;
      return;
    }
    _checkUpdatesInFlight = true;
    try {
      var res = await fetch("/check-updates");
      if (!res.ok) return;
      var data = await res.json();
      var current = data.nodes || {};
      if (_nodeBaseline === null) {
        _nodeBaseline = current;
        _lastFingerprint = data.fingerprint;
        _lastGitFingerprint = data.git_fingerprint;
      } else {
        var fresh = _diffNodes(_nodeBaseline, current);
        fresh.forEach(function(id) {
          _dirtyNodes.add(id);
        });
        if (fresh.size > 0) _autoReloadActiveTab(fresh);
        var anyInactiveDirty = false;
        fresh.forEach(function(id) {
          var tab = _tabForNodeId(id);
          if (tab && tab !== _activeTab) anyInactiveDirty = true;
        });
        if (anyInactiveDirty) _refreshShadowCache();
      }
      _renderStale();
    } catch (e) {
    } finally {
      _checkUpdatesInFlight = false;
      if (_checkUpdatesPending) {
        _checkUpdatesPending = false;
        _scheduleCheckUpdates();
      }
    }
  }
  function _idInTab(id, tab) {
    var prefix = tab === "history" ? "projects" : tab;
    return id === prefix || id.indexOf(prefix + "/") === 0;
  }
  var _eventSource = null;
  var _eventReconnectTimer = null;
  var _eventReconnectDelay = 1e3;
  var _configReloadTimer = null;
  function _onConfigChanged(payload) {
    if (_configReloadTimer) clearTimeout(_configReloadTimer);
    _configReloadTimer = setTimeout(async function() {
      _configReloadTimer = null;
      var modal = document.getElementById("config-modal");
      var modalOpen = modal && modal.style.display !== "none" && modal.style.display !== "";
      if (modalOpen) {
        try {
          var res = await fetch("/config", { cache: "no-store" });
          if (res.ok) {
            var cfg = await res.json();
            _populateYamlEditor("repositories", cfg.repositories_yaml_body || "", true);
            _populateYamlEditor("preferences", cfg.preferences_yaml_body || "", true);
            if (!_getDirtyYamlFile()) openConfigModal();
          }
        } catch (e) {
        }
      }
      if (typeof _loadTermShortcuts === "function") _loadTermShortcuts();
      _reloadInPlace();
    }, 150);
  }
  function _startEventStream() {
    if (typeof EventSource !== "function") return;
    try {
      _eventSource = new EventSource("/events");
    } catch (e) {
      _setReconnecting(true);
      _scheduleEventReconnect();
      return;
    }
    _eventSource.addEventListener("hello", function() {
      _setReconnecting(false);
      _eventReconnectDelay = 1e3;
      checkUpdates();
    });
    _eventSource.addEventListener("ping", function() {
    });
    _eventSource.onmessage = function(ev) {
      var payload = null;
      try {
        payload = JSON.parse(ev.data || "{}");
      } catch (e) {
        payload = {};
      }
      if (payload && payload.tab === "config") {
        _onConfigChanged(payload);
        return;
      }
      _scheduleCheckUpdates();
      _reconcileNoteModal();
    };
    _eventSource.onerror = function() {
      _setReconnecting(true);
      try {
        _eventSource.close();
      } catch (e) {
      }
      _eventSource = null;
      _scheduleEventReconnect();
    };
  }
  function _scheduleEventReconnect() {
    if (_eventReconnectTimer) return;
    _eventReconnectTimer = setTimeout(function() {
      _eventReconnectTimer = null;
      _eventReconnectDelay = Math.min(_eventReconnectDelay * 2, 3e4);
      _startEventStream();
    }, _eventReconnectDelay);
  }
  function _setReconnecting(on) {
    var pill = document.getElementById("reconnecting-pill");
    if (!pill) return;
    if (on) pill.removeAttribute("hidden");
    else pill.setAttribute("hidden", "");
  }
  function _autoReloadActiveTab(freshIds) {
    var freshInActive = [];
    freshIds.forEach(function(id) {
      if (_idInTab(id, _activeTab)) freshInActive.push(id);
    });
    if (freshInActive.length === 0) return;
    var needGlobal = freshInActive.some(function(id) {
      return !_supportsFragmentFetch(id);
    });
    if (needGlobal) {
      _reloadInPlace();
      return;
    }
    var minimal = _minimalRoots(freshInActive);
    minimal.forEach(function(id) {
      reloadNode(id);
    });
  }
  function _minimalRoots(ids) {
    var sorted = ids.slice().sort();
    var out = [];
    sorted.forEach(function(id) {
      var covered = out.some(function(prev) {
        return id === prev || id.indexOf(prev + "/") === 0;
      });
      if (!covered) out.push(id);
    });
    return out;
  }
  async function updateBaseline() {
    try {
      var res = await fetch("/check-updates");
      if (!res.ok) return;
      var data = await res.json();
      _nodeBaseline = data.nodes || {};
      _dirtyNodes = /* @__PURE__ */ new Set();
      _lastFingerprint = data.fingerprint;
      _lastGitFingerprint = data.git_fingerprint;
      _renderStale();
    } catch (e) {
    }
  }
  function refreshAll() {
    _nodeBaseline = null;
    _dirtyNodes = /* @__PURE__ */ new Set();
    _shadowCache = null;
    _pendingReloadNodes.clear();
    _pendingReloadInPlace = false;
    _lastFingerprint = null;
    _lastGitFingerprint = null;
    location.reload();
  }
  function _supportsFragmentFetch(nodeId) {
    if (/^projects\/[a-z]+\/.+/.test(nodeId)) return true;
    if (nodeId === "knowledge") return false;
    if (/^knowledge\//.test(nodeId)) return true;
    if (/^code\/[^/]+\/[^/]+$/.test(nodeId)) return true;
    return false;
  }
  function _captureDetailsOpenState(root) {
    var map = {};
    root.querySelectorAll("details[data-node-id]").forEach(function(d) {
      map[d.getAttribute("data-node-id")] = d.open;
    });
    return map;
  }
  function _restoreDetailsOpenState(root, map) {
    root.querySelectorAll("details[data-node-id]").forEach(function(d) {
      var id = d.getAttribute("data-node-id");
      if (id in map) d.open = map[id];
    });
  }
  function _noteModalDirty() {
    return !!(window._noteModal && _noteModal.dirty);
  }
  function _runnerActiveIn(targetEl) {
    if (!targetEl || typeof _runnerViewers !== "object") return false;
    var mounts = targetEl.querySelectorAll && targetEl.querySelectorAll(".runner-term-mount");
    if (!mounts || !mounts.length) return false;
    var activeKeys = {};
    for (var dk in _runnerViewers) {
      var v = _runnerViewers[dk];
      if (v && !v.exited && v.ws && v.ws.readyState === WebSocket.OPEN) {
        activeKeys[v.key] = true;
      }
    }
    for (var i = 0; i < mounts.length; i++) {
      var key = mounts[i].getAttribute("data-runner-key");
      if (key && activeKeys[key]) return true;
    }
    return false;
  }
  function _defaultReloadSkipIf(targetEl) {
    if (_noteModalDirty()) return "note-dirty";
    if (_runnerActiveIn(targetEl)) return "runner-active";
    return null;
  }
  var _pendingReloadNodes = /* @__PURE__ */ new Set();
  var _pendingReloadInPlace = false;
  function _flushPendingReloads() {
    if (_noteModalDirty()) return;
    if (_pendingReloadInPlace) {
      _pendingReloadInPlace = false;
      _pendingReloadNodes.clear();
      _reloadInPlace();
      return;
    }
    var retry = Array.from(_pendingReloadNodes);
    _pendingReloadNodes.clear();
    retry.forEach(function(id) {
      reloadNode(id);
    });
  }
  function focusSafeSwap(targetEl, freshEl, opts) {
    opts = opts || {};
    var skipIf = opts.skipIf || _defaultReloadSkipIf;
    var reason = skipIf(targetEl);
    if (reason) return { skipped: true, reason };
    var snapshot = _snapshotForSwap(targetEl, opts);
    targetEl.replaceWith(freshEl);
    _restoreFromSnapshot(freshEl, snapshot, opts);
    return { skipped: false, snapshot };
  }
  function _snapshotForSwap(el, opts) {
    var snap = {};
    snap.scrollY = window.scrollY;
    var mainScroll = document.getElementById("main-scroll");
    snap.mainScrollTop = mainScroll ? mainScroll.scrollTop : null;
    snap.scrollMap = {};
    el.querySelectorAll("[data-scroll-key]").forEach(function(n) {
      snap.scrollMap[n.getAttribute("data-scroll-key")] = {
        top: n.scrollTop,
        left: n.scrollLeft
      };
    });
    snap.detailsMap = _captureDetailsOpenState(el);
    var active = document.activeElement;
    if (active && el.contains(active) && active.id) {
      snap.focusId = active.id;
      try {
        snap.focusSel = {
          start: active.selectionStart,
          end: active.selectionEnd
        };
      } catch (e) {
      }
    }
    el.querySelectorAll("input[data-preserve],textarea[data-preserve]").forEach(function(n) {
      var key = n.getAttribute("data-preserve");
      if (!key) return;
      var payload = { value: n.value };
      try {
        payload.sel = { start: n.selectionStart, end: n.selectionEnd };
      } catch (e) {
      }
      try {
        sessionStorage.setItem(key, JSON.stringify(payload));
      } catch (e) {
      }
    });
    return snap;
  }
  function _restoreFromSnapshot(el, snap, opts) {
    if (snap.scrollY != null) window.scrollTo(0, snap.scrollY);
    var mainScroll = document.getElementById("main-scroll");
    if (mainScroll && snap.mainScrollTop != null) {
      mainScroll.scrollTop = snap.mainScrollTop;
    }
    el.querySelectorAll("[data-scroll-key]").forEach(function(n) {
      var saved = snap.scrollMap && snap.scrollMap[n.getAttribute("data-scroll-key")];
      if (saved) {
        n.scrollTop = saved.top;
        n.scrollLeft = saved.left;
      }
    });
    _restoreDetailsOpenState(el, snap.detailsMap || {});
    if (snap.focusId) {
      var f = document.getElementById(snap.focusId);
      if (f) {
        try {
          f.focus();
        } catch (e) {
        }
        if (snap.focusSel && f.setSelectionRange) {
          try {
            f.setSelectionRange(snap.focusSel.start, snap.focusSel.end);
          } catch (e) {
          }
        }
      }
    }
    el.querySelectorAll("input[data-preserve],textarea[data-preserve]").forEach(function(n) {
      var key = n.getAttribute("data-preserve");
      if (!key) return;
      try {
        var raw = sessionStorage.getItem(key);
        if (!raw) return;
        var payload = JSON.parse(raw);
        if (payload.value != null && n.value !== payload.value) {
          n.value = payload.value;
        }
        if (payload.sel && n.setSelectionRange && document.activeElement === n) {
          try {
            n.setSelectionRange(payload.sel.start, payload.sel.end);
          } catch (e) {
          }
        }
      } catch (e) {
      }
    });
  }
  async function reloadNode(nodeId) {
    if (!_supportsFragmentFetch(nodeId)) {
      _reloadInPlace();
      return;
    }
    try {
      var res = await fetch(
        "/fragment?id=" + encodeURIComponent(nodeId),
        { cache: "no-store" }
      );
      if (!res.ok) {
        _reloadInPlace();
        return;
      }
      var html = await res.text();
      var esc = window.CSS && CSS.escape ? CSS.escape(nodeId) : nodeId;
      var existing = document.querySelector('[data-node-id="' + esc + '"]');
      if (!existing) {
        _reloadInPlace();
        return;
      }
      var tpl = document.createElement("template");
      tpl.innerHTML = html.trim();
      var fresh = tpl.content.firstElementChild;
      if (!fresh) {
        _reloadInPlace();
        return;
      }
      var wasExpanded = existing.classList.contains("card") && !existing.classList.contains("collapsed");
      var result = focusSafeSwap(existing, fresh);
      if (result.skipped) {
        _pendingReloadNodes.add(nodeId);
        return;
      }
      if (wasExpanded && fresh.classList && fresh.classList.contains("card")) {
        fresh.classList.remove("collapsed");
      }
      restoreNotesTreeState();
      await _refreshBaselineFor(nodeId);
      var prefix = nodeId + "/";
      var dropped = [];
      _dirtyNodes.forEach(function(id) {
        if (id === nodeId || id.indexOf(prefix) === 0) dropped.push(id);
      });
      dropped.forEach(function(id) {
        _dirtyNodes.delete(id);
      });
      if (_activeTab === "projects") _applySubtab(_activeSubtab);
      _renderStale();
    } catch (e) {
      _reloadInPlace();
    }
  }
  async function _refreshBaselineFor(nodeId) {
    try {
      var res = await fetch("/check-updates");
      if (!res.ok) return;
      var data = await res.json();
      var current = data.nodes || {};
      if (!_nodeBaseline) _nodeBaseline = {};
      var prefix = nodeId + "/";
      for (var id in current) {
        if (id === nodeId || id.indexOf(prefix) === 0) {
          _nodeBaseline[id] = current[id];
        }
      }
    } catch (e) {
    }
  }
  function _termHasPyApi() {
    return typeof window !== "undefined" && window.pywebview && window.pywebview.api && typeof window.pywebview.api.clipboard_get === "function" && typeof window.pywebview.api.clipboard_set === "function";
  }
  function _termClipboardWrite(text) {
    if (!text) return;
    if (_termHasPyApi()) {
      try {
        Promise.resolve(window.pywebview.api.clipboard_set(text)).catch(function() {
          _termClipboardWriteHttp(text);
        });
        return;
      } catch (e) {
      }
    }
    _termClipboardWriteHttp(text);
  }
  function _termClipboardWriteHttp(text) {
    try {
      fetch("/clipboard", {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: text
      }).catch(function() {
      });
    } catch (e) {
    }
  }
  function _termClipboardRead() {
    if (_termHasPyApi()) {
      try {
        return Promise.resolve(window.pywebview.api.clipboard_get()).then(
          function(t) {
            return t || "";
          },
          function() {
            return _termClipboardReadHttp();
          }
        );
      } catch (e) {
      }
    }
    return _termClipboardReadHttp();
  }
  function _termClipboardReadHttp() {
    return fetch("/clipboard", { cache: "no-store" }).then(function(r) {
      return r.ok ? r.text() : "";
    }).catch(function() {
      return "";
    });
  }
  var _termTabs = [];
  var _termActive = { left: null, right: null };
  var _termNextId = 1;
  var _termAssetsWarned = false;
  function _termAssetsReady() {
    return typeof Terminal !== "undefined" && typeof FitAddon !== "undefined";
  }
  function _termWarnAssets() {
    if (_termAssetsWarned) return;
    _termAssetsWarned = true;
    document.getElementById("term-mount-left").innerHTML = '<p style="color:#faa; padding: 1rem;">Terminal assets failed to load \u2014 vendored xterm.js missing from /vendor/xterm/. Reinstall condash.</p>';
  }
  function _termSideEl(side, which) {
    if (which === "side") return document.querySelector('.term-side[data-side="' + side + '"]');
    if (which === "tabs") return document.getElementById("term-tabs-" + side);
    return document.getElementById("term-mount-" + side);
  }
  function _termTabsOn(side) {
    return _termTabs.filter(function(t) {
      return t.side === side;
    });
  }
  function _termActiveTab() {
    var leftId = _termActive.left, rightId = _termActive.right;
    var pref = _termLastFocused === "right" ? rightId : leftId;
    var alt = _termLastFocused === "right" ? leftId : rightId;
    return _termTabs.find(function(t) {
      return t.id === pref;
    }) || _termTabs.find(function(t) {
      return t.id === alt;
    }) || null;
  }
  var _termLastFocused = "left";
  function _termSendResize(tab) {
    if (!tab) tab = _termActiveTab();
    if (!tab || !tab.fit || !tab.ws || tab.ws.readyState !== WebSocket.OPEN) return;
    if (!tab.mount.clientHeight || !tab.mount.clientWidth) return;
    try {
      tab.fit.fit();
      tab.ws.send(JSON.stringify({ type: "resize", cols: tab.term.cols, rows: tab.term.rows }));
    } catch (e) {
    }
  }
  function _termSendResizeAll() {
    _termTabs.forEach(function(t) {
      _termSendResize(t);
    });
  }
  function _termPersistTabs() {
    var entries = _termTabs.filter(function(t) {
      return !!t.session_id;
    }).map(function(t) {
      return { session_id: t.session_id, side: t.side, customName: t.customName || "" };
    });
    try {
      localStorage.setItem("term-tabs", JSON.stringify(entries));
    } catch (e) {
    }
    var leftActive = null, rightActive = null;
    _termTabs.forEach(function(t) {
      if (!t.session_id) return;
      if (_termActive[t.side] !== t.id) return;
      if (t.side === "left") leftActive = t.session_id;
      else rightActive = t.session_id;
    });
    try {
      if (leftActive) localStorage.setItem("term-active-left", leftActive);
      else localStorage.removeItem("term-active-left");
      if (rightActive) localStorage.setItem("term-active-right", rightActive);
      else localStorage.removeItem("term-active-right");
    } catch (e) {
    }
  }
  function _termShellLabel(tab) {
    var label = document.getElementById("term-shell");
    if (!label) return;
    label.textContent = tab && tab.shell ? tab.shell : "";
  }
  function _termSyncActiveSide() {
    var sides = ["left", "right"];
    sides.forEach(function(side) {
      var el = _termSideEl(side, "side");
      if (!el) return;
      el.classList.toggle("is-active-side", side === _termLastFocused);
    });
    var leftVisible = _termTabsOn("left").length > 0;
    var rightVisible = _termTabsOn("right").length > 0;
    if (leftVisible && rightVisible) document.body.removeAttribute("data-single-term");
    else document.body.setAttribute("data-single-term", "1");
  }
  function _termSetActive(id) {
    var tab = _termTabs.find(function(t) {
      return t.id === id;
    });
    if (!tab) return;
    _termActive[tab.side] = id;
    _termLastFocused = tab.side;
    _termTabs.forEach(function(t) {
      if (t.side !== tab.side) return;
      var active = t.id === id;
      t.mount.classList.toggle("active", active);
      t.button.classList.toggle("active", active);
    });
    _termSyncActiveSide();
    _termShellLabel(tab);
    requestAnimationFrame(function() {
      _termSendResize(tab);
      tab.term.focus();
    });
    _termPersistTabs();
  }
  function _termRenderTabChip(tab) {
    var btn = document.createElement("div");
    btn.className = "term-tab";
    btn.dataset.tabId = String(tab.id);
    btn.onclick = function() {
      _termSetActive(tab.id);
    };
    btn.ondblclick = function(ev) {
      if (ev.target && ev.target.classList.contains("term-tab-close")) return;
      _termStartRename(tab);
    };
    btn.addEventListener("pointerdown", function(ev) {
      _termChipPointerDown(ev, tab);
    });
    var label = document.createElement("span");
    label.className = "term-tab-label";
    label.textContent = _termDefaultLabel(tab);
    btn.appendChild(label);
    var close = document.createElement("button");
    close.className = "term-tab-close";
    close.textContent = "\xD7";
    close.title = "Close tab";
    close.onclick = function(ev) {
      ev.stopPropagation();
      _termCloseTab(tab.id);
    };
    btn.appendChild(close);
    tab.button = btn;
    tab.labelEl = label;
    _termSideEl(tab.side, "tabs").appendChild(btn);
  }
  var _termDrag = null;
  var _TERM_DRAG_THRESHOLD_PX = 5;
  function _termChipPointerDown(ev, tab) {
    if (ev.button !== void 0 && ev.button !== 0) return;
    if (ev.target && ev.target.classList && ev.target.classList.contains("term-tab-close")) return;
    if (ev.target && ev.target.tagName === "INPUT") return;
    _termDrag = {
      tab,
      pointerId: ev.pointerId,
      startX: ev.clientX,
      startY: ev.clientY,
      active: false,
      ghost: null,
      lastDrop: null
    };
    try {
      tab.button.setPointerCapture(ev.pointerId);
    } catch (e) {
    }
    tab.button.addEventListener("pointermove", _termChipPointerMove);
    tab.button.addEventListener("pointerup", _termChipPointerUp);
    tab.button.addEventListener("pointercancel", _termChipPointerCancel);
  }
  function _termChipPointerMove(ev) {
    if (!_termDrag || ev.pointerId !== _termDrag.pointerId) return;
    var dx = ev.clientX - _termDrag.startX;
    var dy = ev.clientY - _termDrag.startY;
    if (!_termDrag.active) {
      if (Math.hypot(dx, dy) < _TERM_DRAG_THRESHOLD_PX) return;
      _termBeginDrag();
    }
    _termDrag.ghost.style.left = ev.clientX - _termDrag.ghostOffX + "px";
    _termDrag.ghost.style.top = ev.clientY - _termDrag.ghostOffY + "px";
    _termUpdateDropMarkers(ev.clientX, ev.clientY);
  }
  function _termChipPointerUp(ev) {
    if (!_termDrag || ev.pointerId !== _termDrag.pointerId) return;
    var drag = _termDrag;
    _termCleanupDrag();
    if (!drag.active) return;
    if (!drag.lastDrop) return;
    var d = drag.lastDrop;
    if (d.kind === "chip" && d.target.id === drag.tab.id) return;
    if (d.kind === "chip") {
      var before = d.before;
      var beforeTab = before ? d.target : _termNextTabOnSide(d.target);
      _termMoveTabTo(drag.tab, d.target.side, beforeTab);
    } else if (d.kind === "strip") {
      _termMoveTabTo(drag.tab, d.side, null);
    }
  }
  function _termChipPointerCancel(ev) {
    if (!_termDrag || ev.pointerId !== _termDrag.pointerId) return;
    _termCleanupDrag();
  }
  function _termBeginDrag() {
    var tab = _termDrag.tab;
    _termDrag.active = true;
    var rect = tab.button.getBoundingClientRect();
    var ghost = tab.button.cloneNode(true);
    ghost.classList.add("term-tab-ghost");
    ghost.style.position = "fixed";
    ghost.style.left = rect.left + "px";
    ghost.style.top = rect.top + "px";
    ghost.style.width = rect.width + "px";
    ghost.style.height = rect.height + "px";
    ghost.style.pointerEvents = "none";
    ghost.style.zIndex = "9999";
    ghost.style.opacity = "0.85";
    document.body.appendChild(ghost);
    _termDrag.ghost = ghost;
    _termDrag.ghostOffX = _termDrag.startX - rect.left;
    _termDrag.ghostOffY = _termDrag.startY - rect.top;
    tab.button.classList.add("is-dragging");
    document.getElementById("term-tabs-left").classList.add("is-drop-target");
    document.getElementById("term-tabs-right").classList.add("is-drop-target");
  }
  function _termUpdateDropMarkers(x, y) {
    document.querySelectorAll(".term-tab.is-drop-before, .term-tab.is-drop-after").forEach(function(el2) {
      el2.classList.remove("is-drop-before");
      el2.classList.remove("is-drop-after");
    });
    _termDrag.lastDrop = null;
    var el = document.elementFromPoint(x, y);
    if (!el) return;
    var chipEl = el.closest ? el.closest(".term-tab") : null;
    if (chipEl && chipEl.classList.contains("term-tab-ghost")) chipEl = null;
    if (chipEl) {
      var id = parseInt(chipEl.dataset.tabId, 10);
      var target = _termTabs.find(function(t) {
        return t.id === id;
      });
      if (target && target.id !== _termDrag.tab.id) {
        var rect = chipEl.getBoundingClientRect();
        var before = x < rect.left + rect.width / 2;
        chipEl.classList.toggle("is-drop-before", before);
        chipEl.classList.toggle("is-drop-after", !before);
        _termDrag.lastDrop = { kind: "chip", target, before };
        return;
      }
    }
    var stripEl = el.closest ? el.closest(".term-tabs") : null;
    if (stripEl) {
      var side = stripEl.id === "term-tabs-right" ? "right" : "left";
      _termDrag.lastDrop = { kind: "strip", side };
    }
  }
  function _termCleanupDrag() {
    if (!_termDrag) return;
    var tab = _termDrag.tab;
    try {
      tab.button.releasePointerCapture(_termDrag.pointerId);
    } catch (e) {
    }
    tab.button.removeEventListener("pointermove", _termChipPointerMove);
    tab.button.removeEventListener("pointerup", _termChipPointerUp);
    tab.button.removeEventListener("pointercancel", _termChipPointerCancel);
    if (_termDrag.ghost && _termDrag.ghost.parentNode) {
      _termDrag.ghost.parentNode.removeChild(_termDrag.ghost);
    }
    tab.button.classList.remove("is-dragging");
    document.querySelectorAll(".term-tab.is-drop-before, .term-tab.is-drop-after").forEach(function(el) {
      el.classList.remove("is-drop-before");
      el.classList.remove("is-drop-after");
    });
    document.querySelectorAll(".term-tabs.is-drop-target").forEach(function(el) {
      el.classList.remove("is-drop-target");
    });
    _termDrag = null;
  }
  function _termNextTabOnSide(tab) {
    var sideTabs = _termTabsOn(tab.side);
    var idx = sideTabs.findIndex(function(t) {
      return t.id === tab.id;
    });
    if (idx < 0 || idx === sideTabs.length - 1) return null;
    return sideTabs[idx + 1];
  }
  function _termMoveTabTo(tab, targetSide, beforeTab) {
    if (!tab || !tab.button || !tab.mount) return;
    targetSide = targetSide === "right" ? "right" : "left";
    var sourceSide = tab.side;
    var wasActiveOnSource = _termActive[sourceSide] === tab.id;
    var targetStrip = _termSideEl(targetSide, "tabs");
    var targetMount = _termSideEl(targetSide, "mount");
    if (!targetStrip || !targetMount) return;
    if (beforeTab && beforeTab.button && beforeTab.button.parentNode === targetStrip) {
      targetStrip.insertBefore(tab.button, beforeTab.button);
    } else {
      targetStrip.appendChild(tab.button);
    }
    if (tab.mount.parentNode !== targetMount) {
      targetMount.appendChild(tab.mount);
    }
    tab.side = targetSide;
    var i = _termTabs.indexOf(tab);
    if (i >= 0) _termTabs.splice(i, 1);
    var stripChildren = Array.prototype.slice.call(targetStrip.children);
    var domIdx = stripChildren.indexOf(tab.button);
    var priorArrayIdx = 0;
    for (var k = 0; k < domIdx; k++) {
      var siblingId = parseInt(stripChildren[k].dataset.tabId, 10);
      var siblingPos = _termTabs.findIndex(function(t) {
        return t.id === siblingId;
      });
      if (siblingPos >= 0) priorArrayIdx = siblingPos + 1;
    }
    _termTabs.splice(priorArrayIdx, 0, tab);
    if (sourceSide !== targetSide) {
      if (wasActiveOnSource) {
        var remaining = _termTabsOn(sourceSide);
        _termActive[sourceSide] = remaining.length ? remaining[remaining.length - 1].id : null;
        if (_termActive[sourceSide] !== null) {
          var stillActive = _termTabs.find(function(t) {
            return t.id === _termActive[sourceSide];
          });
          if (stillActive) {
            stillActive.mount.classList.add("active");
            stillActive.button.classList.add("active");
          }
        }
      }
      tab.mount.classList.remove("active");
      tab.button.classList.remove("active");
      _termSetActive(tab.id);
    }
    _termShowSide(sourceSide, _termTabsOn(sourceSide).length > 0);
    _termShowSide(targetSide, true);
    _termPersistTabs();
    setTimeout(_termSendResizeAll, 0);
  }
  function _termMoveActiveTabToSide(targetSide) {
    var tab = _termActiveTab();
    if (!tab) return;
    if (tab.side === targetSide) return;
    _termMoveTabTo(tab, targetSide, null);
  }
  function _termDefaultLabel(tab) {
    var base = tab.shell ? tab.shell.split("/").pop() || "sh" : "sh";
    return base + " " + tab.id;
  }
  function _termRefreshLabel(tab) {
    if (!tab.labelEl) return;
    tab.labelEl.textContent = tab.customName || _termDefaultLabel(tab);
  }
  function _termStartRename(tab) {
    if (!tab.labelEl) return;
    var input = document.createElement("input");
    input.type = "text";
    input.className = "term-tab-rename";
    input.value = tab.customName || _termDefaultLabel(tab);
    input.style.width = Math.max(60, tab.labelEl.offsetWidth + 20) + "px";
    var committed = false;
    var commit = function(save) {
      if (committed) return;
      committed = true;
      if (save) {
        tab.customName = input.value.trim();
        _termPersistTabs();
      }
      if (input.parentNode) {
        tab.button.insertBefore(tab.labelEl, input);
        input.parentNode.removeChild(input);
      }
      _termRefreshLabel(tab);
    };
    input.onkeydown = function(ev) {
      if (ev.key === "Enter") {
        ev.preventDefault();
        commit(true);
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        commit(false);
      }
      ev.stopPropagation();
    };
    input.onblur = function() {
      commit(true);
    };
    input.onclick = function(ev) {
      ev.stopPropagation();
    };
    tab.button.insertBefore(input, tab.labelEl);
    tab.button.removeChild(tab.labelEl);
    requestAnimationFrame(function() {
      input.focus();
      input.select();
    });
  }
  function _termApplySplitRatio() {
    var r = parseFloat(localStorage.getItem("term-split-ratio") || "");
    var leftEl = _termSideEl("left", "side");
    var rightEl = _termSideEl("right", "side");
    if (isFinite(r) && r > 0 && r < 1) {
      leftEl.style.flex = r + " 1 0";
      rightEl.style.flex = 1 - r + " 1 0";
    } else {
      leftEl.style.flex = "";
      rightEl.style.flex = "";
    }
  }
  function _termShowSide(side, show) {
    var sideEl = _termSideEl(side, "side");
    if (show) sideEl.removeAttribute("hidden");
    else sideEl.setAttribute("hidden", "");
    var leftVisible = _termTabsOn("left").length > 0;
    var rightVisible = _termTabsOn("right").length > 0;
    var splitter = document.getElementById("term-splitter");
    if (leftVisible && rightVisible) {
      splitter.removeAttribute("hidden");
      _termApplySplitRatio();
    } else {
      splitter.setAttribute("hidden", "");
      _termSideEl("left", "side").style.flex = "";
      _termSideEl("right", "side").style.flex = "";
    }
    _termSyncActiveSide();
  }
  function _termCreateTab(side, opts) {
    if (!_termAssetsReady()) {
      _termWarnAssets();
      return;
    }
    side = side === "right" ? "right" : "left";
    opts = opts || {};
    var id = _termNextId++;
    var mount = document.createElement("div");
    mount.className = "term-mount-session";
    _termSideEl(side, "mount").appendChild(mount);
    _termShowSide(side, true);
    var term = new Terminal({
      convertEol: false,
      cursorBlink: true,
      fontFamily: 'ui-monospace, "SF Mono", "Menlo", monospace',
      fontSize: 13,
      theme: { background: "#0b0b0e", foreground: "#e6e6e6" }
    });
    var fit = new FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(mount);
    if (term.textarea) {
      term.textarea.addEventListener("focus", function() {
        if (_termLastFocused !== side) {
          _termLastFocused = side;
          _termSyncActiveSide();
          _termShellLabel(tab);
        }
      });
    }
    term.attachCustomKeyEventHandler(function(ev) {
      if (ev.type !== "keydown") return true;
      if (_termShortcut && _matchShortcut(ev, _termShortcut)) {
        ev.preventDefault();
        ev.stopPropagation();
        toggleTerminal();
        return false;
      }
      if (_screenshotPasteShortcut && _matchShortcut(ev, _screenshotPasteShortcut)) {
        ev.preventDefault();
        ev.stopPropagation();
        pasteRecentScreenshot();
        return false;
      }
      if (_termMoveLeftShortcut && _matchShortcut(ev, _termMoveLeftShortcut)) {
        ev.preventDefault();
        ev.stopPropagation();
        _termMoveActiveTabToSide("left");
        return false;
      }
      if (_termMoveRightShortcut && _matchShortcut(ev, _termMoveRightShortcut)) {
        ev.preventDefault();
        ev.stopPropagation();
        _termMoveActiveTabToSide("right");
        return false;
      }
      if (ev.ctrlKey && !ev.altKey && !ev.metaKey && (ev.key === "c" || ev.key === "C")) {
        if (ev.shiftKey || term.hasSelection()) {
          var sel = term.getSelection();
          if (sel) {
            _termClipboardWrite(sel);
            ev.preventDefault();
            return false;
          }
          if (ev.shiftKey) {
            ev.preventDefault();
            return false;
          }
        }
        return true;
      }
      if (ev.ctrlKey && !ev.altKey && !ev.metaKey && (ev.key === "v" || ev.key === "V")) {
        ev.preventDefault();
        _termClipboardRead().then(function(text) {
          if (text) term.paste(text);
        });
        return false;
      }
      return true;
    });
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var wsUrl = proto + "//" + location.host + "/ws/term";
    if (opts.session_id) {
      wsUrl += "?session_id=" + encodeURIComponent(opts.session_id);
    } else {
      var q = [];
      if (opts.cwd) q.push("cwd=" + encodeURIComponent(opts.cwd));
      if (opts.launcher) q.push("launcher=1");
      if (q.length) wsUrl += "?" + q.join("&");
    }
    var ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    var tab = {
      id,
      side,
      term,
      fit,
      ws,
      mount,
      shell: "",
      customName: opts.customName || "",
      session_id: opts.session_id || null
    };
    ws.onopen = function() {
      _termSendResize(tab);
    };
    ws.onmessage = function(ev) {
      if (typeof ev.data === "string") {
        try {
          var obj = JSON.parse(ev.data);
          if (obj.type === "session-expired") {
            _termCloseTab(tab.id);
          } else if (obj.type === "error" && obj.message) {
            term.write("\r\n\x1B[31m" + obj.message + "\x1B[0m\r\n");
          } else if (obj.type === "info") {
            tab.session_id = obj.session_id || tab.session_id;
            tab.shell = obj.shell || tab.shell;
            _termRefreshLabel(tab);
            _termPersistTabs();
            if (_termActive[tab.side] === tab.id) _termShellLabel(tab);
          } else if (obj.type === "exit") {
            _termCloseTab(tab.id);
          }
        } catch (e) {
        }
        return;
      }
      term.write(new Uint8Array(ev.data));
    };
    ws.onclose = function() {
      _termCloseTab(tab.id);
    };
    term.onData(function(data) {
      if (ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(data));
    });
    _termRenderTabChip(tab);
    _termTabs.push(tab);
    _termShowSide(side, true);
    fit.fit();
    _termSetActive(id);
    setTimeout(_termSendResizeAll, 0);
  }
  function _termCloseTab(id) {
    var idx = _termTabs.findIndex(function(t) {
      return t.id === id;
    });
    if (idx < 0) return;
    var tab = _termTabs[idx];
    var side = tab.side;
    try {
      tab.ws.close();
    } catch (e) {
    }
    try {
      tab.term.dispose();
    } catch (e) {
    }
    if (tab.mount && tab.mount.parentNode) tab.mount.parentNode.removeChild(tab.mount);
    if (tab.button && tab.button.parentNode) tab.button.parentNode.removeChild(tab.button);
    _termTabs.splice(idx, 1);
    var sideTabs = _termTabsOn(side);
    if (sideTabs.length === 0) {
      _termShowSide(side, false);
      _termActive[side] = null;
    } else if (_termActive[side] === id) {
      _termSetActive(sideTabs[sideTabs.length - 1].id);
    }
    if (_termTabs.length === 0) {
      var pane = document.getElementById("term-pane");
      pane.setAttribute("hidden", "");
      _termSyncOpenFlag(false);
      localStorage.removeItem("term-open");
      _termShellLabel(null);
      return;
    }
    if (_termLastFocused === side && sideTabs.length === 0) {
      _termLastFocused = side === "left" ? "right" : "left";
      _termShellLabel(_termActiveTab());
    }
    setTimeout(_termSendResizeAll, 0);
    _termPersistTabs();
  }
  function termNewTab(side) {
    var pane = document.getElementById("term-pane");
    if (pane.hasAttribute("hidden")) {
      pane.removeAttribute("hidden");
      _termSyncOpenFlag(true);
      localStorage.setItem("term-open", "1");
    }
    _termCreateTab(side || "left");
  }
  function termNewLauncherTab(side) {
    if (!_termLauncherCommand) return;
    var pane = document.getElementById("term-pane");
    if (pane.hasAttribute("hidden")) {
      pane.removeAttribute("hidden");
      _termSyncOpenFlag(true);
      localStorage.setItem("term-open", "1");
    }
    var label = _termLauncherCommand.split(/\s+/)[0] || "launcher";
    _termCreateTab(side || "left", { launcher: true, customName: label });
  }
  function _termSyncOpenFlag(open) {
    if (open) document.body.setAttribute("data-term-open", "1");
    else document.body.removeAttribute("data-term-open");
  }
  function toggleTerminal() {
    var pane = document.getElementById("term-pane");
    var opening = pane.hasAttribute("hidden");
    if (opening) {
      pane.removeAttribute("hidden");
      _termSyncOpenFlag(true);
      localStorage.setItem("term-open", "1");
      if (_termTabs.length === 0) _termCreateTab("left");
      setTimeout(function() {
        var tab = _termActiveTab();
        if (tab) {
          _termSendResize(tab);
          tab.term.focus();
        }
      }, 0);
    } else {
      pane.setAttribute("hidden", "");
      _termSyncOpenFlag(false);
      localStorage.removeItem("term-open");
    }
  }
  window.addEventListener("resize", function() {
    _termSendResizeAll();
  });
  var _termDrag = null;
  function _parseShortcut(spec) {
    if (!spec || typeof spec !== "string") return null;
    var parts = spec.split("+").map(function(s) {
      return s.trim();
    }).filter(Boolean);
    if (!parts.length) return null;
    var mods = { ctrl: false, shift: false, alt: false, meta: false };
    var key = null;
    parts.forEach(function(p) {
      var low = p.toLowerCase();
      if (low === "ctrl" || low === "control") mods.ctrl = true;
      else if (low === "shift") mods.shift = true;
      else if (low === "alt" || low === "option") mods.alt = true;
      else if (low === "meta" || low === "cmd" || low === "command" || low === "super") mods.meta = true;
      else key = p;
    });
    if (!key) return null;
    return {
      ctrl: mods.ctrl,
      shift: mods.shift,
      alt: mods.alt,
      meta: mods.meta,
      // Normalise single chars to lower-case; leave named keys as-is.
      key: key.length === 1 ? key.toLowerCase() : key
    };
  }
  function _matchShortcut(ev, spec) {
    if (!spec) return false;
    if (ev.ctrlKey !== spec.ctrl) return false;
    if (ev.shiftKey !== spec.shift) return false;
    if (ev.altKey !== spec.alt) return false;
    if (ev.metaKey !== spec.meta) return false;
    var k = ev.key;
    return (k && k.length === 1 ? k.toLowerCase() : k) === spec.key;
  }
  var _termShortcut = null;
  var _screenshotPasteShortcut = null;
  var _termMoveLeftShortcut = null;
  var _termMoveRightShortcut = null;
  var _termLauncherCommand = "";
  async function _loadTermShortcuts() {
    try {
      var res = await fetch("/config");
      if (!res.ok) return;
      var cfg = await res.json();
      var term = cfg.terminal || {};
      _termShortcut = _parseShortcut(term.shortcut || "Ctrl+`");
      _screenshotPasteShortcut = _parseShortcut(term.screenshot_paste_shortcut || "Ctrl+Shift+V");
      _termMoveLeftShortcut = _parseShortcut(term.move_tab_left_shortcut || "Ctrl+Left");
      _termMoveRightShortcut = _parseShortcut(term.move_tab_right_shortcut || "Ctrl+Right");
      _termLauncherCommand = (term.launcher_command || "").trim();
      _termSyncLauncherButtons();
    } catch (e) {
    }
  }
  function _termSyncLauncherButtons() {
    var show = !!_termLauncherCommand;
    ["left", "right"].forEach(function(side) {
      var btn = document.getElementById("term-launcher-" + side);
      if (!btn) return;
      if (show) {
        btn.removeAttribute("hidden");
        var label = _termLauncherCommand.split(/\s+/)[0] || "launcher";
        btn.title = "New " + label + " tab (" + side + ")";
        btn.setAttribute("aria-label", btn.title);
      } else {
        btn.setAttribute("hidden", "");
      }
    });
  }
  var _toastTimer = null;
  function _showToast(msg, opts) {
    var el = document.getElementById("shortcut-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "shortcut-toast";
      el.className = "shortcut-toast";
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.toggle("is-err", !!(opts && opts.error));
    void el.offsetWidth;
    el.classList.add("is-visible");
    if (_toastTimer) clearTimeout(_toastTimer);
    var ms = opts && opts.ms || 1800;
    _toastTimer = setTimeout(function() {
      el.classList.remove("is-visible");
    }, ms);
  }
  async function pasteRecentScreenshot() {
    var info;
    try {
      var res = await fetch("/recent-screenshot");
      info = await res.json();
      if (!res.ok) {
        _showToast(info && info.error || "HTTP " + res.status, { error: true });
        return;
      }
    } catch (e) {
      _showToast("Could not query screenshot directory", { error: true });
      return;
    }
    if (!info.path) {
      var dirNote = info.dir ? " (" + info.dir + ")" : "";
      _showToast("No screenshot found" + dirNote + (info.reason ? " \u2014 " + info.reason : ""), { error: true });
      return;
    }
    var text = info.path;
    var active = _termActiveTab();
    if (active && active.ws && active.ws.readyState === WebSocket.OPEN) {
      active.ws.send(new TextEncoder().encode(text));
      active.term.focus();
      return;
    }
    var pane = document.getElementById("term-pane");
    if (pane.hasAttribute("hidden")) {
      pane.removeAttribute("hidden");
      _termSyncOpenFlag(true);
      localStorage.setItem("term-open", "1");
    }
    if (_termTabs.length === 0) _termCreateTab("left");
    var tries = 0;
    (function trySend() {
      var tab = _termActiveTab();
      if (tab && tab.ws && tab.ws.readyState === WebSocket.OPEN) {
        tab.ws.send(new TextEncoder().encode(text));
        tab.term.focus();
        return;
      }
      if (++tries < 40) setTimeout(trySend, 75);
    })();
  }
  document.addEventListener("keydown", function(ev) {
    var inEditable = ev.target && (ev.target.tagName === "INPUT" || ev.target.tagName === "TEXTAREA" || ev.target.isContentEditable);
    if (_termShortcut) {
      var hasModifier = _termShortcut.ctrl || _termShortcut.alt || _termShortcut.meta;
      if (!(inEditable && !hasModifier) && _matchShortcut(ev, _termShortcut)) {
        ev.preventDefault();
        toggleTerminal();
        return;
      }
    }
    if (_screenshotPasteShortcut) {
      var hasMod = _screenshotPasteShortcut.ctrl || _screenshotPasteShortcut.alt || _screenshotPasteShortcut.meta;
      if (!(inEditable && !hasMod) && _matchShortcut(ev, _screenshotPasteShortcut)) {
        ev.preventDefault();
        pasteRecentScreenshot();
        return;
      }
    }
    if (_termMoveLeftShortcut && _matchShortcut(ev, _termMoveLeftShortcut)) {
      if (!inEditable || _termMoveLeftShortcut.ctrl || _termMoveLeftShortcut.alt || _termMoveLeftShortcut.meta) {
        ev.preventDefault();
        _termMoveActiveTabToSide("left");
        return;
      }
    }
    if (_termMoveRightShortcut && _matchShortcut(ev, _termMoveRightShortcut)) {
      if (!inEditable || _termMoveRightShortcut.ctrl || _termMoveRightShortcut.alt || _termMoveRightShortcut.meta) {
        ev.preventDefault();
        _termMoveActiveTabToSide("right");
        return;
      }
    }
  });
  _loadTermShortcuts();
  (function restoreTerm() {
    var saved = localStorage.getItem("term-height");
    if (saved) document.documentElement.style.setProperty("--term-height", saved);
    if (localStorage.getItem("term-open") !== "1") return;
    var persisted = [];
    try {
      var raw = localStorage.getItem("term-tabs");
      if (raw) persisted = JSON.parse(raw);
      if (!Array.isArray(persisted)) persisted = [];
    } catch (e) {
      persisted = [];
    }
    var leftActive = localStorage.getItem("term-active-left") || null;
    var rightActive = localStorage.getItem("term-active-right") || null;
    document.addEventListener("DOMContentLoaded", function() {
      window.addEventListener("load", function() {
        if (typeof Terminal === "undefined") return;
        var pane = document.getElementById("term-pane");
        pane.removeAttribute("hidden");
        _termSyncOpenFlag(true);
        if (persisted.length === 0) {
          _termCreateTab("left");
          return;
        }
        persisted.forEach(function(entry) {
          if (!entry || typeof entry !== "object") return;
          if (!entry.session_id) return;
          _termCreateTab(entry.side === "right" ? "right" : "left", {
            session_id: entry.session_id,
            customName: entry.customName || ""
          });
        });
        _termTabs.forEach(function(t) {
          if (!t.session_id) return;
          if (t.side === "left" && t.session_id === leftActive) _termSetActive(t.id);
          else if (t.side === "right" && t.session_id === rightActive) _termSetActive(t.id);
        });
      }, { once: true });
    });
  })();
  checkUpdates();
  _startEventStream();
  (async function detectSetup() {
    try {
      var res = await fetch("/config");
      if (!res.ok) return;
      var cfg = await res.json();
      if (!cfg.conception_path) {
        document.getElementById("setup-banner").style.display = "";
        openConfigModal();
      }
    } catch (e) {
    }
  })();
  new MutationObserver(function() {
    if (typeof _cmRetheme === "function") _cmRetheme();
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  var _runnerViewers = {};
  var _runnerActiveModal = null;
  function _runnerDomKey(key, checkout) {
    return key + "|" + checkout;
  }
  function _runnerCreateViewer(mount, key, checkout, opts) {
    if (typeof Terminal === "undefined" || typeof FitAddon === "undefined") return;
    opts = opts || {};
    var host = mount.querySelector(".runner-term-host");
    if (!host) return;
    var term = new Terminal({
      convertEol: false,
      cursorBlink: false,
      fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
      fontSize: 12,
      theme: { background: "#0b0b0e", foreground: "#e6e6e6" }
    });
    var fit = new FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(host);
    try {
      fit.fit();
    } catch (e) {
    }
    term.attachCustomKeyEventHandler(function(ev) {
      if (ev.type !== "keydown") return true;
      if (ev.ctrlKey && !ev.altKey && !ev.metaKey && (ev.key === "c" || ev.key === "C")) {
        if (ev.shiftKey || term.hasSelection()) {
          var sel = term.getSelection();
          if (sel) {
            _termClipboardWrite(sel);
            ev.preventDefault();
            return false;
          }
          if (ev.shiftKey) {
            ev.preventDefault();
            return false;
          }
        }
        return true;
      }
      if (ev.ctrlKey && !ev.altKey && !ev.metaKey && (ev.key === "v" || ev.key === "V")) {
        ev.preventDefault();
        _termClipboardRead().then(function(text) {
          if (text && !viewer.exited) term.paste(text);
        });
        return false;
      }
      return true;
    });
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var wsUrl = proto + "//" + location.host + "/ws/runner/" + encodeURIComponent(key);
    var ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    var viewer = {
      ws,
      term,
      fit,
      mount,
      key,
      checkout,
      exited: mount.hasAttribute("data-exit-code"),
      isModal: !!opts.isModal
    };
    _runnerViewers[_runnerDomKey(key, checkout)] = viewer;
    ws.onopen = function() {
      try {
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      } catch (e) {
      }
    };
    ws.onmessage = function(ev) {
      if (typeof ev.data === "string") {
        try {
          var obj = JSON.parse(ev.data);
          if (obj.type === "info") {
            var status = obj.exit_code == null ? "running \xB7 " + (obj.template || "") : "exited: " + obj.exit_code;
            _runnerSetStatus(viewer, status);
            if (obj.exit_code != null) {
              viewer.exited = true;
              mount.setAttribute("data-exit-code", String(obj.exit_code));
              mount.classList.add("runner-exited");
            }
          } else if (obj.type === "exit") {
            var wasExited = viewer.exited;
            viewer.exited = true;
            mount.setAttribute("data-exit-code", String(obj.exit_code));
            mount.classList.add("runner-exited");
            _runnerSetStatus(viewer, "exited: " + (obj.exit_code == null ? "?" : obj.exit_code));
            if (!wasExited) {
              _runnerScheduleRefresh(key, checkout);
              if (typeof _flushPendingReloads === "function") {
                _flushPendingReloads();
              }
            }
          } else if (obj.type === "session-missing") {
            _runnerSetStatus(viewer, "no session");
          } else if (obj.type === "error" && obj.message) {
            term.write("\r\n\x1B[31m" + obj.message + "\x1B[0m\r\n");
          }
        } catch (e) {
        }
        return;
      }
      term.write(new Uint8Array(ev.data));
    };
    ws.onclose = function() {
      if (typeof _flushPendingReloads === "function") _flushPendingReloads();
    };
    term.onData(function(data) {
      if (viewer.exited) return;
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });
    requestAnimationFrame(function() {
      try {
        fit.fit();
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
        }
      } catch (e) {
      }
    });
  }
  function _runnerSetStatus(viewer, text) {
    var el = viewer.mount.querySelector(".runner-term-status");
    if (el) el.textContent = text;
  }
  function _runnerDestroyViewer(viewer) {
    if (!viewer) return;
    try {
      viewer.ws.close();
    } catch (e) {
    }
    try {
      viewer.term.dispose();
    } catch (e) {
    }
    delete _runnerViewers[_runnerDomKey(viewer.key, viewer.checkout)];
  }
  function runnerReattachAll() {
    if (typeof Terminal === "undefined") return;
    var mounts = document.querySelectorAll(".runner-term-mount");
    var seen = {};
    mounts.forEach(function(mount) {
      if (mount.classList.contains("runner-modal-viewer")) return;
      var key = mount.dataset.runnerKey;
      var checkout = mount.dataset.runnerCheckout;
      if (!key || !checkout) return;
      var domKey = _runnerDomKey(key, checkout);
      seen[domKey] = true;
      var existing = _runnerViewers[domKey];
      if (existing && existing.mount === mount && !existing.isModal) return;
      if (existing && existing.isModal) return;
      if (existing) _runnerDestroyViewer(existing);
      _runnerCreateViewer(mount, key, checkout);
    });
    Object.keys(_runnerViewers).forEach(function(domKey) {
      if (seen[domKey]) return;
      var viewer = _runnerViewers[domKey];
      if (viewer.isModal) return;
      _runnerDestroyViewer(viewer);
    });
  }
  function _runnerFindMount(key, checkout) {
    var esc = window.CSS && CSS.escape ? CSS.escape : function(s) {
      return s;
    };
    return document.querySelector(
      '.runner-term-mount[data-runner-key="' + esc(key) + '"][data-runner-checkout="' + esc(checkout) + '"]'
    );
  }
  function _runnerRepoNodeIdFor(key, checkout) {
    var mount = _runnerFindMount(key, checkout);
    if (!mount) return null;
    var group = mount.closest(".flat-group");
    return group ? group.getAttribute("data-node-id") : null;
  }
  async function _runnerRefreshRepoNode(repoNodeId) {
    if (!repoNodeId) {
      await _reloadInPlace();
      runnerReattachAll();
      return;
    }
    await reloadNode(repoNodeId);
    runnerReattachAll();
  }
  var _runnerRefreshPending = null;
  function _runnerScheduleRefresh(key, checkout) {
    if (_runnerRefreshPending) clearTimeout(_runnerRefreshPending);
    var repoId = _runnerRepoNodeIdFor(key, checkout) || document.querySelector('.flat-group[data-node-id*="/' + key.split("--")[0] + '"]');
    if (repoId && repoId.getAttribute) repoId = repoId.getAttribute("data-node-id");
    _runnerRefreshPending = setTimeout(function() {
      _runnerRefreshPending = null;
      _runnerRefreshRepoNode(repoId);
    }, 120);
  }
  async function runnerStart(ev, key, checkout, path) {
    if (ev) ev.stopPropagation();
    var res;
    try {
      res = await fetch("/api/runner/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, checkout_key: checkout, path })
      });
    } catch (e) {
      return;
    }
    if (res.status === 409) {
      var data = {};
      try {
        data = await res.json();
      } catch (e) {
      }
      var other = data.checkout_key || "?";
      if (!confirm("Stop runner on " + other + " and start on " + checkout + "?")) return;
      await _runnerStopFetch(key);
      try {
        await fetch("/api/runner/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key, checkout_key: checkout, path })
        });
      } catch (e) {
      }
    }
    await _runnerRefreshRepoNode(_findRepoNodeIdByKey(key));
  }
  async function runnerSwitch(ev, key, checkout, path) {
    return runnerStart(ev, key, checkout, path);
  }
  async function runnerStop(ev, key) {
    if (ev) ev.stopPropagation();
    await _runnerStopFetch(key);
    await _runnerRefreshRepoNode(_findRepoNodeIdByKey(key));
  }
  function runnerStopInline(btn) {
    var mount = btn.closest(".runner-term-mount");
    if (!mount) return;
    runnerStop(null, mount.dataset.runnerKey);
  }
  function runnerToggleCollapse(btn) {
    var mount = btn.closest(".runner-term-mount");
    if (!mount) return;
    var collapsed = mount.classList.toggle("runner-collapsed");
    btn.setAttribute("aria-label", collapsed ? "Expand terminal" : "Collapse terminal");
    if (!collapsed) {
      var key = mount.dataset.runnerKey;
      var checkout = mount.dataset.runnerCheckout;
      var viewer = _runnerViewers[_runnerDomKey(key, checkout)];
      if (viewer) {
        requestAnimationFrame(function() {
          try {
            viewer.fit.fit();
            if (viewer.ws.readyState === WebSocket.OPEN) {
              viewer.ws.send(JSON.stringify({
                type: "resize",
                cols: viewer.term.cols,
                rows: viewer.term.rows
              }));
            }
          } catch (e) {
          }
        });
      }
    }
  }
  async function _runnerStopFetch(key) {
    try {
      await fetch("/api/runner/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key })
      });
    } catch (e) {
    }
  }
  function gitToggleOpenPopover(ev, btn) {
    if (ev) {
      ev.stopPropagation();
      ev.preventDefault();
    }
    var grp = btn.closest(".open-grp");
    if (!grp) return;
    var popover = grp.querySelector(".open-popover");
    if (!popover) return;
    var isOpen = !popover.hidden;
    gitClosePopovers();
    if (!isOpen) popover.hidden = false;
  }
  function gitClosePopovers(root) {
    var scope = root || document;
    scope.querySelectorAll(".open-popover").forEach(function(p) {
      p.hidden = true;
    });
  }
  document.addEventListener("click", function(ev) {
    if (ev.target && ev.target.closest && ev.target.closest(".open-grp")) return;
    gitClosePopovers();
  }, true);
  document.addEventListener("keydown", function(ev) {
    if (ev.key === "Escape") gitClosePopovers();
  });
  function _findRepoNodeIdByKey(key) {
    var repoName = key.indexOf("--") >= 0 ? key.split("--")[0] : key;
    var esc = window.CSS && CSS.escape ? CSS.escape : function(s) {
      return s;
    };
    var nodes = document.querySelectorAll(".flat-group[data-node-id]");
    for (var i = 0; i < nodes.length; i++) {
      var id = nodes[i].getAttribute("data-node-id");
      if (id && id.endsWith("/" + repoName)) return id;
    }
    return null;
  }
  function runnerJump(ev, btn) {
    if (ev) ev.stopPropagation();
    var scope = btn.closest(".peer-card") || btn.closest(".flat-group");
    if (!scope) return;
    var mount = scope.querySelector(".runner-term-mount");
    if (!mount) return;
    try {
      mount.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (e) {
      mount.scrollIntoView();
    }
    mount.classList.add("runner-term-highlight");
    setTimeout(function() {
      mount.classList.remove("runner-term-highlight");
    }, 1200);
  }
  function runnerPopout(btn) {
    var mount = btn.closest(".runner-term-mount");
    if (!mount) return;
    if (_runnerActiveModal) _runnerCloseModal();
    var key = mount.dataset.runnerKey;
    var checkout = mount.dataset.runnerCheckout;
    var domKey = _runnerDomKey(key, checkout);
    _runnerDestroyViewer(_runnerViewers[domKey]);
    var modal = document.createElement("div");
    modal.className = "runner-modal";
    modal.innerHTML = '<div class="runner-modal-dialog">  <div class="runner-modal-header">    <span class="runner-term-label"></span>    <span class="runner-term-status" aria-live="polite"></span>    <button class="runner-modal-close" aria-label="Close">&times;</button>  </div>  <div class="runner-term-mount runner-modal-viewer" data-runner-key="' + key.replace(/"/g, "&quot;") + '" data-runner-checkout="' + checkout.replace(/"/g, "&quot;") + '">    <div class="runner-term-host"></div>  </div></div>';
    modal.querySelector(".runner-term-label").textContent = key + " @ " + checkout;
    document.body.appendChild(modal);
    modal.querySelector(".runner-modal-close").onclick = _runnerCloseModal;
    modal.addEventListener("click", function(ev) {
      if (ev.target === modal) _runnerCloseModal();
    });
    var viewerMount = modal.querySelector(".runner-term-mount");
    _runnerCreateViewer(viewerMount, key, checkout, { isModal: true });
    _runnerActiveModal = {
      modal,
      key,
      checkout
    };
    requestAnimationFrame(function() {
      var viewer = _runnerViewers[_runnerDomKey(key, checkout)];
      if (!viewer) return;
      try {
        viewer.fit.fit();
        if (viewer.ws.readyState === WebSocket.OPEN) {
          viewer.ws.send(JSON.stringify({
            type: "resize",
            cols: viewer.term.cols,
            rows: viewer.term.rows
          }));
        }
      } catch (e) {
      }
    });
  }
  function _runnerCloseModal() {
    var active = _runnerActiveModal;
    if (!active) return;
    _runnerActiveModal = null;
    var viewer = _runnerViewers[_runnerDomKey(active.key, active.checkout)];
    _runnerDestroyViewer(viewer);
    if (active.modal && active.modal.parentNode) {
      active.modal.parentNode.removeChild(active.modal);
    }
    var inlineMount = _runnerFindMount(active.key, active.checkout);
    if (inlineMount) _runnerCreateViewer(inlineMount, active.key, active.checkout);
  }
  (function() {
    var origReloadInPlace = window._reloadInPlace;
    if (typeof origReloadInPlace === "function") {
      window._reloadInPlace = async function() {
        var ret = await origReloadInPlace.apply(this, arguments);
        try {
          runnerReattachAll();
        } catch (e) {
        }
        return ret;
      };
    }
    var origReloadNode = window.reloadNode;
    if (typeof origReloadNode === "function") {
      window.reloadNode = async function() {
        var ret = await origReloadNode.apply(this, arguments);
        try {
          runnerReattachAll();
        } catch (e) {
        }
        return ret;
      };
    }
  })();
  document.addEventListener("DOMContentLoaded", function() {
    window.addEventListener("load", function() {
      try {
        runnerReattachAll();
      } catch (e) {
      }
    }, { once: true });
  });
  window.addEventListener("resize", function() {
    Object.keys(_runnerViewers).forEach(function(domKey) {
      var v = _runnerViewers[domKey];
      try {
        v.fit.fit();
        if (v.ws.readyState === WebSocket.OPEN) {
          v.ws.send(JSON.stringify({ type: "resize", cols: v.term.cols, rows: v.term.rows }));
        }
      } catch (e) {
      }
    });
  });
  Object.assign(window, {
    toggleCard,
    togglePriMenu,
    uploadToNotes,
    workOn,
    toggleSection,
    openInTerminal,
    startEditText,
    stepPointerDown,
    openDeliverable,
    startRenameNote,
    runnerStart,
    runnerStop,
    runnerSwitch,
    runnerToggleCollapse,
    runnerJump,
    runnerPopout,
    runnerStopInline,
    gitToggleOpenPopover,
    gitClosePopovers,
    updateProgress,
    _syncModeControls,
    openNotePreview,
    addStep,
    removeStep,
    cycle,
    pickPriority,
    createNoteFor,
    createNotesSubdir,
    openFolder,
    openConfigModal,
    openNewItemModal,
    openAboutModal,
    closeConfigModal,
    closeNewItemModal,
    closeAboutModal,
    closeNotePreview,
    toggleTheme,
    toggleTerminal,
    termNewTab,
    termNewLauncherTab,
    switchTab,
    switchSubtab,
    switchConfigTab,
    refreshAll,
    setNoteMode,
    noteSearchStep,
    noteSearchClose,
    saveEdit,
    noteNavBack,
    jumpToProject,
    _openHistoryHit,
    _noteReconcileDismiss,
    _noteReconcileReload
  });

  // src/condash/assets/src/js/cm6-mount.js
  (function() {
    if (!window.CondashCM) {
      console.warn("[condash] CodeMirror 6 bundle missing \u2014 note editor stays as plain textarea.");
      return;
    }
    var CM = window.CondashCM;
    var EditorView = CM.EditorView;
    function buildTheme(isDark) {
      var styles = getComputedStyle(document.documentElement);
      var v = function(name, fb) {
        return styles.getPropertyValue(name).trim() || fb;
      };
      var bg = v("--bg-card", isDark ? "#18181b" : "#fff");
      var fg = v("--text", isDark ? "#e4e4e7" : "#18181b");
      var accent = v("--accent", "#2563eb");
      var accentBg = v("--accent-bg", "rgba(37,99,235,0.1)");
      var pillBg = v("--pill-bg", isDark ? "#27272a" : "#f4f4f5");
      var border = v("--border", isDark ? "#3f3f46" : "#e4e4e7");
      var muted = v("--text-muted", "#a1a1aa");
      return EditorView.theme({
        "&": { color: fg, backgroundColor: bg, height: "100%" },
        ".cm-content": { caretColor: accent },
        "&.cm-focused": { outline: "none" },
        ".cm-gutters": {
          backgroundColor: pillBg,
          color: muted,
          borderRight: "1px solid " + border
        },
        ".cm-activeLineGutter, .cm-activeLine": {
          backgroundColor: accentBg
        },
        ".cm-selectionMatch, ::selection": { backgroundColor: accentBg },
        ".cm-cursor, .cm-dropCursor": { borderLeftColor: accent },
        "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
          backgroundColor: accentBg
        }
      }, { dark: isDark });
    }
    window.__cm6 = {
      EditorView,
      EditorState: CM.EditorState,
      Compartment: CM.Compartment,
      keymap: CM.keymap,
      basicSetup: CM.basicSetup,
      markdown: CM.markdownLang,
      buildTheme
    };
    if (typeof window._syncModeControls === "function") window._syncModeControls();
  })();

  // src/condash/assets/src/js/markdown-preview.js
  (async function() {
    const COMMON = {
      cMapUrl: "/vendor/pdfjs/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/vendor/pdfjs/standard_fonts/",
      wasmUrl: "/vendor/pdfjs/wasm/",
      iccUrl: "/vendor/pdfjs/iccs/"
    };
    const ZOOM_STOPS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3];
    const FIT_WIDTH = "fit-width";
    const FIT_PAGE = "fit-page";
    const ACTUAL = "actual";
    let pdfjsLib;
    try {
      pdfjsLib = await import("/vendor/pdfjs/build/pdf.mjs");
      pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdfjs/build/pdf.worker.mjs";
    } catch (err) {
      console.warn("[condash] PDF.js failed to load:", err);
      window.__pdfjs = { ready: false, error: err };
      const pending2 = document.querySelectorAll('.note-pdf-host[data-pdf-pending="1"]');
      pending2.forEach(function(h) {
        delete h.dataset.pdfPending;
        h.innerHTML = '<div class="pdf-error">PDF viewer failed to load.</div>';
      });
      return;
    }
    async function mount(host) {
      if (host.dataset.mounted === "1") return;
      host.dataset.mounted = "1";
      const src = host.dataset.pdfSrc;
      const filename = host.dataset.pdfFilename || "document.pdf";
      host.innerHTML = "";
      const tb = document.createElement("div");
      tb.className = "pdf-toolbar";
      const safeName = filename.replace(/"/g, "&quot;");
      tb.innerHTML = [
        '<button class="pdf-thumbs" title="Toggle thumbnails (T)" aria-label="Toggle thumbnails">\u25A4</button>',
        '<div class="pdf-toolbar-spacer" style="flex:0 0 0.5rem"></div>',
        '<button class="pdf-prev" title="Previous page (\u2190, PgUp)" aria-label="Previous page">\u2190</button>',
        '<span class="pdf-pageinfo">',
        '  <span class="pdf-page-label">Page</span>',
        '  <input class="pdf-page-input" type="number" min="1" value="1" aria-label="Page number">',
        '  <span class="pdf-total">/ ?</span>',
        "</span>",
        '<button class="pdf-next" title="Next page (\u2192, PgDn)" aria-label="Next page">\u2192</button>',
        '<span class="pdf-goto-hint" aria-live="polite"></span>',
        '<div class="pdf-toolbar-spacer"></div>',
        '<button class="pdf-fit" data-fit="fit-width" title="Fit width (W)" aria-label="Fit width">Width</button>',
        '<button class="pdf-fit" data-fit="fit-page" title="Fit page (P)" aria-label="Fit page">Page</button>',
        '<button class="pdf-fit" data-fit="actual" title="Actual size (1)" aria-label="Actual size">1:1</button>',
        '<div class="pdf-toolbar-spacer" style="flex:0 0 0.5rem"></div>',
        '<button class="pdf-zoom-out" title="Zoom out (\u2212)" aria-label="Zoom out">\u2212</button>',
        '<span class="pdf-zoom-label">\u2014</span>',
        '<button class="pdf-zoom-in" title="Zoom in (+)" aria-label="Zoom in">+</button>',
        '<div class="pdf-toolbar-spacer" style="flex:0 0 0.5rem"></div>',
        '<a class="pdf-dl" href="' + src + '" download="' + safeName + '" title="Download" aria-label="Download">\u2193</a>'
      ].join("");
      host.appendChild(tb);
      const body = document.createElement("div");
      body.className = "pdf-body";
      host.appendChild(body);
      const sidebar = document.createElement("aside");
      sidebar.className = "pdf-sidebar";
      sidebar.hidden = true;
      body.appendChild(sidebar);
      const pagesEl = document.createElement("div");
      pagesEl.className = "pdf-pages";
      pagesEl.tabIndex = 0;
      pagesEl.innerHTML = '<div class="pdf-loading">Loading PDF\u2026</div>';
      body.appendChild(pagesEl);
      let pdf;
      try {
        pdf = await pdfjsLib.getDocument(Object.assign({ url: src }, COMMON)).promise;
      } catch (e) {
        pagesEl.innerHTML = '<div class="pdf-error">Failed to load PDF: ' + (e && e.message ? e.message : String(e)) + "</div>";
        return;
      }
      let currentScale = FIT_WIDTH;
      let pageWrappers = [];
      let thumbWrappers = [];
      let renderSeq = 0;
      let findSeq = 0;
      let pageIo = null;
      let lazyIo = null;
      let thumbIo = null;
      const findState = { query: "", matches: [], idx: -1 };
      function destroyObservers() {
        if (lazyIo) lazyIo.disconnect();
        if (pageIo) pageIo.disconnect();
        lazyIo = null;
        pageIo = null;
      }
      function resolveScale(mode, vp1) {
        if (typeof mode === "number") return mode;
        if (mode === ACTUAL) return 1;
        if (mode === FIT_PAGE) {
          const availW = Math.max(200, pagesEl.clientWidth - 32);
          const availH = Math.max(200, pagesEl.clientHeight - 32);
          return Math.min(availW / vp1.width, availH / vp1.height);
        }
        const avail = Math.max(200, pagesEl.clientWidth - 32);
        return avail / vp1.width;
      }
      function updateFitButtons() {
        tb.querySelectorAll(".pdf-fit").forEach(function(b) {
          b.classList.toggle(
            "is-active",
            typeof currentScale === "string" && b.dataset.fit === currentScale
          );
        });
      }
      async function renderAll() {
        const seq = ++renderSeq;
        destroyObservers();
        const p1 = await pdf.getPage(1);
        const vp1 = p1.getViewport({ scale: 1 });
        const scale = resolveScale(currentScale, vp1);
        tb.querySelector(".pdf-zoom-label").textContent = Math.round(scale * 100) + "%";
        tb.querySelector(".pdf-total").textContent = "/ " + pdf.numPages;
        tb.querySelector(".pdf-page-input").max = String(pdf.numPages);
        updateFitButtons();
        pagesEl.innerHTML = "";
        pageWrappers = [];
        for (let i = 1; i <= pdf.numPages; i++) {
          const wrap = document.createElement("div");
          wrap.className = "pdf-page";
          wrap.dataset.page = String(i);
          pagesEl.appendChild(wrap);
          pageWrappers.push(wrap);
        }
        for (let i = 1; i <= pdf.numPages; i++) {
          const p = await pdf.getPage(i);
          if (seq !== renderSeq) return;
          const vp = p.getViewport({ scale });
          const w = pageWrappers[i - 1];
          w.style.width = vp.width + "px";
          w.style.height = vp.height + "px";
        }
        lazyIo = new IntersectionObserver(function(entries) {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            const w = entry.target;
            if (w.dataset.rendered === "1" || w.dataset.rendering === "1") continue;
            w.dataset.rendering = "1";
            const i = Number(w.dataset.page);
            renderPage(seq, i, w, scale).catch(function(err) {
              console.warn("[pdfjs] page", i, "render failed:", err);
            });
          }
        }, { root: pagesEl, rootMargin: "400px" });
        pageWrappers.forEach(function(w) {
          lazyIo.observe(w);
        });
        const inp2 = tb.querySelector(".pdf-page-input");
        pageIo = new IntersectionObserver(function(entries) {
          let best = null, bestRatio = 0;
          for (const e of entries) {
            if (e.intersectionRatio > bestRatio) {
              bestRatio = e.intersectionRatio;
              best = e.target;
            }
          }
          if (best) {
            const n = Number(best.dataset.page);
            if (document.activeElement !== inp2) inp2.value = String(n);
            setActiveThumb(n);
          }
        }, { root: pagesEl, threshold: [0.25, 0.5, 0.75] });
        pageWrappers.forEach(function(w) {
          pageIo.observe(w);
        });
      }
      async function renderPage(seq, i, wrap, scale) {
        const page = await pdf.getPage(i);
        if (seq !== renderSeq) return;
        const vp = page.getViewport({ scale });
        const canvas = document.createElement("canvas");
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(vp.width * dpr);
        canvas.height = Math.floor(vp.height * dpr);
        canvas.style.width = vp.width + "px";
        canvas.style.height = vp.height + "px";
        wrap.appendChild(canvas);
        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        await page.render({ canvasContext: ctx, viewport: vp }).promise;
        if (seq !== renderSeq) return;
        try {
          const txt = await page.getTextContent();
          if (seq !== renderSeq) return;
          const layer = document.createElement("div");
          layer.className = "textLayer";
          layer.style.width = vp.width + "px";
          layer.style.height = vp.height + "px";
          wrap.appendChild(layer);
          if (pdfjsLib.TextLayer) {
            const tl = new pdfjsLib.TextLayer({
              textContentSource: txt,
              container: layer,
              viewport: vp
            });
            await tl.render();
          }
          if (findState.query) {
            markInSubtree(layer, findState.query, findState.matches);
          }
        } catch (e) {
        }
        wrap.dataset.rendered = "1";
        delete wrap.dataset.rendering;
      }
      function buildThumbs() {
        if (thumbWrappers.length === pdf.numPages) return;
        sidebar.innerHTML = "";
        thumbWrappers = [];
        for (let i = 1; i <= pdf.numPages; i++) {
          const tw = document.createElement("div");
          tw.className = "pdf-thumb";
          tw.dataset.page = String(i);
          tw.style.width = "120px";
          tw.style.height = "160px";
          const lbl = document.createElement("span");
          lbl.className = "pdf-thumb-label";
          lbl.textContent = String(i);
          tw.appendChild(lbl);
          tw.addEventListener("click", function() {
            gotoPage(i);
          });
          sidebar.appendChild(tw);
          thumbWrappers.push(tw);
        }
        if (thumbIo) thumbIo.disconnect();
        thumbIo = new IntersectionObserver(function(entries) {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            const tw = entry.target;
            if (tw.dataset.rendered === "1" || tw.dataset.rendering === "1") continue;
            tw.dataset.rendering = "1";
            const i = Number(tw.dataset.page);
            renderThumb(i, tw).catch(function(err) {
              console.warn("[pdfjs] thumb", i, "render failed:", err);
            });
          }
        }, { root: sidebar, rootMargin: "200px" });
        thumbWrappers.forEach(function(tw) {
          thumbIo.observe(tw);
        });
        setActiveThumb(Number(tb.querySelector(".pdf-page-input").value) || 1);
      }
      async function renderThumb(i, tw) {
        const page = await pdf.getPage(i);
        const vp0 = page.getViewport({ scale: 1 });
        const scale = 120 / vp0.width;
        const vp = page.getViewport({ scale });
        const canvas = document.createElement("canvas");
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(vp.width * dpr);
        canvas.height = Math.floor(vp.height * dpr);
        canvas.style.width = vp.width + "px";
        canvas.style.height = vp.height + "px";
        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        await page.render({ canvasContext: ctx, viewport: vp }).promise;
        tw.style.width = vp.width + "px";
        tw.style.height = vp.height + "px";
        tw.insertBefore(canvas, tw.firstChild);
        tw.dataset.rendered = "1";
        delete tw.dataset.rendering;
      }
      function setActiveThumb(n) {
        if (!thumbWrappers.length) return;
        thumbWrappers.forEach(function(tw) {
          const isActive = Number(tw.dataset.page) === n;
          tw.classList.toggle("is-active", isActive);
          if (isActive && !sidebar.hidden) {
            tw.scrollIntoView({ block: "nearest" });
          }
        });
      }
      function toggleSidebar() {
        sidebar.hidden = !sidebar.hidden;
        tb.querySelector(".pdf-thumbs").classList.toggle("is-active", !sidebar.hidden);
        if (!sidebar.hidden) buildThumbs();
      }
      await renderAll();
      const inp = tb.querySelector(".pdf-page-input");
      function gotoPage(n) {
        n = Math.max(1, Math.min(pdf.numPages, n | 0));
        inp.value = String(n);
        pageWrappers[n - 1].scrollIntoView({ behavior: "smooth", block: "start" });
        setActiveThumb(n);
      }
      function setFit(mode) {
        currentScale = mode;
        renderAll();
      }
      function zoomStep(dir) {
        const cur = parseFloat(tb.querySelector(".pdf-zoom-label").textContent) / 100;
        if (dir > 0) {
          currentScale = ZOOM_STOPS.find(function(s) {
            return s > cur + 1e-3;
          }) || ZOOM_STOPS[ZOOM_STOPS.length - 1];
        } else {
          let next = ZOOM_STOPS[0];
          for (const s of ZOOM_STOPS) {
            if (s < cur - 1e-3) next = s;
          }
          currentScale = next;
        }
        renderAll();
      }
      inp.addEventListener("change", function() {
        gotoPage(Number(inp.value) || 1);
      });
      tb.querySelector(".pdf-prev").addEventListener("click", function() {
        gotoPage((Number(inp.value) || 1) - 1);
      });
      tb.querySelector(".pdf-next").addEventListener("click", function() {
        gotoPage((Number(inp.value) || 1) + 1);
      });
      tb.querySelector(".pdf-zoom-in").addEventListener("click", function() {
        zoomStep(1);
      });
      tb.querySelector(".pdf-zoom-out").addEventListener("click", function() {
        zoomStep(-1);
      });
      tb.querySelectorAll(".pdf-fit").forEach(function(b) {
        b.addEventListener("click", function() {
          setFit(b.dataset.fit);
        });
      });
      tb.querySelector(".pdf-thumbs").addEventListener("click", toggleSidebar);
      const gotoHint = tb.querySelector(".pdf-goto-hint");
      const gotoBuf = {
        active: false,
        digits: "",
        timer: null,
        start: function() {
          this.active = true;
          this.digits = "";
          this._render();
          this._arm();
        },
        push: function(d) {
          this.digits += d;
          this._render();
          this._arm();
        },
        commit: function() {
          if (this.digits) gotoPage(parseInt(this.digits, 10));
          this.cancel();
        },
        cancel: function() {
          clearTimeout(this.timer);
          this.timer = null;
          this.active = false;
          this.digits = "";
          this._render();
        },
        _arm: function() {
          clearTimeout(this.timer);
          const self = this;
          this.timer = setTimeout(function() {
            self.commit();
          }, 1500);
        },
        _render: function() {
          gotoHint.textContent = this.active ? "goto " + (this.digits || "\u2026") : "";
        }
      };
      pagesEl.addEventListener("keydown", function(ev) {
        if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
        const key = ev.key;
        if (gotoBuf.active) {
          if (/^[0-9]$/.test(key)) {
            ev.preventDefault();
            gotoBuf.push(key);
            return;
          }
          if (key === "Enter") {
            ev.preventDefault();
            gotoBuf.commit();
            return;
          }
          if (key === "Escape") {
            ev.preventDefault();
            gotoBuf.cancel();
            return;
          }
          gotoBuf.cancel();
        }
        const cur = Number(inp.value) || 1;
        if (key === "+" || key === "=") {
          ev.preventDefault();
          zoomStep(1);
        } else if (key === "-" || key === "_") {
          ev.preventDefault();
          zoomStep(-1);
        } else if (key === "0") {
          ev.preventDefault();
          setFit(FIT_WIDTH);
        } else if (key === "w" || key === "W") {
          ev.preventDefault();
          setFit(FIT_WIDTH);
        } else if (key === "p" || key === "P") {
          ev.preventDefault();
          setFit(FIT_PAGE);
        } else if (key === "1") {
          ev.preventDefault();
          setFit(ACTUAL);
        } else if (key === "PageDown" || key === "ArrowRight") {
          ev.preventDefault();
          gotoPage(cur + 1);
        } else if (key === "PageUp" || key === "ArrowLeft") {
          ev.preventDefault();
          gotoPage(cur - 1);
        } else if (key === "Home") {
          ev.preventDefault();
          gotoPage(1);
        } else if (key === "End") {
          ev.preventDefault();
          gotoPage(pdf.numPages);
        } else if (key === "t" || key === "T") {
          ev.preventDefault();
          toggleSidebar();
        } else if (key === "g" || key === "G") {
          ev.preventDefault();
          gotoBuf.start();
        }
      });
      if (typeof ResizeObserver !== "undefined") {
        let t;
        const ro = new ResizeObserver(function() {
          if (typeof currentScale === "number") return;
          clearTimeout(t);
          t = setTimeout(function() {
            renderAll();
          }, 150);
        });
        ro.observe(pagesEl);
      }
      function markInSubtree(root, q, collected) {
        const qLow = q.toLowerCase();
        const qLen = q.length;
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
          acceptNode: function(n) {
            const tag = n.parentNode && n.parentNode.nodeName;
            if (tag === "SCRIPT" || tag === "STYLE" || tag === "MARK") {
              return NodeFilter.FILTER_REJECT;
            }
            return NodeFilter.FILTER_ACCEPT;
          }
        });
        const textNodes = [];
        let node;
        while (node = walker.nextNode()) textNodes.push(node);
        textNodes.forEach(function(n) {
          const low = n.nodeValue.toLowerCase();
          const positions = [];
          let pos = 0;
          while ((pos = low.indexOf(qLow, pos)) !== -1) {
            positions.push(pos);
            pos += qLen;
          }
          for (let i = positions.length - 1; i >= 0; i--) {
            const start = positions[i];
            const matchNode = n.splitText(start);
            matchNode.splitText(qLen);
            const mark = document.createElement("mark");
            mark.className = "note-match";
            matchNode.parentNode.replaceChild(mark, matchNode);
            mark.appendChild(matchNode);
            collected.push(mark);
          }
        });
      }
      async function ensureAllRendered() {
        const p1 = await pdf.getPage(1);
        const vp1 = p1.getViewport({ scale: 1 });
        const scale = resolveScale(currentScale, vp1);
        const tasks = [];
        for (let i = 0; i < pageWrappers.length; i++) {
          const w = pageWrappers[i];
          if (w.dataset.rendered !== "1" && w.dataset.rendering !== "1") {
            w.dataset.rendering = "1";
            tasks.push(renderPage(renderSeq, Number(w.dataset.page), w, scale));
          }
        }
        if (tasks.length) await Promise.allSettled(tasks);
      }
      function clearFindMarks() {
        pagesEl.querySelectorAll("mark.note-match").forEach(function(m) {
          const parent = m.parentNode;
          while (m.firstChild) parent.insertBefore(m.firstChild, m);
          parent.removeChild(m);
        });
        pagesEl.querySelectorAll(".textLayer").forEach(function(l) {
          l.normalize();
        });
      }
      async function findRun(query) {
        const seq = ++findSeq;
        findState.query = query || "";
        clearFindMarks();
        findState.matches = [];
        findState.idx = -1;
        if (!findState.query) return findState;
        await ensureAllRendered();
        if (seq !== findSeq) return findState;
        for (let i = 0; i < pageWrappers.length; i++) {
          if (seq !== findSeq) return findState;
          const layer = pageWrappers[i].querySelector(".textLayer");
          if (layer) markInSubtree(layer, findState.query, findState.matches);
        }
        if (findState.matches.length) {
          findState.idx = 0;
          const m = findState.matches[0];
          m.classList.add("active");
          scrollMatchIntoView(m);
        }
        return findState;
      }
      function findStep(dir) {
        const n = findState.matches.length;
        if (!n) return findState;
        if (findState.idx >= 0) findState.matches[findState.idx].classList.remove("active");
        findState.idx = (findState.idx + dir + n) % n;
        const m = findState.matches[findState.idx];
        m.classList.add("active");
        scrollMatchIntoView(m);
        return findState;
      }
      function scrollMatchIntoView(m) {
        const wrap = m.closest(".pdf-page");
        if (wrap) {
          const n = Number(wrap.dataset.page);
          inp.value = String(n);
          setActiveThumb(n);
        }
        m.scrollIntoView({ block: "center" });
      }
      function findClose() {
        findState.query = "";
        clearFindMarks();
        findState.matches = [];
        findState.idx = -1;
      }
      host.__pdfFind = {
        run: findRun,
        step: findStep,
        close: findClose,
        state: findState
      };
      pagesEl.focus();
    }
    window.__pdfjs = { lib: pdfjsLib, mount, ready: true };
    const pending = document.querySelectorAll('.note-pdf-host[data-pdf-pending="1"]');
    pending.forEach(function(h) {
      delete h.dataset.pdfPending;
      h.innerHTML = "";
      mount(h);
    });
  })();
})();
