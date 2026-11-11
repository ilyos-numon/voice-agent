// Knowledge tab: lists the agent's knowledge pieces (50 per page), client-side filter,
// refresh / load more, and highlights a piece when the conversation asks for it ("focus-chunk").
(function () {
  "use strict";

  var API = window.StudioAPI;
  var WS = window.WS;
  var PAGE = 50;
  var FOCUS_ON = ["ring-2", "ring-primary", "border-primary"];

  var ready = false;
  var started = false;
  var total = null;
  var loaded = 0;
  var loading = null;
  var generation = 0;
  var pendingFocus = null;

  function $(id) { return document.getElementById(id); }

  function show(el, on) {
    if (el) { el.hidden = !on; }
  }

  function chunksPath(offset) {
    return "/api/agents/" + encodeURIComponent(WS.state.agentId) +
      "/chunks?offset=" + offset + "&limit=" + PAGE;
  }

  // ---------- render ----------
  function setError(error) {
    var box = $("knowledge-error");
    if (!error) {
      box.textContent = "";
      show(box, false);
      return;
    }
    box.textContent = API.errorText(error);
    show(box, true);
  }

  function renderCounts() {
    $("knowledge-chunk-counter").textContent = "총 " + (total == null ? "-" : String(total)) + "개";
    $("knowledge-pagination-info").textContent = loaded + " / " + (total == null ? 0 : total);
    show($("knowledge-load-more-btn"), total != null && loaded < total);
  }

  function buildItem(item) {
    var li = document.createElement("li");
    li.className = "ws-chunk p-4 rounded-xl bg-surface border border-outline-variant/40 transition-shadow";
    li.dataset.chunkId = String(item.chunk_id);

    var head = document.createElement("div");
    head.className = "flex items-start justify-between gap-3 mb-1.5";
    var title = document.createElement("h3");
    title.className = "ws-chunk-title text-sm font-semibold text-on-surface";
    title.textContent = item.title || "";
    var id = document.createElement("span");
    id.className = "shrink-0 px-2 py-0.5 rounded-full bg-surface-container text-[11px] font-mono text-on-surface-variant";
    id.textContent = String(item.chunk_id);
    head.appendChild(title);
    head.appendChild(id);

    var text = document.createElement("p");
    text.className = "ws-chunk-text text-xs text-on-surface-variant leading-relaxed whitespace-pre-line";
    text.textContent = item.text || "";

    li.appendChild(head);
    li.appendChild(text);
    return li;
  }

  function matches(li, query) {
    if (!query) { return true; }
    return (li.textContent || "").toLowerCase().indexOf(query) >= 0;
  }

  function applyFilter() {
    var query = ($("knowledge-search-input").value || "").trim().toLowerCase();
    var items = $("knowledge-chunk-list").querySelectorAll("li.ws-chunk");
    for (var i = 0; i < items.length; i += 1) {
      show(items[i], matches(items[i], query));
    }
  }

  // ---------- load ----------
  function loadNext() {
    if (loading) { return loading; }
    if (total != null && loaded >= total) { return Promise.resolve(false); }
    var gen = generation;
    var btn = $("knowledge-load-more-btn");
    btn.disabled = true;
    loading = API.request("GET", chunksPath(loaded)).then(function (res) {
      loading = null;
      btn.disabled = false;
      if (gen !== generation) { return false; }
      if (!res.ok || !res.data) {
        setError(res.error || { code: "internal" });
        return false;
      }
      setError(null);
      var items = Array.isArray(res.data.items) ? res.data.items : [];
      total = typeof res.data.total === "number" ? res.data.total : loaded + items.length;
      var list = $("knowledge-chunk-list");
      items.forEach(function (item) { list.appendChild(buildItem(item)); });
      loaded += items.length;
      if (!items.length) { total = loaded; }
      applyFilter();
      renderCounts();
      return items.length > 0;
    });
    return loading;
  }

  function reset() {
    generation += 1;
    loading = null;
    total = null;
    loaded = 0;
    $("knowledge-chunk-list").textContent = "";
    $("knowledge-load-more-btn").disabled = false;
    setError(null);
    renderCounts();
  }

  function start() {
    if (started || !ready) { return Promise.resolve(); }
    started = true;
    return loadNext().then(runFocus);
  }

  // ---------- focus ----------
  function findItem(chunkId) {
    var items = $("knowledge-chunk-list").querySelectorAll("li.ws-chunk");
    for (var i = 0; i < items.length; i += 1) {
      if (items[i].dataset.chunkId === chunkId) { return items[i]; }
    }
    return null;
  }

  function clearFocus() {
    var prev = $("knowledge-chunk-list").querySelectorAll('li.ws-chunk[data-focused="true"]');
    for (var i = 0; i < prev.length; i += 1) {
      delete prev[i].dataset.focused;
      FOCUS_ON.forEach(function (c) { prev[i].classList.remove(c); });
    }
  }

  function highlight(li) {
    clearFocus();
    if (li.hidden) {
      $("knowledge-search-input").value = "";
      applyFilter();
    }
    li.dataset.focused = "true";
    FOCUS_ON.forEach(function (c) { li.classList.add(c); });
    li.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  function runFocus() {
    if (pendingFocus == null) { return Promise.resolve(); }
    var chunkId = pendingFocus;
    var li = findItem(chunkId);
    if (li) {
      pendingFocus = null;
      highlight(li);
      return Promise.resolve();
    }
    if (total != null && loaded >= total) {
      pendingFocus = null;
      API.toast("자료에서 그 조각을 찾지 못했습니다.", "info");
      return Promise.resolve();
    }
    return loadNext().then(function (added) {
      if (!added) {
        if (pendingFocus === chunkId) { pendingFocus = null; }
        return;
      }
      if (pendingFocus === chunkId) { return runFocus(); }
    });
  }

  function onFocusChunk(payload) {
    var chunkId = payload && payload.chunkId != null ? String(payload.chunkId) : "";
    if (!chunkId) { return; }
    pendingFocus = chunkId;
    if (!ready) { return; }
    if (!started) { start(); return; }
    if (loading) { loading.then(runFocus); return; }
    runFocus();
  }

  // ---------- bind ----------
  function bind() {
    $("knowledge-search-input").addEventListener("input", applyFilter);
    $("knowledge-refresh-btn").addEventListener("click", function () {
      if (!ready) { return; }
      reset();
      started = true;
      loadNext().then(runFocus);
    });
    $("knowledge-load-more-btn").addEventListener("click", function () {
      if (!ready) { return; }
      loadNext();
    });
  }

  function currentTabIsKnowledge() {
    var btn = $("tab-btn-knowledge");
    return !!(btn && btn.getAttribute("aria-selected") === "true");
  }

  function init() {
    bind();
    WS.on("tab", function (p) {
      if (p && p.name === "knowledge") { start(); }
    });
    WS.on("focus-chunk", onFocusChunk);
    WS.on("ready", function () {
      ready = true;
      if (currentTabIsKnowledge() || pendingFocus != null) { start(); }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
