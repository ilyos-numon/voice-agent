(function () {
  "use strict";

  var VA = window.VA;
  var $ = function (id) { return document.getElementById(id); };

  var limits = {
    max_text_chars: 20000,
    max_csv_chars: 100000,
    agent_ttl_hours: 24,
    max_avoid_topics: 10,
    max_avoid_topic_chars: 20,
    max_persona_name_chars: 20,
    max_handoff_message_chars: 100
  };
  var csvText = "";
  var busy = false;
  var CREATE_LABEL = "상담원 만들기";

  function fmtHours(h) {
    var n = Number(h);
    if (!(n > 0)) { return "24"; }
    return String(Math.round(n * 10) / 10);
  }

  // ---------- presets ----------
  function renderPresets(items) {
    var list = $("preset-list");
    list.textContent = "";
    items.forEach(function (item) {
      var btn = VA.el("button", "preset-card");
      btn.type = "button";
      btn.dataset.presetId = item.preset_id;
      btn.appendChild(VA.el("span", "preset-title", item.title));
      btn.appendChild(VA.el("span", "preset-desc", item.description));
      var sample = (item.sample_questions || [])[0];
      if (sample) { btn.appendChild(VA.el("span", "preset-sample", sample)); }
      btn.addEventListener("click", function () {
        location.assign(VA.talkUrl(item.agent_id));
      });
      list.appendChild(btn);
    });
  }

  async function loadPresets() {
    var res = await VA.api("GET", "/api/presets");
    if (!res.ok || !res.data || !Array.isArray(res.data.items)) {
      $("preset-list").textContent = "";
      $("preset-error").textContent = VA.errorText(res.error);
      return;
    }
    renderPresets(res.data.items);
  }

  // ---------- options ----------
  function fillSelect(sel, choices, value) {
    sel.textContent = "";
    (choices || []).forEach(function (c) {
      var opt = VA.el("option", null, c.label);
      opt.value = c.value;
      if (c.available === false) { opt.disabled = true; }
      sel.appendChild(opt);
    });
    if (value !== undefined && value !== null) { sel.value = value; }
    if (sel.selectedIndex >= 0 && sel.options[sel.selectedIndex].disabled) {
      for (var i = 0; i < sel.options.length; i += 1) {
        if (!sel.options[i].disabled) { sel.selectedIndex = i; break; }
      }
    }
  }

  function applyOptions(o) {
    var d = o.defaults || {};
    Object.keys(o.limits || {}).forEach(function (k) { limits[k] = o.limits[k]; });
    fillSelect($("tone"), o.tone, d.tone);
    fillSelect($("voice"), o.voices, d.voice);
    fillSelect($("answer-length"), o.answer_length, d.answer_length);
    fillSelect($("when-unknown"), o.when_unknown, d.when_unknown);
    if (d.persona_name) { $("persona-name").value = d.persona_name; }
    if (d.handoff_message) { $("handoff-message").value = d.handoff_message; }
    $("persona-name").maxLength = limits.max_persona_name_chars;
    $("handoff-message").maxLength = limits.max_handoff_message_chars;
    var hours = fmtHours(limits.agent_ttl_hours);
    $("ttl-note").textContent = "만든 상담원은 " + hours + "시간 뒤 지워집니다.";
    $("privacy-note").textContent = "넣은 자료는 이 상담원 답에만 쓰고 " + hours + "시간 뒤 지웁니다.";
  }

  async function loadOptions() {
    var res = await VA.api("GET", "/api/options");
    if (!res.ok || !res.data) {
      $("create-error").textContent = VA.errorText(res.error);
      $("create-btn").disabled = true;
      return;
    }
    applyOptions(res.data);
    updateKind();
    updateUnknown();
  }

  // ---------- form ----------
  function kind() { return $("kn-kind").value; }

  function maxChars() {
    return kind() === "faq_csv" ? limits.max_csv_chars : limits.max_text_chars;
  }

  function currentKnowledge() {
    return kind() === "faq_csv" ? csvText : $("kn-text").value;
  }

  function updateCount() {
    var n = currentKnowledge().length;
    $("kn-count").textContent = n.toLocaleString("ko-KR") + " / " +
      Number(maxChars()).toLocaleString("ko-KR") + "자";
  }

  function updateKind() {
    var isCsv = kind() === "faq_csv";
    $("kn-text-field").hidden = isCsv;
    $("kn-file-field").hidden = !isCsv;
    updateCount();
  }

  function updateUnknown() {
    $("handoff-field").hidden = $("when-unknown").value !== "handoff";
  }

  async function readFile() {
    var f = $("kn-file").files && $("kn-file").files[0];
    csvText = "";
    if (f) {
      try { csvText = await f.text(); } catch (e) { csvText = ""; }
    }
    updateCount();
  }

  function setBusy(on) {
    busy = on;
    var btn = $("create-btn");
    btn.disabled = on;
    btn.textContent = on ? "만드는 중…" : CREATE_LABEL;
  }

  function buildBody() {
    var content = currentKnowledge();
    if (!content.trim()) { return { error: "자료를 넣어 주세요." }; }
    if (content.length > maxChars()) {
      return { error: "자료는 " + Number(maxChars()).toLocaleString("ko-KR") + "자까지 넣을 수 있습니다." };
    }
    var topics = $("avoid-topics").value.split(/[,，]/)
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

    var knowledge = { kind: kind() };
    if (kind() === "faq_csv") { knowledge.csv = content; } else { knowledge.text = content; }

    var settings = { avoid_topics: topics };
    ["tone", "voice", "answer-length", "when-unknown"].forEach(function (id) {
      var v = $(id).value;
      if (v) { settings[id.replace("-", "_")] = v; }
    });
    var persona = $("persona-name").value.trim();
    if (persona) { settings.persona_name = persona; }
    var handoff = $("handoff-message").value.trim();
    if (handoff) { settings.handoff_message = handoff; }

    var body = { knowledge: knowledge, settings: settings };
    var name = $("agent-name").value.trim();
    if (name) { body.name = name; }
    return { body: body };
  }

  async function onSubmit(ev) {
    ev.preventDefault();
    if (busy) { return; }
    $("create-error").textContent = "";
    var built = buildBody();
    if (built.error) {
      $("create-error").textContent = built.error;
      return;
    }
    setBusy(true);
    var res = await VA.api("POST", "/api/agents", built.body);
    if (res.ok && res.data && res.data.agent_id) {
      var id = res.data.agent_id;
      var warnings = (res.data.warnings || []).map(function (w) { return w.message; });
      try {
        sessionStorage.setItem("va:warnings:" + id, JSON.stringify(warnings));
      } catch (e) { /* storage unavailable */ }
      location.assign(VA.talkUrl(id));
      return;
    }
    $("create-error").textContent = VA.errorText(res.error);
    setBusy(false);
  }

  function init() {
    $("kn-kind").addEventListener("change", updateKind);
    $("kn-text").addEventListener("input", updateCount);
    $("kn-file").addEventListener("change", readFile);
    $("when-unknown").addEventListener("change", updateUnknown);
    $("create-form").addEventListener("submit", onSubmit);
    updateKind();
    Promise.all([loadPresets(), loadOptions()]).catch(function () {
      /* errors are already drawn */
    }).then(function () {
      document.body.dataset.ready = "true";
    });
  }

  init();
})();
