(function () {
  "use strict";

  var EMAIL_RE = /^[^\s@<>"']+@[^\s@<>"']+\.[^\s@<>"']+$/;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text != null) { node.textContent = String(text); }
    return node;
  }

  function httpsUrl(value) {
    if (value.indexOf("https://") !== 0) { return null; }
    try {
      var u = new URL(value);
      return u.protocol === "https:" ? u.href : null;
    } catch (e) {
      return null;
    }
  }

  // E-mail -> mailto link, https URL -> link, anything else -> plain text, empty -> nothing.
  function contactNode(contact) {
    var value = typeof contact === "string" ? contact.trim() : "";
    if (!value) { return null; }
    var wrap = el("span", "", null);
    wrap.setAttribute("data-demo-contact", "");
    wrap.appendChild(el("span", "", "문의: "));
    var link = null;
    if (EMAIL_RE.test(value)) {
      link = el("a", "underline font-semibold break-all", value);
      link.href = "mailto:" + value;
    } else {
      var href = httpsUrl(value);
      if (href) {
        link = el("a", "underline font-semibold break-all", value);
        link.href = href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
    }
    wrap.appendChild(link || el("span", "font-semibold break-all", value));
    return wrap;
  }

  // contact_enc = base64(UTF-8 bytes of the contact with its characters reversed).
  function decodeContact(enc) {
    try {
      var bin = atob(enc);
      var bytes = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) { bytes[i] = bin.charCodeAt(i); }
      var text = new TextDecoder("utf-8").decode(bytes);
      return Array.from(text).reverse().join("");
    } catch (e) {
      return "";
    }
  }

  // Plaintext stays out of the DOM until the visitor clicks the reveal button.
  function contactRevealNode(enc) {
    if (typeof enc !== "string" || !enc) { return null; }
    var wrap = el("span", "", null);
    wrap.setAttribute("data-demo-contact", "");
    wrap.appendChild(el("span", "", "문의: "));
    var btn = el("button", "underline font-semibold", "연락처 보기");
    btn.type = "button";
    btn.setAttribute("data-demo-contact-reveal", "");
    btn.addEventListener("click", function () {
      var full = contactNode(decodeContact(enc));
      if (!full) { return; }
      var revealed = full.lastChild;
      if (revealed && btn.parentNode) { btn.parentNode.replaceChild(revealed, btn); }
    });
    wrap.appendChild(btn);
    return wrap;
  }

  function hideDocsLinks() {
    var links = document.querySelectorAll('a[href="/docs"]');
    for (var i = 0; i < links.length; i++) { links[i].hidden = true; }
  }

  function build(info) {
    var root = el("div", "w-full bg-secondary-container text-on-secondary-container border-b border-outline-variant/40", null);
    root.setAttribute("data-demo-banner", "");
    root.setAttribute("role", "note");
    var inner = el("div", "max-w-7xl mx-auto px-4 sm:px-6 lg:px-12 py-2 flex flex-col gap-1 text-[13px] leading-snug", null);
    var top = el("div", "flex flex-wrap items-center gap-x-3 gap-y-1", null);
    top.appendChild(el("span", "font-semibold", info.notice || ""));
    var contact = contactRevealNode(info.contact_enc);
    if (contact) { top.appendChild(contact); }
    var turns = info.remaining && typeof info.remaining.turns === "number" ? info.remaining.turns : null;
    if (turns !== null) {
      var rem = el("span", "font-semibold whitespace-nowrap", "오늘 남은 질문 " + turns + "회");
      rem.setAttribute("data-demo-remaining", "");
      top.appendChild(rem);
    }
    inner.appendChild(top);
    var privacy = el("div", "opacity-90", info.privacy_notice || "");
    privacy.setAttribute("data-demo-privacy", "");
    inner.appendChild(privacy);
    root.appendChild(inner);
    return root;
  }

  // Under a fixed header the banner goes first inside <main> (which already
  // has the header's top padding); otherwise right after the header.
  function place(banner) {
    var body = document.body;
    if (!body) { return; }
    var header = document.querySelector("body > header");
    var main = document.querySelector("main");
    if (header && main && getComputedStyle(header).position === "fixed") {
      main.insertBefore(banner, main.firstChild);
    } else if (header && header.parentNode) {
      header.parentNode.insertBefore(banner, header.nextSibling);
    } else {
      body.insertBefore(banner, body.firstChild);
    }
  }

  function init() {
    if (document.querySelector("[data-demo-banner]")) { return; }
    fetch("/api/demo", { method: "GET", headers: { "Accept": "application/json" } })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (info) {
        if (!info || info.demo_mode !== true) { return; }
        hideDocsLinks();
        place(build(info));
      })
      .catch(function () { /* draw nothing */ });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
