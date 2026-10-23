// Settings tab: fills the form from GET /api/options + agent.settings, saves changed fields with
// PATCH (custom agents only; presets are read-only), and offers the same delete as the header menu.
(function () {
  "use strict";

  var API = window.StudioAPI;
  var WS = window.WS;

  var FIELD_LABEL = {
    persona_name: "상담원 이름",
    tone: "말투",
    answer_length: "답 길이",
    voice: "목소리",
    when_unknown: "모르는 질문에는",
    handoff_message: "담당자 안내 문구",
    avoid_topics: "피할 주제",
    summary: "요약해서 답하기"
  };

  var INPUT_IDS = [
    "setting-input-name", "setting-input-tone", "setting-input-length", "setting-select-voice",
    "setting-unknown-behavior", "setting-handoff-message", "setting-avoid-topics", "setting-summary-toggle"
  ];

  var saving = false;
  var statusTimer = null;

  function $(id) { return document.getElementById(id); }

  function show(el, on) {
    if (el) { el.hidden = !on; }
  }

  // ---------- form fill ----------
  function fillSelect(select, choices, value) {
    select.textContent = "";
    (choices || []).forEach(function (c) {
      var opt = document.createElement("option");
      opt.value = String(c.value);
      opt.textContent = c.label != null ? String(c.label) : String(c.value);
      if (c.available === false) {
        opt.disabled = true;
        opt.textContent += " (사용 불가)";
      }
      select.appendChild(opt);
    });
    if (value != null) { select.value = String(value); }
  }

  function currentSettings() {
    var agent = WS.state.agent;
    var opts = WS.state.options || {};
    var base = {};
    var defaults = opts.defaults || {};
    Object.keys(defaults).forEach(function (k) { base[k] = defaults[k]; });
    var s = (agent && agent.settings) || {};
    Object.keys(s).forEach(function (k) { base[k] = s[k]; });
    return base;
  }

  function applyLimits() {
    var limits = (WS.state.options && WS.state.options.limits) || {};
    if (limits.max_persona_name_chars) { $("setting-input-name").maxLength = limits.max_persona_name_chars; }
    if (limits.max_handoff_message_chars) { $("setting-handoff-message").maxLength = limits.max_handoff_message_chars; }
  }

  function syncNotice() {
    var toggle = $("setting-summary-toggle");
    show($("summary-privacy-notice"), toggle.checked || !toggle.disabled);
  }

  function fillForm() {
    var opts = WS.state.options || {};
    var s = currentSettings();
    $("setting-input-name").value = s.persona_name != null ? String(s.persona_name) : "";
    fillSelect($("setting-input-tone"), opts.tone, s.tone);
    fillSelect($("setting-input-length"), opts.answer_length, s.answer_length);
    fillSelect($("setting-select-voice"), opts.voices, s.voice);
    fillSelect($("setting-unknown-behavior"), opts.when_unknown, s.when_unknown);
    $("setting-handoff-message").value = s.handoff_message != null ? String(s.handoff_message) : "";
    $("setting-avoid-topics").value = Array.isArray(s.avoid_topics) ? s.avoid_topics.join(", ") : "";
    $("setting-summary-toggle").checked = !!s.summary;
    applyLimits();
  }

  function applyMode() {
    var preset = WS.isPreset();
    var summaryOk = !!(WS.state.options && WS.state.options.summary_available);
    INPUT_IDS.forEach(function (id) {
      var el = $(id);
      if (el) { el.disabled = preset; }
    });
    if (!summaryOk) { $("setting-summary-toggle").disabled = true; }
    show($("preset-readonly-banner"), preset);
    show($("settings-save-btn"), !preset);
    show($("settings-delete-section"), !preset);
    syncNotice();
  }

  function render() {
    setError(null);
    fillForm();
    applyMode();
  }

  // ---------- messages ----------
  function setError(error) {
    var box = $("settings-error");
    if (!error) {
      box.textContent = "";
      show(box, false);
      return;
    }
    var text = API.errorText(error);
    var loc = error.loc || [];
    var field = loc.length ? loc[loc.length - 1] : "";
    if (field && Object.prototype.hasOwnProperty.call(FIELD_LABEL, field)) {
      text = FIELD_LABEL[field] + ": " + text;
    }
    box.textContent = text;
    show(box, true);
  }

  function setStatus(text) {
    var el = $("settings-status");
    el.textContent = text || "";
    if (statusTimer) { clearTimeout(statusTimer); statusTimer = null; }
    if (text) {
      statusTimer = setTimeout(function () { el.textContent = ""; }, 5000);
    }
  }

  // ---------- save ----------
  function readForm() {
    var topics = ($("setting-avoid-topics").value || "").split(",").map(function (t) {
      return t.trim();
    }).filter(function (t) { return t.length > 0; });
    return {
      persona_name: ($("setting-input-name").value || "").trim(),
      tone: $("setting-input-tone").value,
      answer_length: $("setting-input-length").value,
      voice: $("setting-select-voice").value,
      when_unknown: $("setting-unknown-behavior").value,
      handoff_message: ($("setting-handoff-message").value || "").trim(),
      avoid_topics: topics,
      summary: $("setting-summary-toggle").checked
    };
  }

  function sameValue(a, b) {
    if (Array.isArray(a) || Array.isArray(b)) {
      var x = Array.isArray(a) ? a : [];
      var y = Array.isArray(b) ? b : [];
      if (x.length !== y.length) { return false; }
      for (var i = 0; i < x.length; i += 1) {
        if (String(x[i]) !== String(y[i])) { return false; }
      }
      return true;
    }
    return a === b;
  }

  function changedFields() {
    var before = currentSettings();
    var after = readForm();
    var patch = {};
    Object.keys(after).forEach(function (k) {
      if (!sameValue(before[k], after[k])) { patch[k] = after[k]; }
    });
    return patch;
  }

  async function onSave(ev) {
    if (ev) { ev.preventDefault(); }
    if (saving || !WS.state.agent) { return; }
    if (WS.isPreset()) {
      setError({ code: "preset_read_only", message: "프리셋 상담원은 바꿀 수 없습니다." });
      return;
    }
    setError(null);
    var patch = changedFields();
    if (!Object.keys(patch).length) {
      setStatus("바뀐 내용이 없습니다.");
      return;
    }
    saving = true;
    var btn = $("settings-save-btn");
    btn.disabled = true;
    setStatus("저장하는 중…");
    var res = await API.request("PATCH", "/api/agents/" + encodeURIComponent(WS.state.agentId) + "/settings", patch);
    saving = false;
    btn.disabled = false;
    if (res.ok && res.data) {
      WS.setAgent(res.data);
      render();
      setStatus("저장했습니다. 다음 질문부터 적용됩니다.");
      API.toast("설정을 저장했습니다.", "success");
      return;
    }
    setStatus("");
    setError(res.error || { code: "internal" });
  }

  function onDelete() {
    var menuBtn = $("menu-delete-agent");
    if (menuBtn && WS.state.agent && !WS.isPreset()) { menuBtn.click(); }
  }

  // ---------- bind ----------
  function init() {
    $("settings-form").addEventListener("submit", onSave);
    $("setting-summary-toggle").addEventListener("change", syncNotice);
    $("settings-delete-btn").addEventListener("click", onDelete);
    WS.on("ready", render);
    WS.on("tab", function (p) {
      if (p && p.name === "settings" && WS.state.agent && !saving) { applyMode(); }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
