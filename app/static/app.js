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

  askBtn.addEventListener("click", ask);
  question.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); ask(); }
  });
})();
