// A/B tab: asks one question with two partial settings (POST …/compare) and shows both answers,
// the B − A differences and the server notes side by side. Uses window.StudioAPI and window.WS only.
(function () {
  "use strict";

  var API = window.StudioAPI;
  var SIDES = ["a", "b"];
  var MAX_CHIPS = 3;
  var CHIP_CLASS = "ab-sample-chip px-2.5 py-1 rounded-full bg-surface-container hover:bg-surface-container-high " +
    "border border-outline-variant/40 text-[11px] sm:text-xs text-on-surface transition-colors";

  var bound = false;
  var busy = false;
  var player = null;
  var maxChars = 500;

  function $(id) { return document.getElementById(id); }

  function show(el, on) {
    if (el) { el.hidden = !on; }
  }

  function clear(el) {
    while (el && el.firstChild) { el.removeChild(el.firstChild); }
  }

  function node(tag, className, text) {
    var el = document.createElement(tag);
    if (className) { el.className = className; }
    if (text != null) { el.textContent = String(text); }
    return el;
  }

  function agentPath(suffix) {
    return "/api/agents/" + encodeURIComponent(WS.state.agentId) + suffix;
  }

  // ---------- question ----------
  function updateCounter() {
    var q = $("ab-question");
    var c = $("ab-char-counter");
    if (q && c) { c.textContent = q.value.length + " / " + maxChars; }
  }

  function renderChips(questions) {
    var box = $("ab-sample-chips");
    if (!box) { return; }
    clear(box);
    questions.slice(0, MAX_CHIPS).forEach(function (text) {
      if (!text) { return; }
      var b = node("button", CHIP_CLASS, text);
      b.type = "button";
      b.addEventListener("click", function () {
        var q = $("ab-question");
        if (!q) { return; }
        q.value = String(text).slice(0, maxChars);
        updateCounter();
        q.focus();
      });
      box.appendChild(b);
    });
  }

  async function loadChips() {
    var preset = WS.state.preset;
    if (preset && Array.isArray(preset.sample_questions) && preset.sample_questions.length) {
      renderChips(preset.sample_questions);
      return;
    }
    var res = await API.request("GET", agentPath("/chunks?offset=0&limit=" + MAX_CHIPS));
    if (res.ok && res.data && Array.isArray(res.data.items)) {
      renderChips(res.data.items.map(function (it) { return it && it.title; }));
    }
  }

  // ---------- settings ----------
  function fillSelect(sel, choices, isVoice) {
    if (!sel) { return; }
    (choices || []).forEach(function (c) {
      if (!c) { return; }
      var opt = document.createElement("option");
      opt.value = String(c.value);
      opt.textContent = String(c.label || c.value);
      if (isVoice && c.available === false) {
        opt.disabled = true;
        opt.textContent += " (사용 불가)";
      }
      sel.appendChild(opt);
    });
  }

  function fillSettings(options) {
    var summaryOk = !!(options && options.summary_available);
    var current = (WS.state.agent && WS.state.agent.settings) || {};
    SIDES.forEach(function (s) {
      fillSelect($("ab-" + s + "-tone"), options && options.tone, false);
      fillSelect($("ab-" + s + "-length"), options && options.answer_length, false);
      fillSelect($("ab-" + s + "-voice"), options && options.voices, true);
      var sum = $("ab-" + s + "-summary");
      if (sum) {
        sum.checked = !!current.summary;
        sum.disabled = !summaryOk;
        if (!summaryOk) { sum.title = "이 서버에서는 요약을 쓸 수 없습니다"; }
      }
    });
  }

  // "(기본값 유지)" (empty value) means the field is left out of the request.
  function readSide(s) {
    var out = {};
    var map = { tone: "tone", length: "answer_length", voice: "voice" };
    Object.keys(map).forEach(function (k) {
      var sel = $("ab-" + s + "-" + k);
      if (sel && sel.value) { out[map[k]] = sel.value; }
    });
    var sum = $("ab-" + s + "-summary");
    var current = (WS.state.agent && WS.state.agent.settings) || {};
    if (sum && !sum.disabled && sum.checked !== !!current.summary) { out.summary = sum.checked; }
    return out;
  }

  // ---------- run ----------
  function showError(error) {
    var box = $("ab-error");
    if (!box) { return; }
    box.textContent = typeof error === "string" ? error : API.errorText(error);
    show(box, true);
  }

  function hideError() {
    var box = $("ab-error");
    if (box) { box.textContent = ""; }
    show(box, false);
  }

  function setBusy(on) {
    busy = on;
    var btn = $("ab-run-btn");
    if (btn) { btn.disabled = on; }
    show($("ab-spinner"), on);
  }

  function stopPlayer() {
    if (player) { player.stop(); player = null; }
  }

  async function ensureSession() {
    if (WS.state.sessionId) { return WS.state.sessionId; }
    return WS.newSession();
  }

  async function run() {
    if (busy) { return; }
    var q = $("ab-question");
    var question = q ? q.value.trim() : "";
    hideError();
    if (!question) {
      showError("비교할 질문을 입력해 주세요.");
      return;
    }
    stopPlayer();
    setBusy(true);
    var sessionId;
    try {
      sessionId = await ensureSession();
    } catch (e) {
      setBusy(false);
      showError(e);
      return;
    }
    var body = { session_id: sessionId, question: question, a: readSide("a"), b: readSide("b") };
    var res = await API.request("POST", agentPath("/compare"), body);
    setBusy(false);
    if (!res.ok || !res.data) {
      var err = res.error || { code: "internal" };
      showError(err);
      if (err.code === "session_not_found") {
        WS.newSession().catch(function () { /* the next run reports it */ });
      } else if (err.code === "question_limit") {
        WS.setQuota(0);
      }
      return;
    }
    renderResult(res.data);
    if (typeof res.data.questions_left === "number") { WS.setQuota(res.data.questions_left); }
  }

  // ---------- result ----------
  function signed(n, unit) {
    var v = Number(n) || 0;
    if (v === 0) { return "0" + unit; }
    return (v > 0 ? "+" : "−") + Math.abs(v) + unit;
  }

  function signedMs(ms) {
    var v = Number(ms) || 0;
    if (Math.round(v) === 0) { return "0ms"; }
    return (v > 0 ? "+" : "−") + API.formatMs(Math.abs(v));
  }

  function diffBadge(label, value) {
    var cell = node("div", "p-2.5 rounded-xl bg-surface border border-outline-variant/30 flex flex-col gap-0.5");
    cell.appendChild(node("span", "text-[11px] text-on-surface-variant", label));
    cell.appendChild(node("span", "font-mono font-semibold text-on-surface", value));
    return cell;
  }

  function sortedSentences(side) {
    var list = Array.isArray(side.sentences) ? side.sentences.slice() : [];
    list.sort(function (x, y) { return (x.index || 0) - (y.index || 0); });
    return list;
  }

  function groundedCount(side) {
    if (side.answer_kind !== "grounded") { return 0; }
    return sortedSentences(side).filter(function (s) { return s && s.supported; }).length;
  }

  function renderEvidence(box, side) {
    clear(box);
    if (side.answer_kind === "unknown") {
      box.appendChild(node("div", null, "맞는 자료가 없어 지어내지 않고 안내했습니다."));
      return;
    }
    if (side.answer_kind === "avoided") {
      box.appendChild(node("div", null, "피할 주제에 걸려 답하지 않았습니다."));
      return;
    }
    var seen = {};
    var items = [];
    sortedSentences(side).forEach(function (s) {
      (s.evidence || []).forEach(function (ev) {
        if (!ev || seen[ev.chunk_id]) { return; }
        seen[ev.chunk_id] = true;
        items.push(ev);
      });
    });
    if (!items.length) {
      box.appendChild(node("div", null, "근거가 없습니다."));
      return;
    }
    box.appendChild(node("div", "font-medium", "근거 " + items.length + "건"));
    items.forEach(function (ev) {
      var row = node("button", "block w-full text-left p-2 rounded-lg bg-surface border border-outline-variant/20 hover:border-primary/40 transition-colors");
      row.type = "button";
      row.dataset.chunkId = String(ev.chunk_id || "");
      row.appendChild(node("div", "font-medium text-on-surface", ev.title || ""));
      if (ev.quote) { row.appendChild(node("div", null, "“" + ev.quote + "”")); }
      row.addEventListener("click", function () {
        if (ev.chunk_id) { WS.focusChunk(String(ev.chunk_id)); }
      });
      box.appendChild(row);
    });
  }

  function renderColumn(col, side) {
    if (!col) { return; }
    side = side || {};
    var fa = col.querySelector(".ab-first-audio");
    if (fa) {
      var t = side.timings && side.timings.first_audio_ms;
      fa.textContent = (t == null) ? "-" : API.formatMs(t);
    }
    var sc = col.querySelector(".ab-sentence-count");
    if (sc) { sc.textContent = String(side.sentence_count == null ? "-" : side.sentence_count); }
    var cc = col.querySelector(".ab-char-count");
    if (cc) { cc.textContent = String(side.char_count == null ? "-" : side.char_count); }
    var ans = col.querySelector(".ab-answer");
    if (ans) { ans.textContent = side.answer || ""; }
    var evBox = col.querySelector(".ab-evidence");
    if (evBox) { renderEvidence(evBox, side); }

    var audio = sortedSentences(side).map(function (s) { return s && s.audio_wav_b64; });
    var playBtn = col.querySelector("button.ab-play");
    if (playBtn) {
      var hasAudio = audio.some(function (b) { return !!b; });
      playBtn.disabled = !hasAudio;
      playBtn.onclick = function () {
        stopPlayer();
        player = API.playSequence(audio);
      };
    }
  }

  function renderResult(data) {
    var a = data.a || {};
    var b = data.b || {};
    renderColumn($("ab-col-a"), a);
    renderColumn($("ab-col-b"), b);

    var diffBox = $("ab-diff");
    if (diffBox) {
      clear(diffBox);
      var d = data.diff || {};
      diffBox.appendChild(diffBadge("첫 음성까지", signedMs(d.first_audio_ms)));
      diffBox.appendChild(diffBadge("문장 수", signed(d.sentence_count, "문장")));
      diffBox.appendChild(diffBadge("글자 수", signed(d.char_count, "자")));
      diffBox.appendChild(diffBadge("근거 있는 문장", signed(groundedCount(b) - groundedCount(a), "개")));
    }

    var notes = $("ab-notes");
    if (notes) {
      clear(notes);
      (Array.isArray(data.notes) ? data.notes : []).forEach(function (n) {
        notes.appendChild(node("li", null, n));
      });
    }
    show($("ab-result"), true);
  }

  // ---------- init ----------
  function init(payload) {
    if (bound) { return; }
    bound = true;
    var options = (payload && payload.options) || WS.state.options || {};
    var limits = options.limits || {};
    if (limits.max_question_chars > 0) { maxChars = limits.max_question_chars; }

    var q = $("ab-question");
    if (q) {
      q.maxLength = maxChars;
      q.addEventListener("input", updateCounter);
      q.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
          ev.preventDefault();
          run();
        }
      });
    }
    updateCounter();
    fillSettings(options);
    loadChips();

    var btn = $("ab-run-btn");
    if (btn) { btn.addEventListener("click", function () { run(); }); }
    WS.on("tab", function (p) {
      if (p && p.name !== "abtest") { stopPlayer(); }
    });
  }

  if (window.WS) { WS.on("ready", init); }
})();
