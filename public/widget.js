/*
 * منارة — embeddable chat widget for anu.edu.eg
 *
 * Add one line to the university site, right before </body>:
 *   <script src="https://bot.anu.edu.eg/widget.js" defer></script>
 *
 * Everything renders inside an iframe on purpose: the university site ships
 * Bootstrap, and an inline widget would inherit its resets and break. The
 * iframe gives the chat its own CSS world with zero risk to the host page.
 */
(function () {
  "use strict";

  var origin = (function () {
    var self = document.currentScript;
    return self ? new URL(self.src, location.href).origin : "";
  })();

  var open = false;
  var frame = null;

  var css = [
    ".anu-fab{position:fixed;inset-inline-end:20px;bottom:20px;z-index:2147483000;",
    "width:58px;height:58px;border-radius:50%;border:0;cursor:pointer;background:#08202f;",
    "box-shadow:0 10px 30px -10px rgba(8,32,47,.6);display:grid;place-items:center;",
    "transition:transform .18s ease}",
    ".anu-fab:hover{transform:translateY(-2px)}",
    ".anu-fab svg{width:28px;height:28px}",
    ".anu-frame{position:fixed;inset-inline-end:20px;bottom:88px;z-index:2147483000;",
    "width:380px;height:min(560px,72vh);border:0;border-radius:14px;background:#fff;",
    "box-shadow:0 24px 60px -24px rgba(8,32,47,.55);display:none}",
    ".anu-frame.on{display:block}",
    "@media (max-width:480px){.anu-frame{inset-inline:12px;width:auto;bottom:84px;height:70vh}}"
  ].join("");

  var mark =
    '<svg viewBox="0 0 64 64" aria-hidden="true">' +
    '<g fill="none" stroke="#0e8b8b" stroke-width="4" stroke-linejoin="round" stroke-linecap="round">' +
    '<path d="M24 56 L26.5 32 L37.5 32 L40 56 Z"/><path d="M27 32 L28.5 20 L35.5 20 L37 32"/></g>' +
    '<circle cx="32" cy="14" r="5.5" fill="#f4b740"/></svg>';

  function mount() {
    var style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);

    var fab = document.createElement("button");
    fab.className = "anu-fab";
    fab.type = "button";
    fab.setAttribute("aria-label", "افتح مساعد القبول");
    fab.setAttribute("aria-expanded", "false");
    fab.innerHTML = mark;

    fab.addEventListener("click", function () {
      if (!frame) {
        frame = document.createElement("iframe");
        frame.className = "anu-frame";
        frame.title = "منارة — مساعد القبول";
        frame.src = origin + "/?embed=1";
        document.body.appendChild(frame);
      }
      open = !open;
      frame.classList.toggle("on", open);
      fab.setAttribute("aria-expanded", String(open));
      fab.setAttribute("aria-label", open ? "اقفل مساعد القبول" : "افتح مساعد القبول");
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && open) fab.click();
    });

    document.body.appendChild(fab);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
