(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var question = $("question");
  var askBtn = $("ask");
  var result = $("result");
  var errorEl = $("error");

  function ms(v) { return Math.round((Number(v) || 0) * 10) / 10; }

  function setState(state) { result.dataset.state = state; }

  function showError(message) {
    setState("error");
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  // SSE endpoints: /api/ask-stream (text), /api/ask-audio-stream (mic) — §4.2 wire format
  var reqSeq = 0;
  var playback = null;
  var audioEl = $("audio");

  function stopPlayback() {
    audioEl.pause();
    audioEl.removeAttribute("src");
    audioEl.load();
    if (playback) { playback.playing = false; }
  }

  function newPlayback() {
    stopPlayback();
    reqSeq += 1;
    playback = { id: reqSeq, items: [], pos: 0, playing: false, tFetch: performance.now() };
    return playback;
  }

  function playNext(pb) {
    if (pb !== playback) { return; }
    if (pb.pos >= pb.items.length) { pb.playing = false; return; }
    var item = pb.items[pb.pos];
    pb.playing = true;
    item.li.className = "playing";
    audioEl.src = item.src;
    var p = audioEl.play(); if (p && p.catch) { p.catch(function () {}); }
  }

  audioEl.addEventListener("ended", function () {
    var pb = playback;
    if (!pb || !pb.playing || pb.pos >= pb.items.length) { return; }
    pb.items[pb.pos].li.className = "played";
    pb.pos += 1;
    playNext(pb);
  });

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

  function handleEvent(pb, ev, emptyMsg) {
    if (pb !== playback) { return true; }
    var d = ev.data || {};
    if (ev.event === "meta") {
      $("transcript").textContent = "👤 " + d.transcript;
      $("answer").textContent = d.answer;
      $("source").textContent = "출처: " + (d.source ? d.source.id : "없음");
      $("timings").textContent = "";
      $("first-audio").textContent = "";
      $("sentences").textContent = "";
      setState("speaking");
    } else if (ev.event === "audio") {
      var li = document.createElement("li");
      li.textContent = d.text;
      $("sentences").appendChild(li);
      pb.items.push({ li: li, src: "data:audio/wav;base64," + d.audio_wav_b64 });
      if (d.index === 0) {
        $("first-audio").textContent = "🔊 첫 음성 " + ms(d.elapsed_ms) + "ms · 체감 " +
          Math.round(performance.now() - pb.tFetch) + "ms";
      }
      if (!pb.playing) { playNext(pb); }
    } else if (ev.event === "done") {
      var t = d.timings || {};
      $("timings").textContent =
        "⏱ 듣기 " + ms(t.stt_ms) + "ms · 검색 " + ms(t.retrieve_ms) +
        "ms · 생각 " + ms(t.llm_ms) + "ms · 말하기 " + ms(t.tts_ms) + "ms";
      setState("answered");
      return true;
    } else if (ev.event === "error") {
      showError(d.detail === "no speech recognized" ? emptyMsg : "답변을 가져오지 못했습니다.");
      return true;
    }
    return false;
  }

  async function readStream(res, pb, emptyMsg) {
    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    for (;;) {
      var chunk = await reader.read();
      if (chunk.done) { buffer += decoder.decode(); buffer += "\n\n"; }
      else { buffer += decoder.decode(chunk.value, { stream: true }); }
      var parsed = parseSse(buffer.replace(/\r\n/g, "\n"));
      buffer = parsed.rest;
      for (var i = 0; i < parsed.events.length; i++) {
        if (handleEvent(pb, parsed.events[i], emptyMsg)) {
          try { reader.cancel(); } catch (e) { /* ignore */ }
          return;
        }
      }
      if (chunk.done) {
        if (pb === playback) { showError("답변을 가져오지 못했습니다."); }
        return;
      }
    }
  }

  async function ask() {
    errorEl.hidden = true;
    errorEl.textContent = "";
    setState("loading");
    askBtn.disabled = true;
    var pb = newPlayback();
    try {
      var res = await fetch("/api/ask-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: question.value })
      });
      if (!res.ok) {
        var msg = res.status === 422
          ? "질문을 입력해 주세요. (422)"
          : "답변을 가져오지 못했습니다. (" + res.status + ")";
        showError(msg);
        return;
      }
      await readStream(res, pb, "질문을 입력해 주세요. (422)");
    } catch (e) {
      showError("서버에 연결하지 못했습니다.");
    } finally {
      askBtn.disabled = false;
    }
  }

  var MAX_RECORD_MS = 15000;
  var micBtn = $("mic");
  var recorder = null;
  var stream = null;
  var chunks = [];
  var recordTimer = null;

  async function startRecording() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      showError("이 브라우저는 마이크 녹음을 지원하지 않습니다.");
      return;
    }
    errorEl.hidden = true;
    errorEl.textContent = "";
    micBtn.disabled = true;
    askBtn.disabled = true;
    stopPlayback();
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      stream = null;
      micBtn.disabled = false;
      askBtn.disabled = false;
      showError("마이크 권한이 필요합니다. 브라우저 설정에서 마이크를 허용해 주세요.");
      return;
    }
    chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = function (e) {
      if (e.data && e.data.size > 0) { chunks.push(e.data); }
    };
    recorder.onstop = sendRecording;
    recorder.start();
    micBtn.classList.add("recording");
    micBtn.setAttribute("aria-pressed", "true");
    micBtn.disabled = false;
    setState("recording");
    recordTimer = setTimeout(stopRecording, MAX_RECORD_MS);
  }

  function stopRecording() {
    if (recordTimer) { clearTimeout(recordTimer); recordTimer = null; }
    if (recorder && recorder.state !== "inactive") { recorder.stop(); }
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
    micBtn.classList.remove("recording");
    micBtn.setAttribute("aria-pressed", "false");
    micBtn.disabled = true;
  }

  async function sendRecording() {
    var blob = new Blob(chunks, { type: (recorder && recorder.mimeType) || "audio/webm" });
    recorder = null;
    chunks = [];
    setState("transcribing");
    var pb = newPlayback();
    try {
      var res = await fetch("/api/ask-audio-stream", {
        method: "POST",
        headers: { "Content-Type": blob.type },
        body: blob
      });
      if (!res.ok) {
        var msg;
        if (res.status === 422) { msg = "말씀이 들리지 않았어요. 다시 말씀해 주세요. (422)"; }
        else if (res.status === 415) { msg = "지원하지 않는 녹음 형식입니다. (415)"; }
        else if (res.status === 413) { msg = "녹음이 너무 깁니다. (413)"; }
        else { msg = "답변을 가져오지 못했습니다. (" + res.status + ")"; }
        showError(msg);
        return;
      }
      await readStream(res, pb, "말씀이 들리지 않았어요. 다시 말씀해 주세요. (422)");
    } catch (e) {
      showError("서버에 연결하지 못했습니다.");
    } finally {
      micBtn.disabled = false;
      askBtn.disabled = false;
    }
  }

  micBtn.addEventListener("click", function () {
    if (recorder && recorder.state === "recording") { stopRecording(); } else { startRecording(); }
  });

  askBtn.addEventListener("click", ask);
  question.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); ask(); }
  });
})();
