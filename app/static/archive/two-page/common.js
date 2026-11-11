(function () {
  "use strict";

  var DEFAULT_TEXT = "답을 가져오지 못했습니다. 다시 시도해 주세요.";
  var VALIDATION_TEXT = "입력 값을 확인해 주세요.";

  var ERROR_TEXT = {
    agent_not_found: "이 상담원은 없거나 보관 기간(24시간)이 지나 사라졌습니다.",
    question_limit: "이번 대화에서 물어볼 수 있는 질문을 다 썼습니다. 페이지를 새로 고치면 다시 시작합니다.",
    busy: "지금 묻는 사람이 많습니다. 잠시 뒤 다시 눌러 주세요.",
    session_not_found: "대화가 끝났습니다. 페이지를 새로 고쳐 주세요.",
    capacity_full: "지금은 새 상담원을 더 만들 수 없습니다. 잠시 뒤 다시 시도해 주세요.",
    no_speech: "말씀이 들리지 않았어요. 버튼을 누르고 다시 말씀해 주세요.",
    audio_decode_failed: "녹음을 읽지 못했어요. 다시 녹음해 주세요.",
    unsupported_audio: "녹음을 읽지 못했어요. 다시 녹음해 주세요.",
    empty_audio: "녹음을 읽지 못했어요. 다시 녹음해 주세요.",
    audio_too_large: "녹음이 너무 깁니다. 짧게 말씀해 주세요.",
    mic_denied: "마이크를 쓸 수 없습니다. 주소창의 마이크 권한을 허용하거나 글자로 물어봐 주세요.",
    mic_unsupported: "이 브라우저에서는 녹음할 수 없습니다. 글자로 물어봐 주세요.",
    network: "서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
    incomplete: DEFAULT_TEXT,
    internal: DEFAULT_TEXT,
    validation: VALIDATION_TEXT
  };

  // codes whose server message is shown as-is
  var SERVER_MESSAGE_CODES = {
    knowledge_empty: true,
    knowledge_bad_csv: true,
    knowledge_too_large: true
  };

  function errorText(error) {
    if (!error) { return DEFAULT_TEXT; }
    var code = error.code;
    if (code && SERVER_MESSAGE_CODES[code]) {
      return error.message || DEFAULT_TEXT;
    }
    if (code && Object.prototype.hasOwnProperty.call(ERROR_TEXT, code)) {
      return ERROR_TEXT[code];
    }
    return error.message || DEFAULT_TEXT;
  }

  function errorFromBody(body) {
    var d = body && body.detail;
    if (Array.isArray(d)) {
      return { code: "validation", message: VALIDATION_TEXT };
    }
    if (d && typeof d === "object" && d.code) {
      return d;
    }
    return { code: "internal", message: "" };
  }

  async function api(method, path, body) {
    var opt = { method: method, headers: {} };
    if (body !== undefined && body !== null) {
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body);
    }
    var res;
    try {
      res = await fetch(path, opt);
    } catch (e) {
      return {
        ok: false, status: 0, data: null,
        error: { code: "network", message: (e && e.message) || "" }
      };
    }
    var data = null;
    if (res.status !== 204) {
      var ctype = res.headers.get("Content-Type") || "";
      if (ctype.indexOf("json") >= 0) {
        try { data = await res.json(); } catch (e2) { data = null; }
      }
    }
    if (res.ok) {
      return { ok: true, status: res.status, data: data, error: null };
    }
    return { ok: false, status: res.status, data: data, error: errorFromBody(data) };
  }

  function parseBlock(block) {
    var name = "message";
    var lines = [];
    block.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) { name = line.slice(6).trim(); }
      else if (line.indexOf("data:") === 0) { lines.push(line.slice(5).replace(/^ /, "")); }
    });
    if (!lines.length) { return null; }
    try {
      return { name: name, data: JSON.parse(lines.join("\n")) };
    } catch (e) {
      return null;
    }
  }

  async function readSse(response, onEvent) {
    var finished = false;
    function emit(ev) {
      onEvent(ev.name, ev.data);
      if (ev.name === "done" || ev.name === "error") { finished = true; }
      return finished;
    }
    if (!response || !response.body) {
      onEvent("error", { code: "incomplete", message: "" });
      return;
    }
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    for (;;) {
      var chunk;
      try {
        chunk = await reader.read();
      } catch (e) {
        break;
      }
      if (chunk.done) { buffer += decoder.decode() + "\n\n"; }
      else { buffer += decoder.decode(chunk.value, { stream: true }); }
      buffer = buffer.replace(/\r\n/g, "\n");
      var i;
      while ((i = buffer.indexOf("\n\n")) >= 0) {
        var block = buffer.slice(0, i);
        buffer = buffer.slice(i + 2);
        var ev = parseBlock(block);
        if (ev && emit(ev)) {
          try { reader.cancel(); } catch (e3) { /* ignore */ }
          return;
        }
      }
      if (chunk.done) { break; }
    }
    if (!finished) {
      onEvent("error", { code: "incomplete", message: "" });
    }
  }

  // Plays sentence audio strictly in index order.
  function AudioQueue(audioEl) {
    if (!(this instanceof AudioQueue)) { return new AudioQueue(audioEl); }
    this.el = audioEl;
    this.gen = 0;
    this.items = [];
    this.pos = 0;
    this.playing = false;
    var self = this;
    if (audioEl) {
      audioEl.addEventListener("ended", function () { self._advance(self.gen); });
      audioEl.addEventListener("error", function () {
        if (self.playing) { self._advance(self.gen); }
      });
    }
  }

  function setState(node, value) {
    if (node && node.dataset) { node.dataset.audio = value; }
  }

  AudioQueue.prototype.reset = function () {
    this.gen += 1;
    var cur = this.items[this.pos];
    if (cur && this.playing) { setState(cur.node, "played"); }
    this.items = [];
    this.pos = 0;
    this.playing = false;
    if (this.el) {
      try { this.el.pause(); } catch (e) { /* ignore */ }
      this.el.removeAttribute("src");
    }
  };

  AudioQueue.prototype.push = function (index, b64, node) {
    var idx = Number(index);
    if (!(idx >= 0)) { return; }
    this.items[idx] = { src: b64 ? "data:audio/wav;base64," + b64 : null, node: node || null };
    setState(node, "queued");
    if (!this.playing) { this._playNext(); }
  };

  AudioQueue.prototype.playList = function (list) {
    this.reset();
    var self = this;
    (list || []).slice().sort(function (a, b) { return a.index - b.index; })
      .forEach(function (it) { self.push(it.index, it.b64, it.node); });
  };

  AudioQueue.prototype._playNext = function () {
    var self = this;
    for (;;) {
      var item = this.items[this.pos];
      if (!item) { this.playing = false; return; }
      if (item.src && this.el) { break; }
      setState(item.node, "played");
      this.pos += 1;
    }
    this.playing = true;
    setState(item.node, "playing");
    var gen = this.gen;
    this.el.src = item.src;
    var p;
    try {
      p = this.el.play();
    } catch (e) {
      self._advance(gen);
      return;
    }
    if (p && p.catch) { p.catch(function () { self._advance(gen); }); }
  };

  AudioQueue.prototype._advance = function (gen) {
    if (gen !== this.gen || !this.playing) { return; }
    var item = this.items[this.pos];
    if (item) { setState(item.node, "played"); }
    this.pos += 1;
    this.playing = false;
    this._playNext();
  };

  function fmtMs(ms) {
    var n = Math.round(Number(ms) || 0);
    if (n >= 1000) { return (Math.round(n / 100) / 10) + "s"; }
    return n + "ms";
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    return e;
  }

  function param(name) {
    try {
      return new URLSearchParams(window.location.search).get(name);
    } catch (e) {
      return null;
    }
  }

  function talkUrl(agentId) {
    return "/talk?agent=" + encodeURIComponent(agentId);
  }

  var existing = window.VA || {};
  existing.api = api;
  existing.errorText = errorText;
  existing.readSse = readSse;
  existing.AudioQueue = AudioQueue;
  existing.fmtMs = fmtMs;
  existing.el = el;
  existing.param = param;
  existing.talkUrl = talkUrl;
  window.VA = existing;
})();
