// Workspace conversation tab: text and voice questions over the turn stream, ordered audio playback,
// per-turn receipts (timings, evidence, search candidates), queue badge, question quota and errors.
(function () {
  "use strict";

  var API = window.StudioAPI;
  var WS = window.WS;
  var MAX_RECORD_MS = 15000;
  var DEFAULT_MAX_CHARS = 500;

  var ready = false;
  var busy = false;
  var recovering = false;
  var maxChars = DEFAULT_MAX_CHARS;
  var voiceAvailable = false;
  var liveQueue = null;
  var replay = null;
  var controller = null;

  var recorder = null;
  var micStream = null;
  var recChunks = [];
  var recTimer = null;
  var recording = false;

  function $(id) { return document.getElementById(id); }

  function show(el, on) {
    if (el) { el.hidden = !on; }
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text != null) { node.textContent = String(text); }
    return node;
  }

  function icon(name, extra) {
    return el("span", "material-symbols-outlined " + (extra || "text-[14px]"), name);
  }

  function scrollDown() {
    var area = $("dialogue-scroll-area");
    if (area) { area.scrollTop = area.scrollHeight; }
  }

  // ---------- audio ----------
  function stopAudio() {
    if (liveQueue) { liveQueue.stop(); liveQueue = null; }
    if (replay) { replay.stop(); replay = null; }
  }

  function voiceLabel() {
    var agent = WS.state.agent;
    var opts = WS.state.options;
    var v = agent && agent.settings && agent.settings.voice;
    var list = (opts && opts.voices) || [];
    for (var i = 0; i < list.length; i += 1) {
      if (list[i].value === v) { return list[i].label; }
    }
    return "";
  }

  // ---------- errors / controls ----------
  function showChatError(message) {
    var box = $("chat-error");
    if (!box) { return; }
    box.textContent = message || "";
    show(box, !!message);
  }

  function refreshControls() {
    var text = $("chat-textarea").value;
    var len = text.length;
    $("char-counter").textContent = String(len);
    var blocked = !ready || busy || recording;
    $("send-btn").disabled = blocked || !text.trim() || len > maxChars;
    var mic = $("mic-btn");
    mic.disabled = !voiceAvailable || !ready || (busy && !recording);
    var chips = document.querySelectorAll("#sample-chips-container button.sample-chip");
    Array.prototype.forEach.call(chips, function (c) { c.disabled = blocked; });
  }

  function setResponding(on, text) {
    show($("responding-indicator"), on);
    if (text) { $("responding-text").textContent = text; }
  }

  function setQueueBadge(position) {
    var badge = $("queue-badge");
    if (position == null) { show(badge, false); return; }
    $("queue-badge-text").textContent = "앞에 " + position + "명";
    show(badge, true);
  }

  // ---------- turn rendering ----------
  function createTurn(questionText) {
    var turn = el("div", "ws-turn space-y-2");
    turn.dataset.state = "pending";

    var qRow = el("div", "flex justify-end");
    var q = el("div", "ws-question max-w-[85%] px-3.5 py-2 rounded-2xl rounded-tr-sm bg-primary text-white text-xs sm:text-sm leading-relaxed whitespace-pre-wrap break-words", questionText);
    qRow.appendChild(q);
    turn.appendChild(qRow);

    var aRow = el("div", "flex items-start gap-2.5 sm:gap-3");
    var avatar = el("div", "w-8 h-8 rounded-lg bg-primary-fixed flex items-center justify-center text-sm shrink-0");
    var ga = $("greeting-avatar");
    avatar.textContent = ga ? ga.textContent : API.customEmoji;
    var bubble = el("div", "ws-bubble flex-1 min-w-0 max-w-[85%] bg-surface p-3 rounded-2xl rounded-tl-sm border border-outline-variant/40 space-y-2");
    var answer = el("div", "ws-answer text-xs sm:text-sm text-on-surface leading-relaxed");
    bubble.appendChild(answer);
    aRow.appendChild(avatar);
    aRow.appendChild(bubble);
    aRow.hidden = true;
    turn.appendChild(aRow);

    $("messages-list").appendChild(turn);
    scrollDown();
    return {
      root: turn,
      question: q,
      answerRow: aRow,
      bubble: bubble,
      answer: answer,
      meta: null,
      sentences: [],
      sentenceEls: [],
      firstSpeakMs: null,
      receipt: null
    };
  }

  function ensureAnswerVisible(t) {
    t.answerRow.hidden = false;
  }

  function addSentence(t, data) {
    var idx = Number(data.index);
    var kind = t.meta ? t.meta.answer_kind : null;
    var span = el("span", "ws-sentence inline");
    span.dataset.index = String(idx);
    span.dataset.supported = data.supported ? "true" : "false";
    span.appendChild(document.createTextNode(String(data.text || "")));
    if (kind === "grounded" && !data.supported) {
      var mark = el("span", "ws-unsupported-mark inline-flex items-center gap-0.5 ml-1 px-1.5 py-0.5 rounded bg-error-container/50 text-on-error-container text-[10px] font-medium align-middle");
      mark.appendChild(icon("warning", "text-[11px]"));
      mark.appendChild(el("span", "", "근거 없음"));
      span.appendChild(mark);
    }
    span.appendChild(document.createTextNode(" "));
    t.answer.appendChild(span);
    t.sentences[idx] = data;
    t.sentenceEls[idx] = span;
    if (idx === 0 && data.speak_ms != null) { t.firstSpeakMs = data.speak_ms; }
  }

  function timingRow(label, ms) {
    var item = el("span", "inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-surface-container text-on-surface-variant");
    item.appendChild(el("span", "", label));
    item.appendChild(el("strong", "text-on-surface font-semibold", API.formatMs(ms)));
    return item;
  }

  function renderTimings(box, timings, isAudio, done) {
    box.textContent = "";
    var head = el("div", "flex items-center gap-1 text-[11px] font-semibold text-on-surface mb-1");
    head.appendChild(icon("schedule", "text-[13px] text-primary"));
    head.appendChild(el("span", "", "걸린 시간"));
    box.appendChild(head);
    var row = el("div", "flex flex-wrap gap-1.5 text-[11px]");
    timings = timings || {};
    if (isAudio || (timings.listen_ms || 0) >= 1) { row.appendChild(timingRow("듣기", timings.listen_ms)); }
    row.appendChild(timingRow("검색", timings.search_ms));
    row.appendChild(timingRow("생각", timings.think_ms));
    if (done) {
      row.appendChild(timingRow("말하기", timings.speak_ms));
      row.appendChild(timingRow("첫 음성까지", timings.first_audio_ms));
      row.appendChild(timingRow("전체", timings.total_ms));
      if (timings.queue_ms) { row.appendChild(timingRow("대기", timings.queue_ms)); }
    }
    box.appendChild(row);
  }

  function ensureReceipt(t) {
    if (t.receipt) { return t.receipt; }
    var details = el("details", "ws-receipt rounded-xl border border-outline-variant/40 bg-surface-container-low/60 text-xs");
    var summary = el("summary", "cursor-pointer select-none px-3 py-2 font-medium text-on-surface-variant flex items-center gap-1");
    summary.appendChild(icon("search", "text-[14px] text-primary"));
    summary.appendChild(el("span", "", "이 답의 영수증"));
    details.appendChild(summary);
    var body = el("div", "px-3 pb-3 space-y-3");
    var timings = el("div", "ws-timings");
    var evidence = el("div", "ws-evidence space-y-1.5");
    var candidates = el("div", "ws-candidates space-y-1");
    body.appendChild(timings);
    body.appendChild(evidence);
    body.appendChild(candidates);
    details.appendChild(body);
    t.bubble.appendChild(details);
    t.receipt = { details: details, timings: timings, evidence: evidence, candidates: candidates };
    return t.receipt;
  }

  function renderCandidates(t) {
    var box = ensureReceipt(t).candidates;
    box.textContent = "";
    var list = (t.meta && t.meta.candidates) || [];
    if (!list.length) { box.hidden = true; return; }
    box.hidden = false;
    var head = el("div", "flex items-center gap-1 text-[11px] font-semibold text-on-surface");
    head.appendChild(icon("search", "text-[13px] text-primary"));
    head.appendChild(el("span", "", "검색 후보"));
    box.appendChild(head);
    list.forEach(function (c) {
      var row = el("div", "ws-candidate flex items-center gap-1.5 text-[11px] text-on-surface-variant");
      row.dataset.chunkId = String(c.chunk_id || "");
      row.appendChild(el("span", "font-semibold text-on-surface", "#" + c.rank));
      row.appendChild(el("span", "truncate", c.title || ""));
      var score = Number(c.score);
      row.appendChild(el("span", "shrink-0", "(점수 " + (isNaN(score) ? "-" : score.toFixed(2)) + ")"));
      box.appendChild(row);
    });
  }

  function renderEvidence(t) {
    var box = ensureReceipt(t).evidence;
    box.textContent = "";
    var seen = {};
    var items = [];
    t.sentences.forEach(function (s) {
      ((s && s.evidence) || []).forEach(function (ev) {
        var id = String(ev.chunk_id || "");
        if (!id || seen[id]) { return; }
        seen[id] = true;
        items.push(ev);
      });
    });
    if (!items.length) { box.hidden = true; return; }
    box.hidden = false;
    var head = el("div", "flex items-center gap-1 text-[11px] font-semibold text-on-surface");
    head.appendChild(icon("source", "text-[13px] text-primary"));
    head.appendChild(el("span", "", "근거 " + items.length + "건"));
    box.appendChild(head);
    items.forEach(function (ev) {
      var card = el("div", "rounded-lg border border-outline-variant/30 bg-surface px-2.5 py-2 space-y-1");
      var top = el("div", "flex items-center justify-between gap-2");
      top.appendChild(el("span", "font-semibold text-on-surface text-[11px] truncate", ev.title || ""));
      var link = el("a", "ws-evidence-link inline-flex items-center gap-0.5 text-[11px] text-primary hover:underline shrink-0");
      link.href = "#";
      link.dataset.chunkId = String(ev.chunk_id);
      link.appendChild(el("span", "", "자료에서 보기"));
      link.appendChild(icon("open_in_new", "text-[12px]"));
      link.addEventListener("click", function (e) {
        e.preventDefault();
        WS.focusChunk(String(ev.chunk_id));
      });
      top.appendChild(link);
      card.appendChild(top);
      if (ev.quote) {
        card.appendChild(el("p", "text-[11px] text-on-surface-variant leading-relaxed", "“" + ev.quote + "”"));
      }
      box.appendChild(card);
    });
  }

  function renderFooter(t, done) {
    var kind = done.answer_kind || (t.meta && t.meta.answer_kind);
    t.root.dataset.answerKind = kind || "";
    var row = el("div", "flex flex-wrap items-center gap-2");
    var allSupported = t.sentences.length > 0 && t.sentences.every(function (s) { return s && s.supported; });
    if (kind === "grounded" && allSupported) {
      var badge = el("span", "ws-grounded-badge inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200/60 text-[11px] font-medium");
      badge.appendChild(icon("verified_user", "text-[12px]"));
      badge.appendChild(el("span", "", "근거 있음"));
      row.appendChild(badge);
    }
    var note = null;
    if (kind === "unknown") { note = "자료에 없어 지어내지 않았습니다"; }
    else if (kind === "avoided") { note = "피할 주제라 답하지 않았습니다"; }
    if (note) {
      var n = el("span", "ws-kind-note inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-container text-on-surface-variant text-[11px] font-medium");
      n.appendChild(icon("info", "text-[12px]"));
      n.appendChild(el("span", "", note));
      row.appendChild(n);
    }
    var clips = t.sentences.map(function (s) { return s && s.audio_wav_b64; }).filter(function (b) { return !!b; });
    if (clips.length) {
      var play = el("button", "ws-play inline-flex items-center gap-1 px-2 py-0.5 rounded-full border border-outline-variant/40 text-[11px] text-on-surface-variant hover:text-primary hover:bg-surface-container");
      play.type = "button";
      play.appendChild(icon("play_arrow", "text-[13px]"));
      var label = voiceLabel();
      play.appendChild(el("span", "", label ? "다시 듣기 · " + label : "다시 듣기"));
      play.addEventListener("click", function () {
        stopAudio();
        replay = API.playSequence(clips);
      });
      row.appendChild(play);
    }
    if (row.childNodes.length) { t.bubble.insertBefore(row, t.receipt ? t.receipt.details : null); }
  }

  // ---------- asking ----------
  function finishRequest() {
    busy = false;
    controller = null;
    setResponding(false);
    setQueueBadge(null);
    refreshControls();
  }

  function failTurn(t, err) {
    t.root.dataset.state = "error";
    var message = API.errorText(err);
    showChatError(message);
    ensureAnswerVisible(t);
    var line = el("div", "flex items-center gap-1 text-[11px] text-error");
    line.appendChild(icon("error_outline", "text-[13px]"));
    line.appendChild(el("span", "", message));
    t.bubble.appendChild(line);
    if (err && err.code === "question_limit") { WS.setQuota(0); }
    if (err && err.code === "session_not_found") {
      recovering = true;
      WS.newSession().then(function () {
        recovering = false;
      }, function (e2) {
        recovering = false;
        showChatError(API.errorText(e2));
      });
    }
  }

  function makeHandlers(t, isAudio) {
    var queue = new API.AudioQueue();
    queue.onstate(function (index, state) {
      var s = t.sentenceEls[index];
      if (s) { s.dataset.audio = state; }
    });
    liveQueue = queue;
    return {
      queue: function (d) {
        var pos = d && d.position;
        setQueueBadge(pos);
        setResponding(true, "앞에 " + pos + "명이 기다리고 있습니다…");
      },
      meta: function (d) {
        t.meta = d || {};
        setQueueBadge(null);
        setResponding(true, "답을 만드는 중…");
        if (d && d.transcript) { t.question.textContent = String(d.transcript); }
        t.root.dataset.answerKind = d.answer_kind || "";
        var r = ensureReceipt(t);
        renderTimings(r.timings, d.timings, isAudio, false);
        renderCandidates(t);
        scrollDown();
      },
      sentence: function (d) {
        setResponding(false);
        ensureAnswerVisible(t);
        addSentence(t, d || {});
        if (t.receipt) { t.bubble.appendChild(t.receipt.details); }
        if (liveQueue === queue) { queue.push(d.index, d.audio_wav_b64); }
        scrollDown();
      },
      done: function (d) {
        d = d || {};
        ensureAnswerVisible(t);
        var r = ensureReceipt(t);
        renderTimings(r.timings, d.timings, isAudio, true);
        renderEvidence(t);
        renderCandidates(t);
        renderFooter(t, d);
        r.details.open = true;
        t.root.dataset.state = "answered";
        if (d.questions_left != null) { WS.setQuota(d.questions_left); }
        finishRequest();
        scrollDown();
      },
      error: function (err) {
        failTurn(t, err);
        finishRequest();
        scrollDown();
      }
    };
  }

  function beginTurn(questionText, respondingText) {
    stopAudio();
    showChatError("");
    busy = true;
    refreshControls();
    setResponding(true, respondingText);
    controller = (typeof AbortController !== "undefined") ? new AbortController() : null;
    return createTurn(questionText);
  }

  function askText(text) {
    text = String(text || "").trim();
    if (!ready || busy || recording || !text) { return; }
    if (text.length > maxChars) {
      showChatError(API.errorText({ code: "validation" }));
      return;
    }
    var t = beginTurn(text, "답을 만드는 중…");
    var handlers = makeHandlers(t, false);
    API.askText(WS.state.agentId, WS.state.sessionId, text, handlers, controller && controller.signal)
      .catch(function () { if (busy) { handlers.error({ code: "internal" }); } });
  }

  function askAudio(blob) {
    if (!ready || busy) { return; }
    var t = beginTurn("(음성 질문)", "듣는 중…");
    var handlers = makeHandlers(t, true);
    API.askAudio(WS.state.agentId, WS.state.sessionId, blob, handlers, controller && controller.signal)
      .catch(function () { if (busy) { handlers.error({ code: "internal" }); } });
  }

  // ---------- microphone ----------
  function setRecordingUi(on) {
    recording = on;
    var mic = $("mic-btn");
    mic.setAttribute("aria-pressed", on ? "true" : "false");
    var ic = mic.querySelector(".material-symbols-outlined");
    if (ic) { ic.textContent = on ? "stop_circle" : "mic"; }
    mic.classList.toggle("text-error", on);
    show($("mic-active-strip"), on);
    refreshControls();
  }

  function releaseStream() {
    if (micStream) {
      micStream.getTracks().forEach(function (tr) { tr.stop(); });
      micStream = null;
    }
  }

  async function startRecording() {
    if (!ready || busy || recording || !voiceAvailable) { return; }
    stopAudio();
    showChatError("");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      showChatError(API.errorText({ code: "mic_unsupported" }));
      return;
    }
    var mic = $("mic-btn");
    mic.disabled = true;
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      micStream = null;
      refreshControls();
      var code = (e && (e.name === "NotAllowedError" || e.name === "SecurityError")) ? "mic_denied" : "mic_unsupported";
      showChatError(API.errorText({ code: code }));
      return;
    }
    recChunks = [];
    try {
      recorder = new MediaRecorder(micStream);
    } catch (e2) {
      releaseStream();
      recorder = null;
      refreshControls();
      showChatError(API.errorText({ code: "mic_unsupported" }));
      return;
    }
    recorder.ondataavailable = function (ev) {
      if (ev.data && ev.data.size > 0) { recChunks.push(ev.data); }
    };
    recorder.onstop = sendRecording;
    recorder.start();
    setRecordingUi(true);
    recTimer = setTimeout(stopRecording, MAX_RECORD_MS);
  }

  function stopRecording() {
    if (recTimer) { clearTimeout(recTimer); recTimer = null; }
    if (recorder && recorder.state !== "inactive") { recorder.stop(); }
    releaseStream();
    setRecordingUi(false);
  }

  function sendRecording() {
    var type = (recorder && recorder.mimeType) || "audio/webm";
    var blob = new Blob(recChunks, { type: type });
    recorder = null;
    recChunks = [];
    if (!blob.size) {
      showChatError(API.errorText({ code: "empty_audio" }));
      return;
    }
    askAudio(blob);
  }

  // ---------- setup ----------
  function renderChips(questions) {
    var box = $("sample-chips-container");
    box.textContent = "";
    var list = (questions || []).filter(function (q) { return typeof q === "string" && q.trim(); }).slice(0, 3);
    list.forEach(function (q) {
      var chip = el("button", "sample-chip px-3 py-1.5 rounded-full bg-surface border border-outline-variant/50 text-[11px] sm:text-xs text-on-surface hover:border-primary hover:text-primary transition-colors disabled:opacity-50 text-left", q);
      chip.type = "button";
      chip.addEventListener("click", function () { askText(q); });
      box.appendChild(chip);
    });
    show($("sample-questions-wrap"), list.length > 0);
    refreshControls();
  }

  async function loadCustomChips() {
    var res = await API.request("GET", "/api/agents/" + encodeURIComponent(WS.state.agentId) + "/chunks?limit=3");
    var items = (res.ok && res.data && res.data.items) || [];
    renderChips(items.map(function (c) { return c && c.title; }));
  }

  function onReady(payload) {
    var agent = payload.agent || {};
    var options = payload.options || {};
    var preset = payload.preset;
    var limits = options.limits || {};
    if (limits.max_question_chars) { maxChars = Number(limits.max_question_chars) || DEFAULT_MAX_CHARS; }
    $("char-max-limit").textContent = String(maxChars);
    $("chat-textarea").maxLength = maxChars;

    var desc = $("greeting-description");
    if (preset && preset.description) {
      desc.textContent = preset.description;
    } else {
      desc.textContent = "안녕하세요, " + ((agent.settings && agent.settings.persona_name) || agent.name || "상담원") +
        "입니다. 궁금한 것을 글자나 음성으로 물어보세요. 답마다 근거와 걸린 시간을 함께 보여 드립니다.";
    }

    voiceAvailable = !!options.voice_input_available;
    var mic = $("mic-btn");
    show(mic, voiceAvailable);
    show($("mic-hint"), !voiceAvailable);
    if (!voiceAvailable) { mic.disabled = true; }

    ready = true;
    if (preset) {
      renderChips(preset.sample_questions || []);
    } else {
      renderChips([]);
      loadCustomChips();
    }
    refreshControls();
  }

  function onSession() {
    if (!ready || recovering) { return; }
    stopAudio();
    if (controller) { controller.abort(); }
    if (busy) { finishRequest(); }
    showChatError("");
    $("messages-list").textContent = "";
  }

  function bind() {
    var form = $("chat-form");
    var ta = $("chat-textarea");
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var text = ta.value;
      if (!ready || busy || recording || !text.trim()) { return; }
      ta.value = "";
      refreshControls();
      askText(text);
    });
    ta.addEventListener("input", refreshControls);
    ta.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing && ev.keyCode !== 229) {
        ev.preventDefault();
        if (typeof form.requestSubmit === "function") { form.requestSubmit(); }
        else { form.dispatchEvent(new Event("submit", { cancelable: true })); }
      }
    });
    $("mic-btn").addEventListener("click", function () {
      if (recording) { stopRecording(); } else { startRecording(); }
    });
    refreshControls();
    WS.on("session", onSession);
    WS.on("ready", onReady);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
