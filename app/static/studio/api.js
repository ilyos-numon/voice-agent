(function () {
  "use strict";

  var DEFAULT_TEXT = "답을 가져오지 못했습니다. 다시 시도해 주세요.";
  var AUDIO_TEXT = "녹음을 읽지 못했습니다. 다시 녹음해 주세요.";

  var ERROR_TEXT = {
    network: "서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
    busy: "지금 요청이 많습니다. 잠시 뒤 다시 시도해 주세요.",
    question_limit: "이 세션의 질문 수를 다 썼습니다. 새 세션을 열어 주세요.",
    session_not_found: "대화 세션이 끝났습니다. 새 세션을 열었습니다.",
    agent_not_found: "상담원을 찾을 수 없습니다. 만료되었거나 지워졌을 수 있습니다.",
    no_speech: "말소리를 듣지 못했습니다. 다시 말씀해 주세요.",
    audio_decode_failed: AUDIO_TEXT,
    unsupported_audio: AUDIO_TEXT,
    empty_audio: AUDIO_TEXT,
    audio_too_large: AUDIO_TEXT,
    mic_denied: "마이크 권한이 없어 글자로만 물을 수 있습니다.",
    mic_unsupported: "이 브라우저에서는 녹음을 쓸 수 없습니다. 글자로 물어보세요.",
    validation: "입력 값을 확인해 주세요.",
    internal: DEFAULT_TEXT
  };

  var MY_AGENTS_KEY = "va:studio:my-agents";
  var THEME_KEY = "theme";

  function hasOwn(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj, key);
  }

  // Table first; a server message is used only for codes the table does not know.
  function errorText(error) {
    if (!error) { return DEFAULT_TEXT; }
    var code = error.code;
    if (code && hasOwn(ERROR_TEXT, code)) { return ERROR_TEXT[code]; }
    return error.message || DEFAULT_TEXT;
  }

  function networkError() {
    return { code: "network", message: ERROR_TEXT.network, status: 0 };
  }

  function errorFromBody(body, status) {
    var d = body && body.detail;
    var err;
    if (Array.isArray(d)) {
      err = { code: "validation", message: ERROR_TEXT.validation, status: status };
      var first = d[0];
      if (first && Array.isArray(first.loc)) {
        err.loc = first.loc.map(function (x) { return String(x); });
      }
      return err;
    }
    if (d && typeof d === "object" && d.code) {
      err = { code: String(d.code), status: status };
      err.message = d.message || errorText({ code: err.code });
      if (d.job_id) { err.job_id = String(d.job_id); }
      return err;
    }
    var code = status === 422 ? "validation" : "internal";
    return { code: code, message: errorText({ code: code }), status: status };
  }

  async function readJson(res) {
    if (!res || res.status === 204) { return null; }
    var ctype = (res.headers && res.headers.get("Content-Type")) || "";
    if (ctype.indexOf("json") < 0) { return null; }
    try { return await res.json(); } catch (e) { return null; }
  }

  function isBlob(body) {
    return typeof Blob !== "undefined" && body instanceof Blob;
  }

  // ---------- demo token ----------
  // Cached Promise of the token from GET /api/demo (null when demo mode is off).
  var DEMO_TOKEN_HEADER = "X-Demo-Token";
  var demoTokenPromise = null;

  function demoToken() {
    if (!demoTokenPromise) {
      var p = fetch("/api/demo", { method: "GET", headers: { "Accept": "application/json" } })
        .then(function (res) { return res.ok ? res.json() : null; })
        .then(function (body) {
          return (body && typeof body.token === "string" && body.token) ? body.token : null;
        })
        .catch(function () {
          if (demoTokenPromise === p) { demoTokenPromise = null; }
          return null;
        });
      demoTokenPromise = p;
    }
    return demoTokenPromise;
  }

  async function headersWithToken(headers) {
    var out = {};
    if (headers) {
      Object.keys(headers).forEach(function (k) { out[k] = headers[k]; });
    }
    var token = await demoToken();
    if (typeof token === "string" && token) { out[DEMO_TOKEN_HEADER] = token; }
    return out;
  }

  function isTokenRequired(status, data) {
    var d = data && data.detail;
    return status === 403 && !!d && typeof d === "object" && d.code === "demo_token_required";
  }

  async function request(method, path, body) {
    var baseHeaders = {};
    var payload;
    if (body !== undefined && body !== null) {
      if (isBlob(body)) {
        payload = body;
      } else {
        baseHeaders["Content-Type"] = "application/json";
        payload = JSON.stringify(body);
      }
    }
    for (var attempt = 0; ; attempt++) {
      var opt = { method: method, headers: await headersWithToken(baseHeaders) };
      if (payload !== undefined) { opt.body = payload; }
      var res;
      try {
        res = await fetch(path, opt);
      } catch (e) {
        return { ok: false, status: 0, data: null, error: networkError() };
      }
      var data = await readJson(res);
      if (res.ok) {
        return { ok: true, status: res.status, data: data, error: null };
      }
      if (attempt === 0 && isTokenRequired(res.status, data)) {
        demoTokenPromise = null;
        continue;
      }
      return { ok: false, status: res.status, data: data, error: errorFromBody(data, res.status) };
    }
  }

  // ---------- SSE ----------
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

  function incompleteError() {
    return { code: "incomplete", message: DEFAULT_TEXT, status: 0 };
  }

  async function readSse(response, onEvent, signal) {
    var finished = false;
    if (!response || !response.body) {
      onEvent("error", incompleteError());
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
        if (!ev) { continue; }
        onEvent(ev.name, ev.data);
        if (ev.name === "done" || ev.name === "error") {
          finished = true;
          try { reader.cancel(); } catch (e2) { /* ignore */ }
          return;
        }
      }
      if (chunk.done) { break; }
    }
    if (!finished && !(signal && signal.aborted)) {
      onEvent("error", incompleteError());
    }
  }

  function isAbort(e, signal) {
    return (signal && signal.aborted) || (e && e.name === "AbortError");
  }

  async function streamTurn(path, init, handlers, signal) {
    handlers = handlers || {};
    function call(name, data) {
      var fn = handlers[name];
      if (typeof fn === "function") { fn(data); }
    }
    if (signal) { init.signal = signal; }
    var baseHeaders = init.headers;
    var res;
    for (var attempt = 0; ; attempt++) {
      init.headers = await headersWithToken(baseHeaders);
      if (signal && signal.aborted) { return; }
      try {
        res = await fetch(path, init);
      } catch (e) {
        if (isAbort(e, signal)) { return; }
        call("error", networkError());
        return;
      }
      if (res.ok) { break; }
      var data = await readJson(res);
      if (signal && signal.aborted) { return; }
      if (attempt === 0 && isTokenRequired(res.status, data)) {
        demoTokenPromise = null;
        continue;
      }
      call("error", errorFromBody(data, res.status));
      return;
    }
    await readSse(res, function (name, data) {
      if (signal && signal.aborted) { return; }
      data = data || {};
      if (name === "error") {
        var err = { code: data.code || "internal", status: 0 };
        err.message = data.message || errorText({ code: err.code });
        call("error", err);
        return;
      }
      call(name, data);
    }, signal);
  }

  function turnsBase(agentId) {
    return "/api/agents/" + encodeURIComponent(agentId) + "/turns";
  }

  function askText(agentId, sessionId, text, handlers, signal) {
    return streamTurn(turnsBase(agentId) + "/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, text: text })
    }, handlers, signal);
  }

  function askAudio(agentId, sessionId, blob, handlers, signal) {
    return streamTurn(
      turnsBase(agentId) + "/audio-stream?session_id=" + encodeURIComponent(sessionId),
      { method: "POST", body: blob },
      handlers, signal);
  }

  // ---------- formatting ----------
  function formatMs(ms) {
    var n = Math.round(Number(ms) || 0);
    if (n >= 1000) { return (n / 1000).toFixed(1) + "s"; }
    return n + "ms";
  }

  // ---------- audio ----------
  // Plays sentence audio strictly in index order. The audio element is created lazily.
  function AudioQueue() {
    this.el = null;
    this.gen = 0;
    this.items = [];
    this.pos = 0;
    this.playing = false;
    this.listeners = [];
  }

  AudioQueue.prototype._emit = function (index, state) {
    this.listeners.forEach(function (fn) {
      try { fn(index, state); } catch (e) { /* ignore */ }
    });
  };

  AudioQueue.prototype.onstate = function (fn) {
    if (typeof fn === "function") { this.listeners.push(fn); }
  };

  AudioQueue.prototype._audio = function () {
    if (this.el) { return this.el; }
    if (typeof Audio === "undefined") { return null; }
    var self = this;
    var el = new Audio();
    el.addEventListener("ended", function () { self._advance(self.gen); });
    el.addEventListener("error", function () {
      if (self.playing) { self._advance(self.gen); }
    });
    this.el = el;
    return el;
  };

  AudioQueue.prototype.push = function (index, b64) {
    var idx = Number(index);
    if (!(idx >= 0) || Math.floor(idx) !== idx) { return; }
    this.items[idx] = { src: b64 ? "data:audio/wav;base64," + b64 : null };
    this._emit(idx, "queued");
    if (!this.playing) { this._playNext(); }
  };

  AudioQueue.prototype.stop = function () {
    this.gen += 1;
    if (this.playing && this.items[this.pos]) { this._emit(this.pos, "played"); }
    this.items = [];
    this.pos = 0;
    this.playing = false;
    if (this.el) {
      try { this.el.pause(); } catch (e) { /* ignore */ }
      this.el.removeAttribute("src");
    }
  };

  AudioQueue.prototype._playNext = function () {
    var self = this;
    var el = this._audio();
    var item;
    for (;;) {
      item = this.items[this.pos];
      if (!item) { this.playing = false; return; }
      if (item.src && el) { break; }
      this._emit(this.pos, "played");
      this.pos += 1;
    }
    this.playing = true;
    this._emit(this.pos, "playing");
    var gen = this.gen;
    el.src = item.src;
    var p;
    try {
      p = el.play();
    } catch (e) {
      self._advance(gen);
      return;
    }
    if (p && p.catch) { p.catch(function () { self._advance(gen); }); }
  };

  AudioQueue.prototype._advance = function (gen) {
    if (gen !== this.gen || !this.playing) { return; }
    if (this.items[this.pos]) { this._emit(this.pos, "played"); }
    this.pos += 1;
    this.playing = false;
    this._playNext();
  };

  function playSequence(b64List) {
    var q = new AudioQueue();
    (b64List || []).forEach(function (b64, i) { q.push(i, b64); });
    return { stop: function () { q.stop(); } };
  }

  // ---------- links / storage ----------
  function shareUrl(agentId) {
    return location.origin + "/studio/app?agent=" + encodeURIComponent(agentId);
  }

  function storage() {
    try {
      return (typeof localStorage !== "undefined") ? localStorage : null;
    } catch (e) {
      return null;
    }
  }

  function readMyAgents() {
    var s = storage();
    if (!s) { return []; }
    try {
      var v = JSON.parse(s.getItem(MY_AGENTS_KEY) || "[]");
      if (!Array.isArray(v)) { return []; }
      var out = [];
      v.forEach(function (x) {
        if (typeof x === "string" && x && out.indexOf(x) < 0) { out.push(x); }
      });
      return out;
    } catch (e) {
      return [];
    }
  }

  function writeMyAgents(list) {
    var s = storage();
    if (!s) { return; }
    try { s.setItem(MY_AGENTS_KEY, JSON.stringify(list)); } catch (e) { /* ignore */ }
  }

  var myAgents = {
    list: function () { return readMyAgents(); },
    add: function (id) {
      if (!id) { return; }
      id = String(id);
      var list = readMyAgents();
      if (list.indexOf(id) >= 0) { return; }
      list.push(id);
      writeMyAgents(list);
    },
    remove: function (id) {
      id = String(id);
      writeMyAgents(readMyAgents().filter(function (x) { return x !== id; }));
    }
  };

  // ---------- toast ----------
  var TOAST_CLASS = {
    info: "bg-inverse-surface text-inverse-on-surface",
    success: "bg-inverse-surface text-inverse-on-surface",
    error: "bg-error text-on-error"
  };
  var TOAST_ICON = { info: "info", success: "check_circle", error: "error" };

  function toast(message, kind) {
    if (typeof document === "undefined") { return; }
    var box = document.getElementById("toast-container");
    if (!box) { return; }
    var k = hasOwn(TOAST_CLASS, kind) ? kind : "info";
    var node = document.createElement("div");
    node.className = "flex items-center gap-2 px-4 py-3 rounded-lg shadow-lg font-body-sm text-body-sm " + TOAST_CLASS[k];
    node.setAttribute("role", k === "error" ? "alert" : "status");
    node.dataset.kind = k;
    var icon = document.createElement("span");
    icon.className = "material-symbols-outlined";
    icon.textContent = TOAST_ICON[k];
    var text = document.createElement("span");
    text.textContent = String(message == null ? "" : message);
    node.appendChild(icon);
    node.appendChild(text);
    box.appendChild(node);
    setTimeout(function () {
      if (node.parentNode) { node.parentNode.removeChild(node); }
    }, 4000);
  }

  // ---------- theme ----------
  function applyTheme(dark) {
    if (typeof document === "undefined") { return; }
    document.documentElement.classList.toggle("dark", !!dark);
  }

  var theme = {
    init: function () {
      var s = storage();
      var saved = s ? s.getItem(THEME_KEY) : null;
      var dark;
      if (saved === "dark" || saved === "light") {
        dark = saved === "dark";
      } else {
        dark = typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches;
      }
      applyTheme(dark);
    },
    toggle: function () {
      if (typeof document === "undefined") { return; }
      var dark = !document.documentElement.classList.contains("dark");
      applyTheme(dark);
      var s = storage();
      if (s) {
        try { s.setItem(THEME_KEY, dark ? "dark" : "light"); } catch (e) { /* ignore */ }
      }
    }
  };

  window.StudioAPI = {
    request: request,
    askText: askText,
    askAudio: askAudio,
    errorText: errorText,
    formatMs: formatMs,
    AudioQueue: AudioQueue,
    playSequence: playSequence,
    shareUrl: shareUrl,
    myAgents: myAgents,
    toast: toast,
    theme: theme,
    presetMeta: {
      "civil-kiosk": { emoji: "🏛️", category: "공공/민원" },
      "restaurant": { emoji: "🍜", category: "주문/식당" },
      "hospital": { emoji: "🏥", category: "병원/접수" },
      "office-policy": { emoji: "🧑‍💼", category: "사내/HR" }
    },
    customEmoji: "🤖"
  };
})();
