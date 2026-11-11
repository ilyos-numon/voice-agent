(function () {
  "use strict";

  var VA = window.VA;
  function $(id) { return document.getElementById(id); }

  var POLL_MS = 1000;
  var REASON_TEXT = {
    wrong_chunk: "다른 답",
    no_answer: "답 못 함",
    misheard: "잘못 알아들음"
  };

  // ---------- tabs ----------
  var tabs = [$("tab-scorecard"), $("tab-ab")];

  function selectTab(tab, focus) {
    tabs.forEach(function (t) {
      var on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      var panel = $(t.getAttribute("aria-controls"));
      if (panel) { panel.hidden = !on; }
    });
    if (focus) { tab.focus(); }
    if (tab.id === "tab-ab") { onAbShown(); }
  }

  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () { selectTab(t, false); });
    t.addEventListener("keydown", function (e) {
      var next = null;
      if (e.key === "ArrowRight") { next = tabs[(i + 1) % tabs.length]; }
      else if (e.key === "ArrowLeft") { next = tabs[(i - 1 + tabs.length) % tabs.length]; }
      if (next) {
        e.preventDefault();
        selectTab(next, true);
      }
    });
  });

  // ---------- scorecard ----------
  var talk = null;
  var scJob = null;
  var scTimer = null;
  var scResubmitted = false;

  function scStatus(text, isError) {
    var s = $("sc-status");
    s.textContent = text;
    s.classList.toggle("error", !!isError);
  }

  function stopPolling() {
    if (scTimer) { clearTimeout(scTimer); scTimer = null; }
  }

  function schedulePoll() {
    stopPolling();
    if (!scJob || document.hidden) { return; }
    scTimer = setTimeout(poll, POLL_MS);
  }

  function finishScorecard(buttonText) {
    scJob = null;
    stopPolling();
    var btn = $("sc-start");
    btn.disabled = false;
    btn.textContent = buttonText;
  }

  function showProgress(p) {
    var done = (p && p.done) || 0;
    var total = (p && p.total) || 0;
    var bar = $("sc-progress");
    bar.max = total > 0 ? total : 1;
    bar.value = total > 0 ? done : 0;
    return { done: done, total: total };
  }

  function hitsText(h) {
    return (h && h.hits || 0) + " / " + (h && h.total || 0);
  }

  function renderReport(report) {
    $("sc-text-hits").textContent = hitsText(report.text);
    $("sc-voice-hits").textContent = report.voice
      ? hitsText(report.voice)
      : "이 서버에서는 음성 질문을 시험하지 않았습니다";
    var fa = report.first_audio_ms || {};
    $("sc-p50").textContent = VA.fmtMs(fa.p50);
    $("sc-p95").textContent = VA.fmtMs(fa.p95);

    var fl = $("sc-failures");
    fl.textContent = "";
    var failures = report.failures || [];
    if (!failures.length) {
      fl.appendChild(VA.el("li", "muted", "틀린 질문이 없습니다."));
    }
    failures.forEach(function (f) {
      var got = f.got && f.got.title ? f.got.title : "찾지 못함";
      var label = REASON_TEXT[f.reason] || "다른 답";
      var channel = f.channel === "voice" ? "음성" : "글자";
      var text = "“" + (f.question || "") + "” → " + got + " (" + label + " · " + channel + ")";
      if (f.channel === "voice" && f.heard) { text += " — 알아들은 말: “" + f.heard + "”"; }
      fl.appendChild(VA.el("li", null, text));
    });

    var hl = $("sc-hints");
    hl.textContent = "";
    var hints = report.hints || [];
    if (!hints.length) {
      hl.appendChild(VA.el("li", "muted", "지금은 고칠 점이 없습니다."));
    }
    hints.forEach(function (h) { hl.appendChild(VA.el("li", null, h.message || "")); });

    $("sc-caveat").textContent = report.caveat || "";
    $("sc-report").hidden = false;
  }

  async function poll() {
    scTimer = null;
    var jobId = scJob;
    if (!jobId) { return; }
    var r = await VA.api("GET", "/api/scorecards/" + encodeURIComponent(jobId));
    if (jobId !== scJob) { return; }
    if (!r.ok) {
      if (r.status === 404 && r.error && r.error.code === "job_not_found" && !scResubmitted) {
        scResubmitted = true;
        scJob = null;
        submitScorecard();
        return;
      }
      if (r.status === 0) {
        scStatus(VA.errorText(r.error), true);
        schedulePoll();
        return;
      }
      scStatus(VA.errorText(r.error), true);
      finishScorecard("다시 시도");
      return;
    }
    var job = r.data || {};
    var p = showProgress(job.progress);
    if (job.status === "done") {
      if (job.report) { renderReport(job.report); }
      scStatus("다 됐습니다 " + p.done + "/" + p.total, false);
      finishScorecard("다시 시험해보기");
      return;
    }
    if (job.status === "failed") {
      scStatus((job.error && job.error.message) || VA.errorText(job.error), true);
      finishScorecard("다시 시도");
      return;
    }
    if (job.status === "running") {
      scStatus("진행 중 " + p.done + "/" + p.total, false);
    } else {
      scStatus("대기 중", false);
    }
    schedulePoll();
  }

  async function submitScorecard() {
    if (!talk) { return; }
    var btn = $("sc-start");
    btn.disabled = true;
    btn.textContent = "시험 중…";
    $("sc-report").hidden = true;
    showProgress(null);
    scStatus("대기 중", false);
    var n = parseInt($("sc-n").value, 10) || 10;
    var r = await VA.api("POST", "/api/agents/" + encodeURIComponent(talk.agentId) + "/scorecards",
      { n: n, voice: true });
    var jobId = null;
    if (r.ok && r.data) {
      jobId = r.data.job_id;
    } else if (r.status === 409 && r.error && r.error.job_id) {
      jobId = r.error.job_id;
    }
    if (!jobId) {
      scStatus(VA.errorText(r.error), true);
      finishScorecard("다시 시도");
      return;
    }
    scJob = jobId;
    poll();
  }

  $("sc-start").addEventListener("click", function () {
    if (scJob) { return; }
    scResubmitted = false;
    submitScorecard();
  });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { stopPolling(); }
    else if (scJob && !scTimer) { poll(); }
  });

  // ---------- A/B ----------
  var abQuestionTouched = false;
  var abSides = { a: [], b: [] };
  var abBusy = false;

  function firstSample() {
    var chip = document.querySelector("#sample-chips button.chip");
    return chip ? chip.textContent : "";
  }

  function defaultQuestion() {
    return (talk && talk.lastQuestion()) || firstSample() || "";
  }

  function onAbShown() {
    if (!talk || abQuestionTouched) { return; }
    var q = defaultQuestion();
    if (q) { $("ab-question").value = q; }
  }

  function fillLengthSelect(select, choices, value) {
    select.textContent = "";
    choices.forEach(function (c) {
      var o = VA.el("option", null, c.label);
      o.value = c.value;
      if (c.value === value) { o.selected = true; }
      select.appendChild(o);
    });
  }

  function renderSide(side, data) {
    var box = document.querySelector('.ab-side[data-side="' + side + '"]');
    var ans = box.querySelector(".ab-answer");
    ans.textContent = "";
    var nodes = [];
    var grounded = data.answer_kind === "grounded";
    (data.sentences || []).forEach(function (s) {
      var span = VA.el("span", "sentence", s.text);
      span.dataset.index = String(s.index);
      if (grounded && s.supported === false) {
        span.classList.add("unsupported");
        ans.appendChild(span);
        ans.appendChild(VA.el("span", "unsupported-tag", "근거 없음"));
      } else {
        ans.appendChild(span);
      }
      ans.appendChild(document.createTextNode(" "));
      nodes.push({ index: s.index, b64: s.audio_wav_b64, node: span });
    });
    var t = data.timings || {};
    box.querySelector(".ab-first-audio").textContent = "첫 음성까지 " + VA.fmtMs(t.first_audio_ms);
    box.querySelector(".ab-count").textContent =
      (data.sentence_count || 0) + "문장 · " + (data.char_count || 0) + "자";
    var play = box.querySelector(".ab-play");
    play.disabled = !nodes.some(function (n) { return n.b64; });
    abSides[side] = nodes;
  }

  async function runCompare() {
    if (!talk || abBusy) { return; }
    var status = $("ab-status");
    var q = String($("ab-question").value || "").trim();
    if (!q) {
      status.textContent = "비교할 질문을 적어 주세요.";
      status.classList.add("error");
      return;
    }
    abBusy = true;
    var btn = $("ab-start");
    btn.disabled = true;
    status.classList.remove("error");
    status.textContent = "비교 중…";
    var r = await VA.api("POST", "/api/agents/" + encodeURIComponent(talk.agentId) + "/compare", {
      session_id: talk.getSessionId(),
      question: q,
      a: { answer_length: $("ab-a-length").value },
      b: { answer_length: $("ab-b-length").value }
    });
    abBusy = false;
    btn.disabled = false;
    if (!r.ok) {
      if (r.status === 429 || (r.error && r.error.code === "question_limit")) {
        talk.setQuestionsLeft(0);
        btn.disabled = true;
      }
      status.textContent = VA.errorText(r.error);
      status.classList.add("error");
      return;
    }
    var d = r.data || {};
    talk.audio.reset();
    renderSide("a", d.a || {});
    renderSide("b", d.b || {});
    var notes = $("ab-notes");
    notes.textContent = "";
    (d.notes || []).forEach(function (n) { notes.appendChild(VA.el("li", null, n)); });
    $("ab-result").hidden = false;
    status.textContent = "";
    if (typeof d.questions_left === "number") {
      talk.setQuestionsLeft(d.questions_left);
      if (d.questions_left <= 0) { btn.disabled = true; }
    }
  }

  $("ab-question").addEventListener("input", function () { abQuestionTouched = true; });
  $("ab-start").addEventListener("click", runCompare);
  $("ab-question").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.isComposing) {
      e.preventDefault();
      runCompare();
    }
  });
  Array.prototype.forEach.call(document.querySelectorAll("button.ab-play"), function (b) {
    b.addEventListener("click", function () {
      if (!talk) { return; }
      talk.audio.playList(abSides[b.dataset.side] || []);
    });
  });

  // ---------- start ----------
  $("sc-start").disabled = true;
  $("ab-start").disabled = true;

  function onReady(t) {
    if (talk || !t) { return; }
    talk = t;
    var opts = t.options || {};
    var choices = opts.answer_length || [];
    fillLengthSelect($("ab-a-length"), choices, "one_sentence");
    fillLengthSelect($("ab-b-length"), choices, "detailed");
    var q = defaultQuestion();
    if (q) { $("ab-question").value = q; }
    $("sc-start").disabled = false;
    $("ab-start").disabled = false;
    scStatus("대기 중", false);
  }

  document.addEventListener("va:talk-ready", function (e) { onReady(e.detail || VA.talk); });
  if (VA && VA.talk) { onReady(VA.talk); }
})();
