(function () {
  "use strict";

  var VA = window.VA;
  var $ = function (id) { return document.getElementById(id); };

  var MAX_RECORD_MS = 15000;
  var HINT_IDLE = "누르고 말씀하세요. 다시 누르면 보냅니다. (최대 15초)";
  var HINT_RECORDING = "듣는 중… 다시 누르면 보냅니다";
  var HINT_TEXT_ONLY = "글자로 물어봐 주세요";
  var SHARE_PREFIX = "/talk?agent=";

  var agentId = VA.param("agent");
  var agent = null;
  var options = null;
  var sessionId = "";
  var questionsLeft = null;
  var lastAsked = "";
  var voiceInput = false;
  var reqSeq = 0;
  var current = null;          // {id, turn, controller}
  var audio = new VA.AudioQueue($("player"));

  // recording state
  var recorder = null;
  var micStream = null;
  var recChunks = [];
  var recTimer = null;
  var recording = false;

  // ---------- helpers ----------
  function setReady() { document.body.dataset.ready = "true"; }

  function showFatal(text) {
    $("fatal-text").textContent = text;
    $("fatal").hidden = false;
    $("talk-main").hidden = true;
    $("share-btn").disabled = true;
  }

  function showAskError(text) { $("ask-error").textContent = text || ""; }

  function setQueue(text) { $("queue-status").textContent = text || ""; }

  function inputsLocked() { return questionsLeft !== null && questionsLeft <= 0; }

  function refreshControls() {
    var locked = inputsLocked();
    $("ask-btn").disabled = locked || recording;
    $("ask-input").disabled = locked;
    Array.prototype.forEach.call(document.querySelectorAll("#sample-chips .chip"), function (c) {
      c.disabled = locked || recording;
    });
    $("mic-btn").disabled = locked && !recording;
  }

  function setQuestionsLeft(n) {
    var v = Math.max(0, Math.floor(Number(n) || 0));
    questionsLeft = v;
    $("questions-left").textContent = String(v);
    refreshControls();
  }

  async function errorFromResponse(res) {
    var body = null;
    try { body = await res.json(); } catch (e) { body = null; }
    var d = body && body.detail;
    if (Array.isArray(d)) { return { code: "validation", message: "입력 값을 확인해 주세요." }; }
    if (d && typeof d === "object" && d.code) { return d; }
    return { code: "internal", message: "" };
  }

  // ---------- turn rendering ----------
  function createTurn(questionText) {
    var turn = VA.el("article", "turn");
    turn.dataset.state = "loading";
    var q = VA.el("p", "turn-question", "👤 " + questionText);
    var answer = VA.el("p", "turn-answer");
    turn.appendChild(q);
    turn.appendChild(answer);
    var list = $("turns");
    list.insertBefore(turn, list.firstChild);
    $("turns-empty").hidden = true;
    return {
      el: turn, question: q, answer: answer, receipt: null,
      kind: null, candidates: [], metaTimings: null, speak0: null,
      footIndex: {}, footList: null, footCount: 0
    };
  }

  function buildReceipt(t) {
    var d = VA.el("details", "receipt");
    d.open = true;
    d.appendChild(VA.el("summary", null, "영수증 — 이번 답이 어떻게 나왔나"));
    var timings = VA.el("div", "receipt-timings");
    var note = VA.el("p", "receipt-note");
    var foot = VA.el("ol", "receipt-footnotes");
    foot.hidden = true;
    var cand = VA.el("p", "receipt-candidates");
    d.appendChild(timings);
    d.appendChild(note);
    d.appendChild(foot);
    d.appendChild(cand);
    t.el.appendChild(d);
    t.receipt = { el: d, timings: timings, note: note, cand: cand };
    t.footList = foot;
  }

  function renderTimings(t, done) {
    var box = t.receipt.timings;
    box.textContent = "";
    var src = (done && done.timings) || t.metaTimings || {};
    var segs = [];
    var queueMs = Number(src.queue_ms) || 0;
    if (done && queueMs > 0) { segs.push({ cls: "seg-queue", label: "대기", ms: queueMs }); }
    segs.push({ cls: "seg-listen", label: "듣기", ms: Number(src.listen_ms) || 0 });
    segs.push({ cls: "seg-search", label: "검색", ms: Number(src.search_ms) || 0 });
    segs.push({ cls: "seg-think", label: "생각", ms: Number(src.think_ms) || 0 });
    if (t.speak0 !== null) { segs.push({ cls: "seg-speak", label: "말하기 시작", ms: t.speak0 }); }

    var total = segs.reduce(function (a, s) { return a + s.ms; }, 0);
    var bar = VA.el("div", "bar");
    bar.setAttribute("aria-hidden", "true");
    segs.forEach(function (s) {
      var seg = VA.el("span", "seg " + s.cls);
      seg.style.width = (total > 0 ? (s.ms / total) * 100 : 100 / segs.length) + "%";
      bar.appendChild(seg);
    });
    box.appendChild(bar);

    var legend = VA.el("div", "legend");
    segs.forEach(function (s) {
      var item = VA.el("span");
      var sw = VA.el("i", s.cls);
      item.appendChild(sw);
      item.appendChild(document.createTextNode(s.label + " " + VA.fmtMs(s.ms)));
      legend.appendChild(item);
    });
    if (done && done.timings) {
      legend.appendChild(VA.el("span", "first", "첫 음성까지 " + VA.fmtMs(done.timings.first_audio_ms)));
    }
    box.appendChild(legend);
  }

  function renderCandidates(t) {
    var c = t.receipt.cand;
    var items = t.candidates || [];
    if (!items.length) { c.textContent = ""; c.hidden = true; return; }
    c.hidden = false;
    c.textContent = "찾아본 자료: " + items.map(function (it) {
      return "#" + it.rank + " " + it.title + " (점수 " + (Number(it.score) || 0).toFixed(2) + ")";
    }).join(" · ");
  }

  function onMeta(t, data) {
    if (data.transcript !== undefined && data.transcript !== null) {
      t.question.textContent = "👤 " + data.transcript;
      if (data.transcript) { lastAsked = String(data.transcript); }
    }
    t.kind = data.answer_kind || null;
    t.candidates = data.candidates || [];
    t.metaTimings = data.timings || {};
    buildReceipt(t);
    if (t.kind === "unknown") { t.receipt.note.textContent = "자료에 없어 지어내지 않았습니다."; }
    else if (t.kind === "avoided") { t.receipt.note.textContent = "피할 주제라 답하지 않았습니다."; }
    renderTimings(t, null);
    renderCandidates(t);
  }

  function addFootnote(t, ev) {
    var key = ev.chunk_id;
    if (Object.prototype.hasOwnProperty.call(t.footIndex, key)) { return t.footIndex[key]; }
    t.footCount += 1;
    t.footIndex[key] = t.footCount;
    var li = VA.el("li", null, (ev.title || "") + " — “" + (ev.quote || "") + "”");
    t.footList.appendChild(li);
    t.footList.hidden = false;
    return t.footCount;
  }

  function onSentence(t, data) {
    if (!t.receipt) { buildReceipt(t); }
    var idx = Number(data.index) || 0;
    if (idx === 0 && t.speak0 === null) {
      t.speak0 = Number(data.speak_ms) || 0;
      renderTimings(t, null);
    }
    var s = VA.el("span", "sentence", data.text || "");
    s.dataset.index = String(idx);
    s.dataset.audio = "queued";
    var nums = [];
    (data.evidence || []).forEach(function (ev) {
      var n = addFootnote(t, ev);
      if (nums.indexOf(n) < 0) { nums.push(n); }
    });
    nums.forEach(function (n) { s.appendChild(VA.el("sup", null, String(n))); });
    if (t.kind === "grounded" && data.supported === false) {
      s.classList.add("unsupported");
      s.appendChild(VA.el("span", "unsupported-tag", "근거 없음"));
    }
    if (t.answer.childNodes.length) { t.answer.appendChild(document.createTextNode(" ")); }
    t.answer.appendChild(s);
    audio.push(idx, data.audio_wav_b64, s);
  }

  function onDone(t, data) {
    if (!t.receipt) { buildReceipt(t); }
    t.el.dataset.state = "answered";
    renderTimings(t, data);
    if (data.questions_left !== undefined && data.questions_left !== null) {
      setQuestionsLeft(data.questions_left);
    }
  }

  function failTurn(t, error, status) {
    t.el.dataset.state = "error";
    if (t.question.textContent === "👤 듣는 중…") { t.question.textContent = "👤 (알아듣지 못했어요)"; }
    showAskError(VA.errorText(error));
    if (status === 429 || (error && error.code === "question_limit")) { setQuestionsLeft(0); }
  }

  // ---------- asking ----------
  function beginRequest(questionText) {
    audio.reset();
    showAskError("");
    setQueue("");
    if (current) {
      try { current.controller.abort(); } catch (e) { /* ignore */ }
      if (current.turn.el.dataset.state === "loading") {
        current.turn.el.dataset.state = "error";
        current.turn.answer.appendChild(VA.el("span", "hint", "새 질문으로 멈췄습니다."));
      }
    }
    reqSeq += 1;
    var req = {
      id: reqSeq,
      turn: createTurn(questionText),
      controller: (typeof AbortController === "function") ? new AbortController() : { abort: function () {}, signal: undefined }
    };
    current = req;
    return req;
  }

  function isCurrent(req) { return current && current.id === req.id; }

  async function runRequest(req, path, init) {
    init.signal = req.controller.signal;
    var res;
    try {
      res = await fetch(path, init);
    } catch (e) {
      if (!isCurrent(req)) { return; }
      setQueue("");
      failTurn(req.turn, { code: "network", message: "" }, 0);
      current = null;
      return;
    }
    if (!isCurrent(req)) { return; }
    if (!res.ok) {
      var err = await errorFromResponse(res);
      if (!isCurrent(req)) { return; }
      setQueue("");
      failTurn(req.turn, err, res.status);
      current = null;
      return;
    }
    await VA.readSse(res, function (name, data) {
      if (!isCurrent(req)) { return; }
      data = data || {};
      if (name === "queue") {
        setQueue("앞에 " + data.position + "명");
      } else if (name === "meta") {
        setQueue("");
        onMeta(req.turn, data);
      } else if (name === "sentence") {
        onSentence(req.turn, data);
      } else if (name === "done") {
        setQueue("");
        onDone(req.turn, data);
        current = null;
      } else if (name === "error") {
        setQueue("");
        failTurn(req.turn, data, 0);
        current = null;
      }
    });
  }

  function askText(text) {
    var q = String(text || "").trim();
    if (!q) { showAskError("질문을 적어 주세요."); return; }
    if (inputsLocked() || recording) { return; }
    lastAsked = q;
    var req = beginRequest(q);
    runRequest(req, "/api/agents/" + encodeURIComponent(agentId) + "/turns/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, text: q })
    });
  }

  // ---------- microphone ----------
  function setRecordingUi(on) {
    recording = on;
    var mic = $("mic-btn");
    mic.classList.toggle("recording", on);
    mic.setAttribute("aria-pressed", on ? "true" : "false");
    $("mic-hint").textContent = on ? HINT_RECORDING : HINT_IDLE;
    refreshControls();
  }

  async function startRecording() {
    if (inputsLocked()) { return; }
    audio.reset();
    showAskError("");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      showAskError(VA.errorText({ code: "mic_unsupported" }));
      return;
    }
    $("mic-btn").disabled = true;
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      micStream = null;
      $("mic-btn").disabled = false;
      showAskError(VA.errorText({ code: "mic_denied" }));
      return;
    }
    recChunks = [];
    try {
      recorder = new MediaRecorder(micStream);
    } catch (e2) {
      micStream.getTracks().forEach(function (tr) { tr.stop(); });
      micStream = null;
      $("mic-btn").disabled = false;
      showAskError(VA.errorText({ code: "mic_unsupported" }));
      return;
    }
    recorder.ondataavailable = function (e) {
      if (e.data && e.data.size > 0) { recChunks.push(e.data); }
    };
    recorder.onstop = sendRecording;
    recorder.start();
    setRecordingUi(true);
    recTimer = setTimeout(stopRecording, MAX_RECORD_MS);
  }

  function stopRecording() {
    if (recTimer) { clearTimeout(recTimer); recTimer = null; }
    if (recorder && recorder.state !== "inactive") { recorder.stop(); }
    if (micStream) { micStream.getTracks().forEach(function (tr) { tr.stop(); }); micStream = null; }
    setRecordingUi(false);
  }

  function sendRecording() {
    var type = (recorder && recorder.mimeType) || "audio/webm";
    var blob = new Blob(recChunks, { type: type });
    recorder = null;
    recChunks = [];
    var req = beginRequest("듣는 중…");
    runRequest(req, "/api/agents/" + encodeURIComponent(agentId) +
      "/turns/audio-stream?session_id=" + encodeURIComponent(sessionId), {
      method: "POST",
      body: blob
    });
  }

  // ---------- header ----------
  function shareUrl() {
    var p = agent && agent.share_path;
    if (typeof p === "string" && p.indexOf(SHARE_PREFIX) === 0) { return location.origin + p; }
    return location.origin + VA.talkUrl(agentId);
  }

  async function onShare() {
    var url = shareUrl();
    var status = $("share-status");
    var ok = false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(url);
        ok = true;
      }
    } catch (e) { ok = false; }
    if (ok) {
      status.textContent = "복사했습니다";
      return;
    }
    var input = $("share-url");
    input.value = url;
    input.hidden = false;
    input.focus();
    input.select();
    status.textContent = "링크를 선택했습니다. 복사해 주세요";
  }

  function showWarnings() {
    var key = "va:warnings:" + agentId;
    var list = [];
    try {
      var raw = sessionStorage.getItem(key);
      if (raw) { list = JSON.parse(raw) || []; }
      sessionStorage.removeItem(key);
    } catch (e) { list = []; }
    var box = $("warnings");
    box.textContent = "";
    if (!Array.isArray(list) || !list.length) { box.hidden = true; return; }
    var ul = VA.el("ul");
    ul.style.margin = "0";
    ul.style.paddingLeft = "1.2em";
    list.forEach(function (m) { ul.appendChild(VA.el("li", null, m)); });
    box.appendChild(ul);
    box.hidden = false;
  }

  function renderChips(questions) {
    var box = $("sample-chips");
    box.textContent = "";
    questions.slice(0, 3).forEach(function (q) {
      var b = VA.el("button", "chip", q);
      b.type = "button";
      b.addEventListener("click", function () {
        $("ask-input").value = "";
        askText(q);
      });
      box.appendChild(b);
    });
  }

  async function loadSamples() {
    if (agent && agent.preset_id) {
      var pr = await VA.api("GET", "/api/presets");
      var items = (pr.ok && pr.data && pr.data.items) || [];
      for (var i = 0; i < items.length; i++) {
        if (items[i].agent_id === agentId) {
          return { title: items[i].title, questions: items[i].sample_questions || [] };
        }
      }
      return { title: null, questions: [] };
    }
    var cr = await VA.api("GET", "/api/agents/" + encodeURIComponent(agentId) + "/chunks?limit=3");
    var chunks = (cr.ok && cr.data && cr.data.items) || [];
    return {
      title: null,
      questions: chunks.map(function (c) { return c.title; }).filter(function (t) { return !!t; })
    };
  }

  // ---------- start ----------
  async function start() {
    if (!agentId) {
      showFatal("상담원 주소가 비어 있습니다.");
      setReady();
      return;
    }
    var both = await Promise.all([
      VA.api("GET", "/api/options"),
      VA.api("GET", "/api/agents/" + encodeURIComponent(agentId))
    ]);
    var opt = both[0];
    var ag = both[1];
    if (!ag.ok) {
      showFatal(VA.errorText(ag.error));
      setReady();
      return;
    }
    if (!opt.ok) {
      showFatal(VA.errorText(opt.error));
      setReady();
      return;
    }
    agent = ag.data;
    options = opt.data || {};
    var limits = options.limits || {};
    if (limits.max_question_chars) { $("ask-input").maxLength = Number(limits.max_question_chars); }
    $("agent-title").textContent = agent.name || "상담원";
    showWarnings();

    voiceInput = !!options.voice_input_available;
    $("mic-btn").hidden = !voiceInput;
    $("mic-hint").textContent = voiceInput ? HINT_IDLE : HINT_TEXT_ONLY;

    var samples = await loadSamples();
    if (samples.title) { $("agent-title").textContent = samples.title; }
    document.title = $("agent-title").textContent + " — 음성 상담원";
    renderChips(samples.questions);

    var ses = await VA.api("POST", "/api/agents/" + encodeURIComponent(agentId) + "/sessions");
    if (!ses.ok) {
      showFatal(VA.errorText(ses.error));
      setReady();
      return;
    }
    sessionId = ses.data.session_id;
    setQuestionsLeft(ses.data.questions_left);
    setReady();

    window.VA.talk = {
      agentId: agentId,
      agent: agent,
      options: options,
      getSessionId: function () { return sessionId; },
      setQuestionsLeft: setQuestionsLeft,
      lastQuestion: function () { return lastAsked || ""; },
      audio: audio
    };
    document.dispatchEvent(new CustomEvent("va:talk-ready", { detail: window.VA.talk }));
  }

  $("ask-btn").addEventListener("click", function () {
    var input = $("ask-input");
    var q = input.value;
    if (String(q).trim() && !inputsLocked()) { input.value = ""; }
    askText(q);
  });
  $("ask-input").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.isComposing) {
      e.preventDefault();
      $("ask-btn").click();
    }
  });
  $("mic-btn").addEventListener("click", function () {
    if (recording) { stopRecording(); } else { startRecording(); }
  });
  $("share-btn").addEventListener("click", onShare);

  start();
})();
