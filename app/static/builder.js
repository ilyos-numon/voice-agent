(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  var state = { agentId: null, sessionId: null, presetId: null, options: null, scTimer: null };

  // ---------- helpers ----------
  function fmtMs(v) {
    var n = Number(v) || 0;
    if (n >= 1000) { return (Math.round(n / 100) / 10) + "s"; }
    return (Math.round(n * 10) / 10) + "ms";
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = text; }
    return e;
  }

  function errMessage(body, status) {
    var d = body && body.detail;
    if (d && !Array.isArray(d) && d.message) { return d.message; }
    if (Array.isArray(d) && d.length) {
      var loc = d[0].loc || [];
      return "입력값을 확인해 주세요: " + loc[loc.length - 1] + " (" + status + ")";
    }
    return "요청을 처리하지 못했습니다. (" + status + ")";
  }

  async function api(method, path, body) {
    var opt = { method: method, headers: {} };
    if (body !== undefined) {
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body);
    }
    var res = await fetch(path, opt);
    var data = null;
    if (res.status !== 204) {
      try { data = await res.json(); } catch (e) { data = null; }
    }
    return { ok: res.ok, status: res.status, data: data };
  }

  // ---------- audio: play sentences in index order ----------
  var player = $("player");
  var playback = { seq: 0, items: [], pos: 0, playing: false };

  function resetPlayback() {
    player.pause();
    player.removeAttribute("src");
    playback = { seq: playback.seq + 1, items: [], pos: 0, playing: false };
    return playback.seq;
  }

  function enqueueAudio(seq, index, b64, node) {
    if (seq !== playback.seq || !b64) { return; }
    playback.items[index] = { src: "data:audio/wav;base64," + b64, node: node };
    if (!playback.playing) { playNext(); }
  }

  function playNext() {
    var item = playback.items[playback.pos];
    if (!item) { playback.playing = false; return; }
    playback.playing = true;
    if (item.node) { item.node.classList.add("playing"); }
    player.src = item.src;
    var p = player.play();
    if (p && p.catch) { p.catch(function () { advance(); }); }
  }

  function advance() {
    var item = playback.items[playback.pos];
    if (item && item.node) { item.node.classList.remove("playing"); }
    playback.pos += 1;
    playback.playing = false;
    playNext();
  }

  player.addEventListener("ended", advance);
  player.addEventListener("error", function () { if (playback.playing) { advance(); } });

  // ---------- options / presets ----------
  function fillLengthSelect(select, value) {
    select.textContent = "";
    var items = (state.options && state.options.answer_length) || [
      { value: "one_sentence", label: "한 문장" }, { value: "short", label: "짧게" }, { value: "detailed", label: "자세히" }
    ];
    items.forEach(function (it) {
      var o = el("option", null, it.label);
      o.value = it.value;
      select.appendChild(o);
    });
    if (value) { select.value = value; }
  }

  async function loadOptions() {
    var r = await api("GET", "/api/options");
    if (r.ok) { state.options = r.data; }
    var def = state.options && state.options.defaults ? state.options.defaults.answer_length : "short";
    fillLengthSelect($("answer-length"), def);
    fillLengthSelect($("ab-a-length"), "short");
    fillLengthSelect($("ab-b-length"), "detailed");
    if (state.options && state.options.limits) {
      $("kn-input").maxLength = Math.max(state.options.limits.max_text_chars, state.options.limits.max_csv_chars);
    }
  }

  var presets = [];

  async function loadPresets() {
    var r = await api("GET", "/api/presets");
    var list = $("preset-list");
    list.textContent = "";
    if (!r.ok) { list.appendChild(el("p", "error", "체험용 상담원을 불러오지 못했습니다.")); return; }
    presets = r.data.items || [];
    presets.forEach(function (p) {
      var card = el("button", "preset-card");
      card.type = "button";
      card.dataset.presetId = p.preset_id;
      card.appendChild(el("span", "title", p.title));
      card.appendChild(el("span", "desc", p.description));
      card.addEventListener("click", function () { openAgent(p.agent_id); });
      list.appendChild(card);
    });
  }

  function markActivePreset() {
    document.querySelectorAll(".preset-card").forEach(function (c) {
      c.classList.toggle("active", c.dataset.presetId === state.presetId);
    });
  }

  function showSamples(questions) {
    var box = $("sample-questions");
    box.textContent = "";
    (questions || []).forEach(function (q) {
      var b = el("button", null, q);
      b.type = "button";
      b.addEventListener("click", function () { $("ask-input").value = q; ask(); });
      box.appendChild(b);
    });
  }

  // ---------- agent / session ----------
  async function openAgent(agentId) {
    $("ask-error").textContent = "";
    var r = await api("GET", "/api/agents/" + encodeURIComponent(agentId));
    if (!r.ok) {
      $("ask-error").textContent = r.status === 404 ? "링크가 만료됐습니다. 새로 만들어 주세요." : errMessage(r.data, r.status);
      return false;
    }
    state.agentId = r.data.agent_id;
    state.presetId = r.data.preset_id;
    $("agent-id").textContent = r.data.agent_id;
    $("agent-name").textContent = r.data.name || "";
    $("share-link").textContent = r.data.share_path ? "공유 링크: " + location.origin + r.data.share_path : "";
    var preset = presets.filter(function (p) { return p.agent_id === r.data.agent_id; })[0];
    showSamples(preset ? preset.sample_questions : []);
    markActivePreset();
    $("chat-log").textContent = "";
    $("scorecard-report").hidden = true;
    $("scorecard-status").textContent = "";
    stopPolling();
    $("scorecard-btn").disabled = false;
    return openSession();
  }

  async function openSession() {
    var r = await api("POST", "/api/agents/" + encodeURIComponent(state.agentId) + "/sessions");
    if (!r.ok) { $("ask-error").textContent = errMessage(r.data, r.status); state.sessionId = null; return false; }
    state.sessionId = r.data.session_id;
    $("questions-left").textContent = r.data.questions_left;
    return true;
  }

  async function createAgent() {
    var errEl = $("create-error");
    errEl.textContent = "";
    $("create-warnings").textContent = "";
    var kind = $("kn-kind").value;
    var raw = $("kn-input").value;
    var knowledge = kind === "faq_csv" ? { kind: "faq_csv", csv: raw } : { kind: "text", text: raw };
    var settings = { answer_length: $("answer-length").value };
    var persona = $("persona-name").value.trim();
    if (persona) { settings.persona_name = persona; }
    var name = (persona || "내") + " 상담원";
    $("create-btn").disabled = true;
    try {
      var r = await api("POST", "/api/agents", { name: name, knowledge: knowledge, settings: settings });
      if (!r.ok) { errEl.textContent = errMessage(r.data, r.status); return; }
      var warns = (r.data.warnings || []).map(function (w) { return w.message; });
      await openAgent(r.data.agent_id);
      if (warns.length) { $("create-warnings").textContent = "참고: " + warns.join(" / "); }
      history.replaceState(null, "", "?agent=" + encodeURIComponent(r.data.agent_id));
    } catch (e) {
      errEl.textContent = "서버에 연결하지 못했습니다.";
    } finally {
      $("create-btn").disabled = false;
    }
  }

  // ---------- turn (SSE) ----------
  function parseSse(buffer) {
    var events = [];
    var parts = buffer.split("\n\n");
    var rest = parts.pop();
    parts.forEach(function (block) {
      var name = "message";
      var data = [];
      block.split("\n").forEach(function (line) {
        if (line.indexOf("event:") === 0) { name = line.slice(6).trim(); }
        else if (line.indexOf("data:") === 0) { data.push(line.slice(5).replace(/^ /, "")); }
      });
      if (data.length) {
        try { events.push({ event: name, data: JSON.parse(data.join("\n")) }); } catch (e) { /* skip */ }
      }
    });
    return { events: events, rest: rest };
  }

  function newTurnView(question) {
    var turn = el("div", "turn");
    turn.appendChild(el("p", "q", "질문: " + question));
    var answer = el("p", "a");
    turn.appendChild(answer);
    var note = el("p", "kind-note");
    note.hidden = true;
    turn.appendChild(note);
    var receipt = el("div", "receipt");
    var evidence = el("ol", "evidence");
    var timings = el("div", "receipt-timings", "걸린 시간: 계산 중…");
    var cands = el("p", "receipt-candidates");
    receipt.appendChild(evidence);
    receipt.appendChild(timings);
    receipt.appendChild(cands);
    turn.appendChild(receipt);
    $("chat-log").prepend(turn);
    return { turn: turn, answer: answer, note: note, evidence: evidence, timings: timings, cands: cands,
      footnotes: {}, footCount: 0, meta: null, firstSpeak: null, kind: null };
  }

  function addFootnote(view, ev) {
    if (view.footnotes[ev.chunk_id]) { return view.footnotes[ev.chunk_id]; }
    view.footCount += 1;
    var n = view.footCount;
    view.footnotes[ev.chunk_id] = n;
    var li = el("li");
    li.appendChild(el("span", "num", n + "."));
    li.appendChild(document.createTextNode("근거: " + ev.title + " — “" + ev.quote + "”"));
    view.evidence.appendChild(li);
    return n;
  }

  function renderCandidates(view, cands) {
    view.cands.textContent = "";
    if (!cands || !cands.length) { view.cands.hidden = true; return; }
    view.cands.hidden = false;
    view.cands.textContent = "찾아본 자료: " + cands.map(function (c) {
      return "#" + c.rank + " " + c.title + " (점수 " + Number(c.score).toFixed(2) + ")";
    }).join(" · ");
  }

  function renderTimings(view, t, firstSpeak) {
    var box = view.timings;
    box.textContent = "";
    var segs = [
      { key: "listen", label: "듣기", v: Number(t.listen_ms) || 0 },
      { key: "search", label: "검색", v: Number(t.search_ms) || 0 },
      { key: "think", label: "생각", v: Number(t.think_ms) || 0 },
      { key: "speak", label: "말하기 시작", v: Number(firstSpeak) || 0 }
    ];
    var sum = segs.reduce(function (a, s) { return a + s.v; }, 0) || 1;
    var bar = el("div", "bar");
    var legend = el("div", "legend");
    segs.forEach(function (s) {
      var seg = el("div", "seg seg-" + s.key);
      seg.style.flexGrow = String(s.v / sum);
      seg.title = s.label + " " + fmtMs(s.v);
      bar.appendChild(seg);
      var item = el("span");
      item.appendChild(el("i", "seg-" + s.key));
      item.appendChild(document.createTextNode(s.label + " " + fmtMs(s.v)));
      legend.appendChild(item);
    });
    box.appendChild(bar);
    box.appendChild(legend);
    if (t.first_audio_ms !== undefined) {
      var line = "첫 음성까지 " + fmtMs(t.first_audio_ms) + " · 전체 " + fmtMs(t.total_ms);
      if (Number(t.queue_ms) > 0) { line += " · 대기 " + fmtMs(t.queue_ms); }
      box.appendChild(el("div", "first", line));
    }
  }

  function handleTurnEvent(view, seq, ev) {
    var d = ev.data || {};
    if (ev.event === "queue") {
      $("queue-status").textContent = "앞에 " + d.position + "명";
    } else if (ev.event === "meta") {
      $("queue-status").textContent = "";
      view.meta = d;
      view.kind = d.answer_kind;
      view.turn.dataset.kind = d.answer_kind;
      if (d.answer_kind === "unknown") {
        view.note.hidden = false;
        view.note.textContent = "자료에 없는 내용이라 지어내지 않았습니다.";
      } else if (d.answer_kind === "avoided") {
        view.note.hidden = false;
        view.note.textContent = "피하도록 정한 주제라 답하지 않았습니다.";
      }
      renderCandidates(view, d.candidates);
      renderTimings(view, d.timings || {}, 0);
    } else if (ev.event === "sentence") {
      var span = el("span", "sentence", d.text);
      span.dataset.supported = d.supported ? "true" : "false";
      span.dataset.index = d.index;
      (d.evidence || []).forEach(function (e) {
        var n = addFootnote(view, e);
        span.appendChild(el("sup", null, String(n)));
      });
      if (!d.supported && view.kind === "grounded") {
        span.appendChild(el("span", "no-evidence", "근거 없음"));
      }
      if (view.answer.childNodes.length) { view.answer.appendChild(document.createTextNode(" ")); }
      view.answer.appendChild(span);
      if (d.index === 0) {
        view.firstSpeak = d.speak_ms;
        renderTimings(view, (view.meta && view.meta.timings) || {}, d.speak_ms);
      }
      enqueueAudio(seq, d.index, d.audio_wav_b64, span);
    } else if (ev.event === "done") {
      renderTimings(view, d.timings || {}, view.firstSpeak);
      $("questions-left").textContent = d.questions_left;
      return true;
    } else if (ev.event === "error") {
      $("queue-status").textContent = "";
      view.note.hidden = false;
      view.note.textContent = d.message || "답변을 가져오지 못했습니다.";
      return true;
    }
    return false;
  }

  async function readStream(res, view, seq) {
    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    for (;;) {
      var chunk = await reader.read();
      if (chunk.done) { buffer += decoder.decode() + "\n\n"; }
      else { buffer += decoder.decode(chunk.value, { stream: true }); }
      var parsed = parseSse(buffer.replace(/\r\n/g, "\n"));
      buffer = parsed.rest;
      for (var i = 0; i < parsed.events.length; i++) {
        if (handleTurnEvent(view, seq, parsed.events[i])) {
          try { reader.cancel(); } catch (e) { /* ignore */ }
          return;
        }
      }
      if (chunk.done) { return; }
    }
  }

  async function postTurn(text) {
    return fetch("/api/agents/" + encodeURIComponent(state.agentId) + "/turns/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, text: text })
    });
  }

  async function ask() {
    var errEl = $("ask-error");
    errEl.textContent = "";
    var text = $("ask-input").value.trim();
    if (!text) { errEl.textContent = "질문을 입력해 주세요."; return; }
    if (!state.agentId) { errEl.textContent = "먼저 상담원을 고르거나 만들어 주세요."; return; }
    $("ask-btn").disabled = true;
    try {
      if (!state.sessionId && !(await openSession())) { return; }
      var res = await postTurn(text);
      if (res.status === 404) {
        var body404 = null;
        try { body404 = await res.json(); } catch (e) { /* ignore */ }
        if (body404 && body404.detail && body404.detail.code === "session_not_found" && await openSession()) {
          res = await postTurn(text);
        } else {
          errEl.textContent = errMessage(body404, 404);
          return;
        }
      }
      if (!res.ok) {
        var body = null;
        try { body = await res.json(); } catch (e) { /* ignore */ }
        if (res.status === 429) { $("questions-left").textContent = "0"; }
        errEl.textContent = errMessage(body, res.status);
        return;
      }
      var seq = resetPlayback();
      var view = newTurnView(text);
      await readStream(res, view, seq);
    } catch (e) {
      errEl.textContent = "서버에 연결하지 못했습니다.";
    } finally {
      $("ask-btn").disabled = false;
      $("queue-status").textContent = "";
    }
  }

  // ---------- scorecard (poll every 1 s) ----------
  var REASON = { wrong_chunk: "다른 답", no_answer: "답 못 함", misheard: "음성 인식 오류" };

  function renderReport(rep) {
    $("scorecard-report").hidden = false;
    $("sc-text-hits").textContent = rep.text.hits + " / " + rep.text.total;
    $("sc-voice-hits").textContent = rep.voice
      ? rep.voice.hits + " / " + rep.voice.total
      : "이 서버에서는 음성 질문을 시험하지 않았습니다";
    $("sc-p50").textContent = fmtMs(rep.first_audio_ms.p50);
    $("sc-p95").textContent = fmtMs(rep.first_audio_ms.p95);
    var fl = $("sc-failures");
    fl.textContent = "";
    if (!rep.failures.length) { fl.appendChild(el("li", null, "없음")); }
    rep.failures.forEach(function (f) {
      var got = f.got ? f.got.title : "답 없음";
      var heard = f.heard ? " (알아들은 말: “" + f.heard + "”)" : "";
      fl.appendChild(el("li", null, "“" + f.question + "” → " + got + " · " + (REASON[f.reason] || f.reason) +
        " · 정답: " + f.expected.title + heard));
    });
    var hl = $("sc-hints");
    hl.textContent = "";
    if (!rep.hints.length) { hl.appendChild(el("li", null, "없음")); }
    rep.hints.forEach(function (h) { hl.appendChild(el("li", null, h.message)); });
    $("sc-caveat").textContent = rep.caveat || "";
  }

  function stopPolling() {
    if (state.scTimer) { clearTimeout(state.scTimer); state.scTimer = null; }
  }

  async function pollJob(jobId, agentId) {
    stopPolling();
    if (agentId !== state.agentId) { return; }
    var status = $("scorecard-status");
    var r = await api("GET", "/api/scorecards/" + encodeURIComponent(jobId));
    if (agentId !== state.agentId) { return; }
    if (!r.ok) {
      status.textContent = r.status === 404 ? "성적표 작업이 사라졌습니다. 다시 시험해 주세요." : errMessage(r.data, r.status);
      $("scorecard-btn").disabled = false;
      return;
    }
    var job = r.data;
    if (job.status === "queued") {
      status.textContent = "대기 중…";
    } else if (job.status === "running") {
      status.textContent = "시험하는 중 " + job.progress.done + " / " + job.progress.total;
    } else if (job.status === "done") {
      status.textContent = "완료 (질문 " + job.report.question_count + "개)";
      renderReport(job.report);
      $("scorecard-btn").disabled = false;
      return;
    } else {
      status.textContent = "실패: " + ((job.error && job.error.message) || "알 수 없는 오류") + " — 다시 시험해 주세요.";
      $("scorecard-btn").disabled = false;
      return;
    }
    state.scTimer = setTimeout(function () { pollJob(jobId, agentId); }, 1000);
  }

  async function startScorecard() {
    var status = $("scorecard-status");
    if (!state.agentId) { status.textContent = "먼저 상담원을 고르거나 만들어 주세요."; return; }
    var n = parseInt($("sc-n").value, 10) || 30;
    $("scorecard-btn").disabled = true;
    $("scorecard-report").hidden = true;
    status.textContent = "제출하는 중…";
    var agentId = state.agentId;
    var r = await api("POST", "/api/agents/" + encodeURIComponent(agentId) + "/scorecards", { n: n });
    var jobId = null;
    if (r.ok) { jobId = r.data.job_id; }
    else if (r.status === 409 && r.data && r.data.detail && r.data.detail.job_id) { jobId = r.data.detail.job_id; }
    if (!jobId) {
      status.textContent = errMessage(r.data, r.status);
      $("scorecard-btn").disabled = false;
      return;
    }
    pollJob(jobId, agentId);
  }

  // ---------- A/B compare ----------
  var abSides = {};

  function renderSide(side, data) {
    var box = document.querySelector('.ab-side[data-side="' + side + '"]');
    var fa = box.querySelector(".ab-first-audio");
    fa.textContent = "첫 음성까지 " + fmtMs(data.timings.first_audio_ms) + " · " + data.sentence_count + "문장 · " +
      data.char_count + "자";
    var list = box.querySelector(".ab-sentences");
    list.textContent = "";
    data.sentences.forEach(function (s) {
      var p = el("p", "sentence", s.text);
      p.dataset.supported = s.supported ? "true" : "false";
      if (!s.supported && data.answer_kind === "grounded") { p.appendChild(el("span", "no-evidence", "근거 없음")); }
      list.appendChild(p);
    });
    box.dataset.kind = data.answer_kind;
    abSides[side] = data;
  }

  async function compare() {
    var status = $("ab-status");
    var text = $("ask-input").value.trim();
    if (!state.agentId) { status.textContent = "먼저 상담원을 고르거나 만들어 주세요."; return; }
    if (!text) { status.textContent = "질문 칸에 비교할 질문을 적어 주세요."; return; }
    if (!state.sessionId && !(await openSession())) { return; }
    $("ab-btn").disabled = true;
    status.textContent = "비교하는 중… (최대 1분)";
    $("ab-notes").textContent = "";
    try {
      var r = await api("POST", "/api/agents/" + encodeURIComponent(state.agentId) + "/compare", {
        session_id: state.sessionId, question: text,
        a: { answer_length: $("ab-a-length").value }, b: { answer_length: $("ab-b-length").value }
      });
      if (!r.ok) { status.textContent = errMessage(r.data, r.status); return; }
      renderSide("a", r.data.a);
      renderSide("b", r.data.b);
      (r.data.notes || []).forEach(function (n) { $("ab-notes").appendChild(el("li", null, n)); });
      $("questions-left").textContent = r.data.questions_left;
      status.textContent = "";
    } catch (e) {
      status.textContent = "서버에 연결하지 못했습니다.";
    } finally {
      $("ab-btn").disabled = false;
    }
  }

  function playSide(side) {
    var data = abSides[side];
    if (!data) { return; }
    var seq = resetPlayback();
    var nodes = document.querySelectorAll('.ab-side[data-side="' + side + '"] .ab-sentences .sentence');
    data.sentences.slice().sort(function (x, y) { return x.index - y.index; }).forEach(function (s, i) {
      enqueueAudio(seq, i, s.audio_wav_b64, nodes[i]);
    });
  }

  // ---------- wiring ----------
  $("create-btn").addEventListener("click", createAgent);
  $("ask-btn").addEventListener("click", ask);
  $("ask-input").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); ask(); }
  });
  $("transparent-toggle").addEventListener("change", function (e) {
    $("chat-log").classList.toggle("transparent", e.target.checked);
  });
  $("scorecard-btn").addEventListener("click", startScorecard);
  $("ab-btn").addEventListener("click", compare);
  document.querySelectorAll(".ab-play").forEach(function (b) {
    b.addEventListener("click", function () { playSide(b.dataset.side); });
  });

  async function init() {
    await Promise.all([loadOptions(), loadPresets()]);
    var agentParam = new URLSearchParams(location.search).get("agent");
    if (agentParam) { await openAgent(agentParam); }
    else if (presets.length) { await openAgent(presets[0].agent_id); }
    document.body.dataset.ready = "true";
  }

  init();
})();
