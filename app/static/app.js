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

  function render(data) {
    var t = data.timings || {};
    $("transcript").textContent = "👤 " + data.transcript;
    $("answer").textContent = data.answer;
    $("source").textContent = "출처: " + (data.source ? data.source.id : "없음");
    $("timings").textContent =
      "⏱ 듣기 " + ms(t.stt_ms) + "ms · 검색 " + ms(t.retrieve_ms) +
      "ms · 생각 " + ms(t.llm_ms) + "ms · 말하기 " + ms(t.tts_ms) + "ms";
    $("audio").src = "data:audio/wav;base64," + data.audio_wav_b64;
    var p = $("audio").play(); if (p && p.catch) { p.catch(function () {}); }
    setState("answered");
  }

  async function ask() {
    errorEl.hidden = true;
    errorEl.textContent = "";
    setState("loading");
    askBtn.disabled = true;
    try {
      var res = await fetch("/api/ask", {
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
      render(await res.json());
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
    try {
      var res = await fetch("/api/ask-audio", {
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
      render(await res.json());
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
