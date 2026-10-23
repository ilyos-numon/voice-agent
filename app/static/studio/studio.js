(function () {
  "use strict";

  var API = window.StudioAPI;
  API.theme.init();

  // Fallback limits (docs/api.md §4) used only until GET /api/options answers.
  var limits = {
    max_text_chars: 20000, max_csv_rows: 300, max_csv_chars: 100000, agent_ttl_hours: 24,
    max_avoid_topics: 10, max_avoid_topic_chars: 20, max_handoff_message_chars: 100
  };
  var NAME_MAX = 30;
  var SUBMIT_LABEL = "상담원 만들기";
  var SAMPLE_CSV = "질문,답변\n주차는 어디에 하나요?,지하 1층 주차장을 이용하세요. 두 시간 무료입니다.\n" +
    "영업시간이 어떻게 되나요?,매일 오전 10시부터 오후 9시까지 영업합니다.\n";

  var state = { category: "all", query: "", mode: "text", busy: false, options: null, listOk: false };
  var cards = [];   // {el, category, text}

  function $(id) { return document.getElementById(id); }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function icon(name, cls) {
    return el("span", "material-symbols-outlined " + (cls || "text-[16px]"), name);
  }

  function show(node, on) {
    if (node) { node.hidden = !on; }
  }

  function num(n) { return Number(n).toLocaleString("ko-KR"); }

  function workspaceUrl(agentId) {
    return "/studio/app?agent=" + encodeURIComponent(agentId);
  }

  function hoursLeft(expiresAt) {
    var t = Date.parse(expiresAt || "");
    if (!t) { return null; }
    return Math.max(0, Math.ceil((t - Date.now()) / 3600000));
  }

  // ---------- health & capabilities ----------
  async function loadHealth() {
    var badge = $("api-health-badge");
    var dot = $("api-health-indicator");
    var text = $("api-health-text");
    var res = await API.request("GET", "/health");
    var ok = res.ok && res.data && res.data.status === "ok";
    badge.dataset.health = ok ? "ok" : "down";
    dot.className = "w-2 h-2 rounded-full " + (ok ? "bg-emerald-500" : "bg-error");
    text.textContent = ok ? "서버 정상" : "서버에 연결하지 못했습니다";
  }

  function setCap(node, label, available) {
    node.dataset.available = available === null ? "unknown" : (available ? "true" : "false");
    var word = available === null ? "확인 못 함" : (available ? "가능" : "꺼짐");
    node.querySelector(".cap-text").textContent = label + " " + word;
    node.classList.toggle("text-primary", available === true);
  }

  // ---------- options → modal ----------
  function fillSelect(select, items, value) {
    select.textContent = "";
    (items || []).forEach(function (item) {
      var opt = el("option", "", item.label);
      opt.value = item.value;
      if (item.available === false) {
        opt.disabled = true;
        opt.textContent = item.label + " (쓸 수 없음)";
      }
      if (item.value === value) { opt.selected = true; }
      select.appendChild(opt);
    });
  }

  function applyOptions(opts) {
    var d = opts.defaults || {};
    Object.keys(opts.limits || {}).forEach(function (k) { limits[k] = opts.limits[k]; });
    fillSelect($("setting-agent-tone"), opts.tone, d.tone);
    fillSelect($("setting-answer-length"), opts.answer_length, d.answer_length);
    fillSelect($("setting-agent-voice"), opts.voices, d.voice);
    fillSelect($("setting-fallback-strategy"), opts.when_unknown, d.when_unknown);
    $("setting-handoff-text").value = d.handoff_message || "";
    $("setting-handoff-text").maxLength = limits.max_handoff_message_chars;
    $("setting-avoid-topics").value = (d.avoid_topics || []).join(", ");
    var summary = $("toggle-external-ai");
    summary.checked = !!d.summary && !!opts.summary_available;
    summary.disabled = !opts.summary_available;
    if (!opts.summary_available) {
      $("ai-summary-description").textContent = "이 서버에는 요약 서비스가 설정돼 있지 않아 켤 수 없습니다.";
    }
    $("csv-rule-text").textContent = "첫 2개 열은 질문과 답변입니다 (최대 " + num(limits.max_csv_rows) + "행).";
    $("modal-privacy-note").textContent = "넣은 자료는 이 상담원에만 쓰이고 서버 메모리에만 있습니다. 만든 상담원은 " +
      num(limits.agent_ttl_hours) + "시간 뒤, 또는 서버를 다시 시작하면 지워집니다.";
    updateCounters();
  }

  async function loadOptions() {
    var res = await API.request("GET", "/api/options");
    if (!res.ok || !res.data) {
      setCap($("cap-voice"), "음성 질문", null);
      setCap($("cap-summary"), "요약 답변", null);
      return;
    }
    state.options = res.data;
    setCap($("cap-voice"), "음성 질문", !!res.data.voice_input_available);
    setCap($("cap-summary"), "요약 답변", !!res.data.summary_available);
    applyOptions(res.data);
  }

  // ---------- cards ----------
  function buildCard(info) {
    var card = el("article", "studio-card group flex flex-col justify-between p-6 rounded-2xl bg-surface-container-lowest dark:bg-surface-variant/10 border border-outline-variant/40 hover:border-primary/50 hover:shadow-xl transition-all relative overflow-hidden");
    card.dataset.agentId = info.agentId;
    if (info.presetId) { card.dataset.presetId = info.presetId; } else { card.dataset.custom = "true"; }

    var top = el("div", "flex flex-col gap-3.5");
    var head = el("div", "flex items-start justify-between gap-3");
    var ident = el("div", "flex items-center gap-3 min-w-0");
    ident.appendChild(el("div", "w-12 h-12 rounded-xl bg-surface-container-high flex items-center justify-center text-[24px] shadow-sm shrink-0", info.emoji));
    var names = el("div", "min-w-0");
    names.appendChild(el("h3", "card-title font-headline-sm text-headline-sm font-semibold group-hover:text-primary transition-colors break-keep", info.title));
    names.appendChild(el("span", "font-code-sm text-code-sm text-tertiary dark:text-outline-variant break-all", info.subtitle));
    ident.appendChild(names);
    head.appendChild(ident);
    var chunks = el("span", "card-chunks inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-surface-container-low dark:bg-surface-variant/20 text-primary font-label-sm text-label-sm font-semibold shrink-0");
    chunks.appendChild(icon("description", "text-[14px]"));
    chunks.appendChild(document.createTextNode("지식 " + num(info.chunkCount) + "건"));
    head.appendChild(chunks);
    top.appendChild(head);
    top.appendChild(el("p", "font-body-sm text-body-sm text-on-surface-variant dark:text-outline-variant line-clamp-2 leading-relaxed", info.description));

    var samples = el("div", "card-samples flex flex-col gap-1.5 pt-1");
    if (info.samples.length) {
      samples.appendChild(el("span", "font-label-sm text-label-sm text-tertiary dark:text-outline-variant", "예시 질문"));
      var chips = el("ul", "flex flex-wrap gap-1.5");
      info.samples.forEach(function (q) {
        chips.appendChild(el("li", "px-2.5 py-1 rounded-lg bg-surface-container dark:bg-surface-variant/20 font-body-sm text-body-sm", "“" + q + "”"));
      });
      samples.appendChild(chips);
    }
    top.appendChild(samples);
    card.appendChild(top);

    var foot = el("div", "flex items-center justify-between gap-3 pt-5 mt-4 border-t border-outline-variant/30");
    var note = el("span", "text-tertiary dark:text-outline-variant font-label-sm text-label-sm flex items-center gap-1");
    note.appendChild(icon(info.footIcon, "text-[14px]"));
    note.appendChild(document.createTextNode(info.footText));
    foot.appendChild(note);
    var start = el("button", "card-start px-4 py-2 rounded-xl bg-surface-container-high hover:bg-primary hover:text-on-primary text-on-surface font-label-md text-label-md flex items-center gap-1.5 transition-all shadow-sm active:scale-95 shrink-0");
    start.type = "button";
    start.appendChild(el("span", "", "에이전트 시작하기"));
    start.appendChild(icon("arrow_forward"));
    start.addEventListener("click", function () { location.assign(workspaceUrl(info.agentId)); });
    foot.appendChild(start);
    card.appendChild(foot);
    return card;
  }

  function presetInfo(item) {
    var meta = API.presetMeta[item.preset_id] || {};
    return {
      agentId: item.agent_id, presetId: item.preset_id, emoji: meta.emoji || API.customEmoji,
      title: item.title, subtitle: item.preset_id, description: item.description || "",
      samples: item.sample_questions || [], chunkCount: item.chunk_count || 0,
      footIcon: "lock", footText: (meta.category || "기본") + " · 기본 프리셋"
    };
  }

  function customInfo(agent) {
    var h = hoursLeft(agent.expires_at);
    return {
      agentId: agent.agent_id, presetId: null, emoji: API.customEmoji,
      title: agent.name, subtitle: agent.agent_id,
      description: "이 브라우저에서 만든 상담원입니다.",
      samples: [], chunkCount: agent.chunk_count || 0,
      footIcon: "schedule", footText: h === null ? "내 상담원" : h + "시간 뒤 자동으로 지워집니다"
    };
  }

  async function loadCustomAgents() {
    var ids = API.myAgents.list();
    var results = await Promise.all(ids.map(function (id) {
      return API.request("GET", "/api/agents/" + encodeURIComponent(id));
    }));
    var out = [];
    results.forEach(function (res, i) {
      if (res.ok && res.data) { out.push(res.data); }
      else if (res.status === 404) { API.myAgents.remove(ids[i]); }
    });
    return out;
  }

  function addCard(info, category) {
    var node = buildCard(info);
    var text = [info.title, info.description, info.samples.join(" "), info.subtitle].join(" ").toLowerCase();
    cards.push({ el: node, category: category, text: text });
    $("agents-grid").appendChild(node);
  }

  function applyFilter() {
    if (!state.listOk) {
      show($("agents-grid"), false);
      show($("no-results-view"), false);
      return;
    }
    var q = state.query.trim().toLowerCase();
    var visible = 0;
    cards.forEach(function (c) {
      var okCat = state.category === "all" || state.category === c.category;
      var okText = !q || c.text.indexOf(q) >= 0;
      c.el.hidden = !(okCat && okText);
      if (!c.el.hidden) { visible += 1; }
    });
    show($("agents-grid"), visible > 0);
    show($("no-results-view"), visible === 0);
  }

  function setCategory(cat) {
    state.category = cat;
    document.querySelectorAll("#category-filter-group button[data-category]").forEach(function (b) {
      var on = b.dataset.category === cat;
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.classList.toggle("bg-primary", on);
      b.classList.toggle("text-on-primary", on);
      b.classList.toggle("bg-surface-container-lowest", !on);
      b.classList.toggle("hover:bg-surface-container-high", !on);
      b.classList.toggle("text-on-surface", !on);
    });
    applyFilter();
  }

  async function loadList() {
    state.listOk = false;
    show($("skeleton-view"), true);
    show($("agents-grid"), false);
    show($("no-results-view"), false);
    show($("error-view"), false);
    var both = await Promise.all([API.request("GET", "/api/presets"), loadCustomAgents()]);
    var res = both[0];
    show($("skeleton-view"), false);
    $("agents-grid").textContent = "";
    cards = [];
    if (!res.ok || !res.data || !Array.isArray(res.data.items)) {
      $("error-message-text").textContent = API.errorText(res.error);
      show($("error-view"), true);
      return;
    }
    res.data.items.forEach(function (item) { addCard(presetInfo(item), item.preset_id); });
    both[1].forEach(function (agent) { addCard(customInfo(agent), "custom"); });
    state.listOk = true;
    applyFilter();
  }

  // ---------- modal ----------
  function csvRows(text) {
    var lines = text.split(/\r?\n/).filter(function (l) { return l.trim().length > 0; });
    if (lines.length && /^\s*"?(질문|question)"?\s*,\s*"?(답변|answer)"?/i.test(lines[0])) { lines.shift(); }
    return lines.length;
  }

  function updateCounters() {
    var name = $("modal-agent-name").value;
    $("agent-name-counter").textContent = name.length + " / " + NAME_MAX + "자";
    var text = $("text-knowledge-input").value;
    $("text-knowledge-counter").textContent = num(text.length) + " / " + num(limits.max_text_chars) + "자";
    $("text-knowledge-counter").classList.toggle("text-error", text.length > limits.max_text_chars);
    var csv = $("csv-raw-input").value;
    var rows = csvRows(csv);
    $("csv-meta-counter").textContent = num(rows) + "행 / " + num(csv.length) + "자";
    $("csv-meta-counter").classList.toggle("text-error", rows > limits.max_csv_rows || csv.length > limits.max_csv_chars);
  }

  function setMode(mode) {
    state.mode = mode;
    [["text", "tab-mode-text", "pane-mode-text"], ["csv", "tab-mode-csv", "pane-mode-csv"]].forEach(function (m) {
      var on = m[0] === mode;
      var tab = $(m[1]);
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.classList.toggle("bg-surface-container-lowest", on);
      tab.classList.toggle("text-primary", on);
      tab.classList.toggle("shadow-sm", on);
      tab.classList.toggle("text-on-surface-variant", !on);
      show($(m[2]), on);
    });
  }

  function clearErrors() {
    show($("modal-error-box"), false);
    $("modal-error-msg").textContent = "";
    show($("agent-name-error"), false);
  }

  function showError(message) {
    $("modal-error-msg").textContent = message;
    show($("modal-error-box"), true);
    $("modal-error-box").scrollIntoView({ block: "nearest" });
  }

  function showNameError(message) {
    $("agent-name-error-text").textContent = message;
    show($("agent-name-error"), true);
  }

  function openModal() {
    clearErrors();
    show($("create-agent-modal"), true);
    document.body.classList.add("overflow-hidden");
    updateCounters();
    $("modal-agent-name").focus();
  }

  function closeModal() {
    if (state.busy) { return; }
    show($("create-agent-modal"), false);
    document.body.classList.remove("overflow-hidden");
    $("btn-hero-create").focus();
  }

  function setAdvanced(open) {
    $("btn-toggle-advanced").setAttribute("aria-expanded", open ? "true" : "false");
    show($("advanced-settings-content"), open);
    $("accordion-icon").textContent = open ? "expand_less" : "expand_more";
  }

  async function readCsvFile(file) {
    if (!file) { return; }
    var text = "";
    try { text = await file.text(); } catch (e) { text = ""; }
    $("csv-raw-input").value = text.replace(/^﻿/, "");
    $("csv-file-name").textContent = file.name;
    updateCounters();
  }

  function downloadSample() {
    var blob = new Blob([SAMPLE_CSV], { type: "text/csv;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = el("a");
    a.href = url;
    a.download = "faq-sample.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function buildBody() {
    var name = $("modal-agent-name").value.trim();
    if (!name) { return { nameError: "상담원 이름을 한 글자 이상 입력해 주세요." }; }
    if (name.length > NAME_MAX) { return { nameError: "상담원 이름은 " + NAME_MAX + "자까지 쓸 수 있습니다." }; }

    var knowledge;
    if (state.mode === "csv") {
      var csv = $("csv-raw-input").value;
      if (!csv.trim()) { return { error: "FAQ CSV 파일을 고르거나 CSV 내용을 붙여넣어 주세요." }; }
      if (csv.length > limits.max_csv_chars) { return { error: "CSV는 " + num(limits.max_csv_chars) + "자까지 넣을 수 있습니다." }; }
      if (csvRows(csv) > limits.max_csv_rows) { return { error: "CSV는 " + num(limits.max_csv_rows) + "행까지 넣을 수 있습니다." }; }
      knowledge = { kind: "faq_csv", csv: csv };
    } else {
      var text = $("text-knowledge-input").value;
      if (!text.trim()) { return { error: "자료를 넣어 주세요. 안내문이나 규정 텍스트를 붙여넣으면 됩니다." }; }
      if (text.length > limits.max_text_chars) { return { error: "텍스트는 " + num(limits.max_text_chars) + "자까지 넣을 수 있습니다." }; }
      knowledge = { kind: "text", text: text };
    }

    var body = { name: name, knowledge: knowledge };
    if (!state.options) { return { body: body }; }

    var topics = $("setting-avoid-topics").value.split(/[,，]/)
      .map(function (t) { return t.trim(); })
      .filter(function (t) { return t.length > 0; });
    if (topics.length > limits.max_avoid_topics) {
      return { error: "답하지 않을 주제는 " + limits.max_avoid_topics + "개까지 넣을 수 있습니다." };
    }
    for (var i = 0; i < topics.length; i += 1) {
      if (topics[i].length > limits.max_avoid_topic_chars) {
        return { error: "답하지 않을 주제는 하나에 " + limits.max_avoid_topic_chars + "자까지 쓸 수 있습니다." };
      }
    }
    var handoff = $("setting-handoff-text").value.trim();
    if (handoff.length > limits.max_handoff_message_chars) {
      return { error: "담당자 안내 문구는 " + limits.max_handoff_message_chars + "자까지 쓸 수 있습니다." };
    }
    var settings = { avoid_topics: topics, summary: $("toggle-external-ai").checked };
    [["setting-agent-tone", "tone"], ["setting-answer-length", "answer_length"],
      ["setting-agent-voice", "voice"], ["setting-fallback-strategy", "when_unknown"]].forEach(function (p) {
      var v = $(p[0]).value;
      if (v) { settings[p[1]] = v; }
    });
    if (handoff) { settings.handoff_message = handoff; }
    body.settings = settings;
    return { body: body };
  }

  var FIELD_LABEL = {
    tone: "말투", answer_length: "답 길이", voice: "목소리", when_unknown: "모르는 질문 대응",
    handoff_message: "담당자 안내 문구", avoid_topics: "답하지 않을 주제", summary: "요약해서 답하기",
    persona_name: "상담원 호칭", knowledge: "자료", text: "자료", csv: "CSV"
  };

  function showValidation(error) {
    var loc = (error && error.loc) || [];
    var message = error && error.message ? error.message : API.errorText(error);
    if (loc.indexOf("name") >= 0) {
      showNameError("상담원 이름을 확인해 주세요 (1~" + NAME_MAX + "자).");
      showError(message);
      return;
    }
    var field = loc.slice().reverse().find(function (k) { return FIELD_LABEL[k]; });
    showError(field ? FIELD_LABEL[field] + ": " + message : message);
    if (loc.indexOf("settings") >= 0) { setAdvanced(true); }
  }

  function setBusy(on) {
    state.busy = on;
    $("modal-submit-btn").disabled = on;
    show($("submit-spinner"), on);
    show($("submit-icon"), !on);
    $("submit-text").textContent = on ? "만드는 중…" : SUBMIT_LABEL;
  }

  async function onSubmit(ev) {
    ev.preventDefault();
    if (state.busy) { return; }
    clearErrors();
    var built = buildBody();
    if (built.nameError) {
      showNameError(built.nameError);
      showError("입력 값을 확인해 주세요.");
      return;
    }
    if (built.error) {
      showError(built.error);
      return;
    }
    setBusy(true);
    var res = await API.request("POST", "/api/agents", built.body);
    if (res.ok && res.data && res.data.agent_id) {
      var id = res.data.agent_id;
      API.myAgents.add(id);
      try {
        sessionStorage.setItem("va:warnings:" + id, JSON.stringify(res.data.warnings || []));
      } catch (e) { /* storage unavailable */ }
      location.assign(workspaceUrl(id));
      return;
    }
    setBusy(false);
    if (res.error && res.error.code === "validation") { showValidation(res.error); }
    else { showError(API.errorText(res.error)); }
  }

  // ---------- init ----------
  function bind() {
    $("theme-toggle").addEventListener("click", function () { API.theme.toggle(); });
    $("btn-hero-create").addEventListener("click", openModal);
    $("modal-close-x").addEventListener("click", closeModal);
    $("modal-cancel-btn").addEventListener("click", closeModal);
    $("create-agent-modal").addEventListener("click", function (ev) {
      if (ev.target === ev.currentTarget) { closeModal(); }
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && !$("create-agent-modal").hidden) { closeModal(); }
    });
    $("create-agent-form").addEventListener("submit", onSubmit);
    $("tab-mode-text").addEventListener("click", function () { setMode("text"); });
    $("tab-mode-csv").addEventListener("click", function () { setMode("csv"); });
    ["modal-agent-name", "text-knowledge-input", "csv-raw-input"].forEach(function (id) {
      $(id).addEventListener("input", updateCounters);
    });
    $("btn-toggle-advanced").addEventListener("click", function () {
      setAdvanced($("btn-toggle-advanced").getAttribute("aria-expanded") !== "true");
    });
    $("btn-download-sample-csv").addEventListener("click", downloadSample);

    var drop = $("csv-drop-zone");
    var fileInput = $("csv-file-input");
    drop.addEventListener("click", function (ev) {
      if (ev.target !== fileInput) { fileInput.click(); }
    });
    drop.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fileInput.click(); }
    });
    drop.addEventListener("dragover", function (ev) { ev.preventDefault(); drop.classList.add("border-primary"); });
    drop.addEventListener("dragleave", function () { drop.classList.remove("border-primary"); });
    drop.addEventListener("drop", function (ev) {
      ev.preventDefault();
      drop.classList.remove("border-primary");
      var f = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
      readCsvFile(f);
    });
    fileInput.addEventListener("change", function () {
      readCsvFile(fileInput.files && fileInput.files[0]);
    });

    $("agent-search-input").addEventListener("input", function (ev) {
      state.query = ev.target.value;
      applyFilter();
    });
    document.querySelectorAll("#category-filter-group button[data-category]").forEach(function (b) {
      b.addEventListener("click", function () { setCategory(b.dataset.category); });
    });
    $("btn-reset-filters").addEventListener("click", function () {
      $("agent-search-input").value = "";
      state.query = "";
      setCategory("all");
    });
    $("btn-retry-fetch").addEventListener("click", function () {
      loadList().then(function () { setCategory(state.category); });
    });
  }

  function init() {
    bind();
    setMode("text");
    setAdvanced(false);
    setCategory("all");
    updateCounters();
    loadHealth();
    loadOptions();
    loadList().catch(function () {
      show($("skeleton-view"), false);
      $("error-message-text").textContent = API.errorText(null);
      show($("error-view"), true);
    }).then(function () {
      setCategory(state.category);
      document.body.dataset.ready = "true";
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
