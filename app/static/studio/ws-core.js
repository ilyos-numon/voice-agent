// Workspace core: loads the agent, renders the header, tabs, share/menu, expiry and error states,
// and exposes window.WS for the tab modules (ws-chat, ws-knowledge, ws-settings, ws-scorecard, ws-compare).
(function () {
  "use strict";

  var API = window.StudioAPI;
  var TABS = ["conversation", "knowledge", "settings", "scorecard", "abtest"];
  var TAB_ON = ["font-semibold", "bg-surface-container-highest", "text-primary"];
  var TAB_OFF = ["font-medium", "text-on-surface-variant", "hover:text-on-surface", "hover:bg-surface-container"];
  var BADGE_PRESET = ["bg-surface-container", "text-on-surface-variant", "border-outline-variant/40"];
  var BADGE_CUSTOM = ["bg-emerald-50", "text-emerald-700", "border-emerald-200/60"];

  var listeners = {};
  var readyPayload = null;
  var sessionPending = null;
  var expiryTimer = null;
  var loading = false;

  function $(id) { return document.getElementById(id); }

  function show(el, on) {
    if (el) { el.hidden = !on; }
  }

  function agentPath(suffix) {
    return "/api/agents/" + encodeURIComponent(WS.state.agentId) + (suffix || "");
  }

  function emit(event, payload) {
    var fns = (listeners[event] || []).slice();
    fns.forEach(function (fn) {
      try { fn(payload); } catch (e) { if (window.console) { console.error(e); } }
    });
  }

  function on(event, fn) {
    if (typeof fn !== "function") { return; }
    if (event === "ready" && readyPayload) {
      try { fn(readyPayload); } catch (e) { if (window.console) { console.error(e); } }
      return;
    }
    (listeners[event] = listeners[event] || []).push(fn);
  }

  // ---------- quota / session ----------
  function setQuota(n) {
    WS.state.questionsLeft = n;
    var el = $("quota-count");
    if (el) { el.textContent = (n == null) ? "-" : String(n); }
    emit("quota", { questionsLeft: n });
  }

  function newSession() {
    if (sessionPending) { return sessionPending; }
    sessionPending = API.request("POST", agentPath("/sessions")).then(function (res) {
      sessionPending = null;
      if (!res.ok || !res.data) { throw (res.error || { code: "internal", status: res.status }); }
      WS.state.sessionId = res.data.session_id;
      WS.state.questionsLeft = res.data.questions_left;
      var el = $("quota-count");
      if (el) { el.textContent = String(res.data.questions_left); }
      emit("session", { sessionId: res.data.session_id, questionsLeft: res.data.questions_left });
      return res.data.session_id;
    }, function (e) {
      sessionPending = null;
      throw e;
    });
    return sessionPending;
  }

  // ---------- header ----------
  function agentEmoji(agent) {
    var meta = agent && agent.preset_id && API.presetMeta[agent.preset_id];
    return meta ? meta.emoji : API.customEmoji;
  }

  function renderName(agent) {
    var name = (agent && agent.name) || "상담원";
    $("top-agent-name").textContent = name;
    var g = $("greeting-agent-name");
    if (g) { g.textContent = name; }
    document.title = name + " - 보이스 에이전트 스튜디오";
  }

  function swapClasses(el, add, remove) {
    remove.forEach(function (c) { el.classList.remove(c); });
    add.forEach(function (c) { el.classList.add(c); });
  }

  function renderHeader() {
    var agent = WS.state.agent;
    var preset = isPreset();
    var emoji = agentEmoji(agent);
    ["top-agent-emoji", "greeting-avatar", "indicator-avatar"].forEach(function (id) {
      var el = $(id);
      if (el) { el.textContent = emoji; }
    });
    renderName(agent);

    var badge = $("agent-type-badge");
    badge.dataset.type = preset ? "preset" : "custom";
    badge.textContent = preset ? "기본 프리셋 (수정·삭제 불가)" : "내 상담원";
    badge.title = badge.textContent;
    swapClasses(badge, preset ? BADGE_PRESET : BADGE_CUSTOM, preset ? BADGE_CUSTOM : BADGE_PRESET);
    show(badge, true);

    show($("custom-only-actions"), !preset);
    show($("preset-notice"), preset);
    renderExpiry();
  }

  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  function formatClock(d) {
    return (d.getMonth() + 1) + "월 " + d.getDate() + "일 " + pad2(d.getHours()) + ":" + pad2(d.getMinutes());
  }

  function renderExpiry() {
    var agent = WS.state.agent;
    var text = $("agent-expiry-text");
    var banner = $("expired-banner");
    var msg = $("expired-banner-msg");
    if (expiryTimer) { clearInterval(expiryTimer); expiryTimer = null; }
    if (!agent || isPreset() || !agent.expires_at) {
      show(text, false);
      show(banner, false);
      return;
    }
    var at = new Date(agent.expires_at);
    if (isNaN(at.getTime())) {
      show(text, false);
      show(banner, false);
      return;
    }
    function paint() {
      var left = at.getTime() - Date.now();
      var shortText;
      var longText;
      if (left <= 0) {
        shortText = "만료됨";
        longText = "이 상담원은 보관 기간이 지나 지워졌습니다. 목록에서 새로 만들어 주세요.";
      } else if (left < 3600000) {
        var mins = Math.max(1, Math.ceil(left / 60000));
        shortText = mins + "분 뒤 자동 삭제";
        longText = mins + "분 뒤 자동으로 지워집니다 (" + formatClock(at) + ")";
      } else {
        var hours = Math.floor(left / 3600000);
        shortText = hours + "시간 뒤 자동 삭제";
        longText = hours + "시간 뒤 자동으로 지워집니다 (" + formatClock(at) + ")";
      }
      text.textContent = shortText;
      text.title = longText;
      msg.textContent = longText;
    }
    paint();
    show(text, true);
    show(banner, true);
    expiryTimer = setInterval(paint, 60000);
  }

  function setAgent(agent) {
    if (!agent) { return; }
    WS.state.agent = agent;
    renderHeader();
    emit("agent", { agent: agent });
  }

  function isPreset() {
    return !!(WS.state.agent && WS.state.agent.preset_id != null);
  }

  // ---------- tabs ----------
  function showTab(name) {
    if (TABS.indexOf(name) < 0) { return; }
    TABS.forEach(function (t) {
      var btn = $("tab-btn-" + t);
      var panel = $("tab-panel-" + t);
      var active = t === name;
      if (btn) {
        btn.setAttribute("aria-selected", active ? "true" : "false");
        btn.tabIndex = active ? 0 : -1;
        swapClasses(btn, active ? TAB_ON : TAB_OFF, active ? TAB_OFF : TAB_ON);
      }
      show(panel, active && document.body.dataset.state !== "error");
    });
    emit("tab", { name: name });
  }

  function focusChunk(chunkId) {
    showTab("knowledge");
    emit("focus-chunk", { chunkId: chunkId });
  }

  function currentTab() {
    for (var i = 0; i < TABS.length; i += 1) {
      var btn = $("tab-btn-" + TABS[i]);
      if (btn && btn.getAttribute("aria-selected") === "true") { return TABS[i]; }
    }
    return TABS[0];
  }

  function bindTabs() {
    TABS.forEach(function (t) {
      var btn = $("tab-btn-" + t);
      if (!btn) { return; }
      btn.addEventListener("click", function () { showTab(t); });
      btn.addEventListener("keydown", function (ev) {
        var i = TABS.indexOf(t);
        var next = null;
        if (ev.key === "ArrowRight") { next = TABS[(i + 1) % TABS.length]; }
        else if (ev.key === "ArrowLeft") { next = TABS[(i + TABS.length - 1) % TABS.length]; }
        else if (ev.key === "Home") { next = TABS[0]; }
        else if (ev.key === "End") { next = TABS[TABS.length - 1]; }
        if (!next) { return; }
        ev.preventDefault();
        showTab(next);
        $("tab-btn-" + next).focus();
      });
    });
  }

  // ---------- states ----------
  function setStateAttr(state) {
    document.body.dataset.state = state;
  }

  function showErrorLayout(kind, error) {
    setStateAttr("error");
    show($("ws-tabbar"), false);
    TABS.forEach(function (t) { show($("tab-panel-" + t), false); });
    show($("chat-form"), false);
    show($("expired-banner"), false);
    show($("warnings-box"), false);
    show($("agent-recovery-card"), kind === "not_found");
    show($("agent-error-state"), kind !== "not_found");
    if (kind === "not_found") {
      $("recovery-title").textContent = "상담원을 찾을 수 없습니다";
      $("recovery-desc").textContent = WS.state.agentId
        ? API.errorText({ code: "agent_not_found" })
        : "주소에 상담원 정보가 없습니다. 스튜디오 목록에서 상담원을 골라 주세요.";
      if (!WS.state.agent) { $("top-agent-name").textContent = "상담원을 찾을 수 없습니다"; }
    } else {
      $("agent-error-title").textContent = "상담원 정보를 불러올 수 없습니다";
      $("agent-error-desc").textContent = API.errorText(error || { code: "network" });
      if (!WS.state.agent) { $("top-agent-name").textContent = "상담원 정보를 불러올 수 없습니다"; }
    }
    document.body.dataset.ready = "true";
  }

  function failKind(res) {
    if (res.status === 0 || res.status >= 500) { return "error"; }
    return "not_found";
  }

  function showReadyLayout() {
    show($("agent-recovery-card"), false);
    show($("agent-error-state"), false);
    show($("ws-tabbar"), true);
    show($("chat-form"), true);
    setStateAttr("ready");
    showTabSilently(currentTab());
  }

  function showTabSilently(name) {
    TABS.forEach(function (t) { show($("tab-panel-" + t), t === name); });
  }

  function renderWarnings() {
    var box = $("warnings-box");
    var key = "va:warnings:" + WS.state.agentId;
    var list = [];
    try {
      var raw = sessionStorage.getItem(key);
      if (raw) { list = JSON.parse(raw) || []; }
      sessionStorage.removeItem(key);
    } catch (e) {
      list = [];
    }
    box.textContent = "";
    if (!Array.isArray(list) || !list.length) { show(box, false); return; }
    var head = document.createElement("div");
    head.className = "flex items-center gap-1.5 font-semibold mb-1";
    var icon = document.createElement("span");
    icon.className = "material-symbols-outlined text-[18px] text-secondary";
    icon.textContent = "info";
    var title = document.createElement("span");
    title.textContent = "만들면서 건너뛴 내용이 있습니다";
    head.appendChild(icon);
    head.appendChild(title);
    var ul = document.createElement("ul");
    ul.className = "list-disc pl-6 space-y-0.5 text-on-surface-variant";
    list.forEach(function (m) {
      var li = document.createElement("li");
      li.textContent = typeof m === "string" ? m : (m && m.message) || "";
      ul.appendChild(li);
    });
    box.appendChild(head);
    box.appendChild(ul);
    show(box, true);
  }

  // ---------- load ----------
  async function load() {
    if (loading) { return; }
    loading = true;
    try {
      await loadInner();
    } finally {
      loading = false;
    }
  }

  async function loadInner() {
    setStateAttr("loading");
    show($("agent-error-state"), false);
    show($("agent-recovery-card"), false);
    if (!WS.state.agentId) { showErrorLayout("not_found"); return; }

    var both = await Promise.all([
      API.request("GET", "/api/options"),
      API.request("GET", agentPath(""))
    ]);
    var optRes = both[0];
    var agentRes = both[1];
    if (!agentRes.ok) { showErrorLayout(failKind(agentRes), agentRes.error); return; }
    if (!optRes.ok) { showErrorLayout("error", optRes.error); return; }
    WS.state.options = optRes.data;
    WS.state.agent = agentRes.data;
    WS.state.preset = null;

    if (agentRes.data && agentRes.data.preset_id != null) {
      var pres = await API.request("GET", "/api/presets");
      if (!pres.ok) { showErrorLayout("error", pres.error); return; }
      var items = (pres.data && pres.data.items) || [];
      for (var i = 0; i < items.length; i += 1) {
        if (items[i].agent_id === agentRes.data.agent_id) { WS.state.preset = items[i]; break; }
      }
    }

    renderHeader();
    var limits = (WS.state.options && WS.state.options.limits) || {};
    if (limits.max_questions_per_session != null) {
      $("quota-max").textContent = String(limits.max_questions_per_session);
    }

    try {
      await newSession();
    } catch (err) {
      var status = (err && err.status) || 0;
      showErrorLayout(status === 0 || status >= 500 ? "error" : "not_found", err);
      return;
    }

    showReadyLayout();
    renderWarnings();
    document.body.dataset.ready = "true";
    readyPayload = { agent: WS.state.agent, options: WS.state.options, preset: WS.state.preset };
    var fns = listeners.ready || [];
    listeners.ready = [];
    fns.forEach(function (fn) {
      try { fn(readyPayload); } catch (e) { if (window.console) { console.error(e); } }
    });
  }

  // ---------- share / menu ----------
  function onShare() {
    if (!WS.state.agentId) { return; }
    var url = API.shareUrl(WS.state.agentId);
    var input = $("share-url-input");
    input.value = url;
    show(input, true);
    function fallback() {
      input.focus();
      input.select();
      API.toast("링크를 선택했습니다. 복사해 주세요.", "info");
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(function () {
        API.toast("공유 링크를 복사했습니다.", "success");
      }, fallback);
    } else {
      fallback();
    }
  }

  function setMenu(open) {
    show($("more-menu-dropdown"), open);
    $("more-menu-btn").setAttribute("aria-expanded", open ? "true" : "false");
  }

  function menuOpen() {
    return !$("more-menu-dropdown").hidden;
  }

  function onNewSession() {
    setMenu(false);
    if (!WS.state.agent) { return; }
    newSession().then(function () {
      API.toast("새 세션을 열었습니다.", "success");
    }, function (err) {
      API.toast(API.errorText(err), "error");
    });
  }

  function onExport() {
    setMenu(false);
    var agent = WS.state.agent;
    if (!agent) { return; }
    var body = JSON.stringify({ name: agent.name, preset_id: agent.preset_id, settings: agent.settings }, null, 2);
    var blob = new Blob([body], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "agent-" + agent.agent_id + ".json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  async function onDelete() {
    setMenu(false);
    if (!WS.state.agent || isPreset()) { return; }
    if (!window.confirm("이 상담원을 지울까요? 되돌릴 수 없습니다.")) { return; }
    var res = await API.request("DELETE", agentPath(""));
    if (res.ok || res.status === 404) {
      API.myAgents.remove(WS.state.agentId);
      location.href = "/studio";
      return;
    }
    API.toast(API.errorText(res.error), "error");
  }

  function bindHeader() {
    $("theme-toggle").addEventListener("click", function () { API.theme.toggle(); });
    $("share-btn").addEventListener("click", onShare);
    $("more-menu-btn").addEventListener("click", function (ev) {
      ev.stopPropagation();
      setMenu(!menuOpen());
    });
    document.addEventListener("click", function (ev) {
      if (menuOpen() && !$("more-menu-wrapper").contains(ev.target)) { setMenu(false); }
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && menuOpen()) {
        setMenu(false);
        $("more-menu-btn").focus();
      }
    });
    $("menu-new-session").addEventListener("click", onNewSession);
    $("btn-new-session").addEventListener("click", onNewSession);
    $("menu-export-json").addEventListener("click", onExport);
    $("menu-delete-agent").addEventListener("click", onDelete);
    $("btn-retry-load").addEventListener("click", function () { load(); });
  }

  var WS = {
    state: { agentId: "", agent: null, options: null, preset: null, sessionId: null, questionsLeft: null },
    on: on,
    emit: emit,
    newSession: newSession,
    setQuota: setQuota,
    setAgent: setAgent,
    showTab: showTab,
    focusChunk: focusChunk,
    isPreset: isPreset
  };
  window.WS = WS;

  API.theme.init();
  WS.state.agentId = (new URLSearchParams(location.search).get("agent") || "").trim();

  function start() {
    bindTabs();
    bindHeader();
    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
