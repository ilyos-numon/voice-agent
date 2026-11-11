// Scorecard tab: submits a scorecard job, polls it every 1.5s (keeps polling when the tab is left),
// and renders the report. Uses window.StudioAPI and window.WS only.
(function () {
  "use strict";

  var API = window.StudioAPI;
  var POLL_MS = 1500;
  var STYLE_LABEL = { verbatim: "원문 그대로", colloquial: "사람 말투" };
  var REASON_LABEL = { wrong_chunk: "다른 답", no_answer: "답 못 함", misheard: "음성 인식 오류" };
  var CHANNEL_LABEL = { text: "글자 질문", voice: "음성 질문" };
  var BASIS_LABEL = { text: "글자 질문 기준", voice: "음성 질문 기준" };

  var jobId = null;
  var pollTimer = null;
  var running = false;
  var lastError = null;
  var bound = false;

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

  function ratio(part) {
    if (!part || !(part.total > 0)) { return "0 / 0"; }
    var pct = Math.round((part.hits / part.total) * 1000) / 10;
    return part.hits + " / " + part.total + " (" + pct + "%)";
  }

  // ---------- state ----------
  function setRunning(on) {
    running = on;
    var btn = $("scorecard-start-btn");
    if (btn) { btn.disabled = on; }
    var n = $("scorecard-n");
    if (n) { n.disabled = on; }
    var voice = $("scorecard-voice");
    if (voice) { voice.disabled = on || !voiceAvailable(); }
  }

  function voiceAvailable() {
    var opts = window.WS && WS.state.options;
    return !!(opts && opts.voice_input_available);
  }

  function showError(error) {
    lastError = error || { code: "internal" };
    var box = $("scorecard-error");
    if (box) {
      box.textContent = API.errorText(lastError);
      show(box, true);
    }
    show($("scorecard-retry-btn"), true);
  }

  function hideError() {
    lastError = null;
    var box = $("scorecard-error");
    if (box) { box.textContent = ""; }
    show(box, false);
    show($("scorecard-retry-btn"), false);
  }

  function setProgress(status, text, done, total) {
    var wrap = $("scorecard-progress");
    if (!wrap) { return; }
    wrap.dataset.status = status;
    show(wrap, true);
    setProgressIcon(wrap, status);
    var t = $("scorecard-progress-text");
    if (t) { t.textContent = text; }
    var bar = $("scorecard-progress-bar");
    if (bar) {
      var pct = (total > 0) ? Math.min(100, Math.round((done / total) * 100)) : 0;
      if (status === "done") { pct = 100; }
      bar.style.width = pct + "%";
    }
  }

  function setProgressIcon(wrap, status) {
    var icon = wrap.querySelector(".material-symbols-outlined");
    if (!icon) { return; }
    var moving = status === "queued" || status === "running";
    icon.textContent = moving ? "progress_activity" : (status === "done" ? "check_circle" : "error_outline");
    icon.classList.toggle("animate-spin", moving);
    icon.classList.toggle("text-primary", status !== "failed");
    icon.classList.toggle("text-error", status === "failed");
  }

  function stopPolling() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  // ---------- flow ----------
  async function start() {
    if (running || !window.WS || !WS.state.agentId) { return; }
    stopPolling();
    hideError();
    show($("scorecard-report"), false);
    setRunning(true);
    setProgress("queued", "시험을 준비하는 중…", 0, 0);

    var n = parseInt(($("scorecard-n") || {}).value, 10);
    if ([10, 20, 30].indexOf(n) < 0) { n = 30; }
    var voiceBox = $("scorecard-voice");
    var voice = !!(voiceBox && voiceBox.checked && voiceAvailable());

    var res = await API.request("POST",
      "/api/agents/" + encodeURIComponent(WS.state.agentId) + "/scorecards", { n: n, voice: voice });
    if (res.ok && res.data && res.data.job_id) {
      jobId = res.data.job_id;
      var pos = res.data.position;
      setProgress("queued", pos > 0 ? "대기 중 (" + pos + "번째)" : "시험을 시작하는 중…", 0, 0);
      schedule(0);
      return;
    }
    if (res.status === 409 && res.error && res.error.job_id) {
      jobId = res.error.job_id;
      setProgress("running", "이미 진행 중인 시험을 이어서 확인하는 중…", 0, 0);
      schedule(0);
      return;
    }
    fail(res.error);
  }

  function fail(error) {
    stopPolling();
    setRunning(false);
    var wrap = $("scorecard-progress");
    if (wrap) {
      wrap.dataset.status = "failed";
      setProgressIcon(wrap, "failed");
    }
    var t = $("scorecard-progress-text");
    if (t) { t.textContent = "시험을 마치지 못했습니다."; }
    showError(error);
  }

  function schedule(delay) {
    stopPolling();
    pollTimer = setTimeout(poll, delay);
  }

  async function poll() {
    pollTimer = null;
    if (!jobId) { return; }
    var current = jobId;
    var res = await API.request("GET", "/api/scorecards/" + encodeURIComponent(current));
    if (current !== jobId) { return; }
    if (!res.ok || !res.data) {
      if (res.error && res.error.code === "job_not_found") { jobId = null; }
      fail(res.error);
      return;
    }
    var job = res.data;
    var prog = job.progress || {};
    var done = Number(prog.done) || 0;
    var total = Number(prog.total) || 0;
    if (job.status === "queued") {
      setProgress("queued", "대기 중…", done, total);
      schedule(POLL_MS);
    } else if (job.status === "running") {
      setProgress("running", "시험하는 중… " + done + " / " + total, done, total);
      schedule(POLL_MS);
    } else if (job.status === "done") {
      setProgress("done", "시험을 마쳤습니다. " + done + " / " + total, done, total);
      setRunning(false);
      renderReport(job.report || {});
    } else {
      jobId = null;
      fail(job.error || { code: "internal" });
    }
  }

  function retry() {
    if (running) { return; }
    // Resume the same job after a temporary failure; submit again when the job is gone or failed.
    if (jobId && lastError && lastError.code !== "job_not_found") {
      hideError();
      setRunning(true);
      setProgress("running", "다시 확인하는 중…", 0, 0);
      schedule(0);
      return;
    }
    jobId = null;
    start();
  }

  // ---------- report ----------
  function renderReport(report) {
    var caveat = $("sc-caveat");
    if (caveat) {
      caveat.textContent = report.caveat || "질문은 자동으로 만든 것이라 실제 점수와 다를 수 있습니다.";
    }

    var textHits = $("sc-text-hits");
    if (textHits) { textHits.textContent = ratio(report.text); }

    var voiceHits = $("sc-voice-hits");
    if (voiceHits) {
      voiceHits.textContent = report.voice ? ratio(report.voice) : "이 서버에서는 음성 질문을 시험하지 않았습니다";
    }

    var first = $("sc-first-audio");
    if (first) {
      var fa = report.first_audio_ms;
      if (fa && fa.p50 != null) {
        var basis = BASIS_LABEL[report.first_audio_basis];
        first.textContent = "중앙값 " + API.formatMs(fa.p50) + " · 느린 쪽 5% " + API.formatMs(fa.p95) +
          (basis ? " (" + basis + ")" : "");
      } else {
        first.textContent = "-";
      }
    }

    renderByStyle(report.by_style || {});
    renderHints(report.hints || []);
    renderFailures(report.failures || []);
    show($("scorecard-report"), true);
  }

  function renderByStyle(byStyle) {
    var box = $("sc-by-style");
    if (!box) { return; }
    clear(box);
    var keys = Object.keys(byStyle);
    if (!keys.length) {
      box.appendChild(node("div", "text-on-surface-variant", "유형별 결과가 없습니다."));
      return;
    }
    keys.forEach(function (key) {
      var part = byStyle[key] || {};
      var row = node("div", "flex flex-col gap-1");
      var head = node("div", "flex items-center justify-between");
      head.appendChild(node("span", "text-on-surface-variant", STYLE_LABEL[key] || key));
      head.appendChild(node("span", "font-mono font-semibold text-on-surface", ratio(part)));
      var track = node("div", "w-full bg-surface-container-high rounded-full h-1.5");
      var fill = node("div", "bg-primary h-1.5 rounded-full");
      var pct = part.total > 0 ? Math.round((part.hits / part.total) * 100) : 0;
      fill.style.width = pct + "%";
      track.appendChild(fill);
      row.appendChild(head);
      row.appendChild(track);
      box.appendChild(row);
    });
  }

  function renderHints(hints) {
    var list = $("sc-hints");
    if (!list) { return; }
    clear(list);
    if (!hints.length) {
      list.appendChild(node("li", null, "눈에 띄는 고칠 점이 없습니다."));
      return;
    }
    hints.forEach(function (h) {
      list.appendChild(node("li", null, (h && h.message) || ""));
    });
  }

  function renderFailures(failures) {
    var box = $("sc-failures");
    if (!box) { return; }
    clear(box);
    if (!failures.length) {
      box.appendChild(node("div", "text-xs text-on-surface-variant", "틀린 질문이 없습니다."));
      return;
    }
    failures.forEach(function (f) {
      f = f || {};
      var card = node("div", "p-3 rounded-xl bg-surface border border-outline-variant/30 text-xs space-y-1");
      var head = node("div", "flex flex-wrap items-center gap-1.5");
      head.appendChild(node("span", "px-1.5 py-0.5 rounded bg-error-container/40 text-on-error-container text-[11px] font-medium",
        REASON_LABEL[f.reason] || f.reason || "틀림"));
      head.appendChild(node("span", "px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant text-[11px]",
        CHANNEL_LABEL[f.channel] || f.channel || ""));
      if (f.style) {
        head.appendChild(node("span", "px-1.5 py-0.5 rounded bg-surface-container text-on-surface-variant text-[11px]",
          STYLE_LABEL[f.style] || f.style));
      }
      card.appendChild(head);
      card.appendChild(node("div", "font-medium text-on-surface", "질문: " + (f.question || "")));
      if (f.heard) {
        card.appendChild(node("div", "text-on-surface-variant", "알아들은 말: " + f.heard));
      }
      var expected = f.expected && f.expected.title;
      if (expected) {
        card.appendChild(node("div", "text-on-surface-variant", "맞는 자료: " + expected));
      }
      card.appendChild(node("div", "text-on-surface-variant",
        "찾은 자료: " + ((f.got && f.got.title) || "찾지 못함")));
      box.appendChild(card);
    });
  }

  // ---------- init ----------
  function init() {
    if (bound) { return; }
    bound = true;
    var voice = $("scorecard-voice");
    if (voice && !voiceAvailable()) {
      voice.checked = false;
      voice.disabled = true;
      voice.title = "이 서버에서는 음성 질문을 시험할 수 없습니다";
    }
    var btn = $("scorecard-start-btn");
    if (btn) { btn.addEventListener("click", function () { start(); }); }
    var again = $("scorecard-retry-btn");
    if (again) { again.addEventListener("click", function () { retry(); }); }
  }

  if (window.WS) { WS.on("ready", init); }
})();
