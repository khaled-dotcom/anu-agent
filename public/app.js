(function () {
  "use strict";

  if (/[?&]embed=1/.test(location.search)) document.body.classList.add("embed");

  var API = "/api/chat";
  var log = document.getElementById("log");
  var box = document.getElementById("q");
  var send = document.getElementById("send");
  var chips = document.getElementById("chips");
  var status = document.getElementById("status");
  var panel = document.getElementById("chat");
  var history = [];
  var busy = false;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function bubble(kind, text) {
    var node = el("div", "msg " + kind);
    node.appendChild(el("p", null, text || ""));
    log.appendChild(node);
    log.scrollTop = log.scrollHeight;
    return node;
  }

  // Model output is plain text; render paragraphs, never innerHTML.
  function paint(node, text) {
    node.textContent = "";
    text.split(/\n{2,}/).forEach(function (para) {
      var p = el("p");
      para.split("\n").forEach(function (line, i) {
        if (i) p.appendChild(document.createElement("br"));
        p.appendChild(document.createTextNode(line));
      });
      node.appendChild(p);
    });
  }

  function sources(node, list) {
    if (!list || !list.length) return;
    var wrap = el("div", "src");
    wrap.appendChild(el("strong", null, "المصدر"));
    list.forEach(function (s) {
      if (!s.url) return;
      var a = el("a", null, s.title || s.url);
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noopener";
      wrap.appendChild(a);
    });
    node.appendChild(wrap);
  }

  function setBusy(state) {
    busy = state;
    send.disabled = state;
    panel.classList.toggle("thinking", state);
    status.textContent = state ? "بيدوّر في موقع الجامعة…" : "جاهز للأسئلة";
  }

  async function ask(question) {
    if (busy || !question.trim()) return;
    bubble("user", question);
    history.push({ role: "user", content: question });
    box.value = "";
    box.style.height = "auto";
    setBusy(true);

    var node = bubble("bot", "");
    node.classList.add("cursor");
    var answer = "";

    try {
      var res = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question, history: history.slice(-6) })
      });

      if (res.status === 429) {
        node.remove();
        bubble("err", "في ضغط على الخدمة دلوقتي. استنى دقيقة وجرّب تاني.");
        setBusy(false);
        return;
      }
      if (!res.ok || !res.body) throw new Error("http " + res.status);

      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        var lines = buffer.split("\n\n");
        buffer = lines.pop();

        for (var i = 0; i < lines.length; i++) {
          var line = lines[i].trim();
          if (line.indexOf("data: ") !== 0) continue;
          var evt;
          try { evt = JSON.parse(line.slice(6)); } catch (e) { continue; }

          if (evt.type === "token") {
            answer += evt.text;
            paint(node, answer);
            log.scrollTop = log.scrollHeight;
          } else if (evt.type === "replace") {
            // Server-side guard caught an unverified number and swapped the answer.
            answer = evt.text;
            paint(node, answer);
          } else if (evt.type === "error") {
            node.remove();
            bubble("err", evt.text);
            answer = "";
          } else if (evt.type === "done") {
            sources(node, evt.sources);
          }
        }
      }
    } catch (err) {
      node.remove();
      bubble("err", "الاتصال بالخدمة اتقطع. اتأكد من النت وجرّب تاني.");
      answer = "";
    }

    node.classList.remove("cursor");
    if (answer) history.push({ role: "assistant", content: answer });
    setBusy(false);
    box.focus();
  }

  send.addEventListener("click", function () { ask(box.value); });

  box.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      ask(box.value);
    }
  });

  box.addEventListener("input", function () {
    box.style.height = "auto";
    box.style.height = Math.min(box.scrollHeight, 120) + "px";
  });

  chips.addEventListener("click", function (e) {
    if (e.target.tagName === "BUTTON") ask(e.target.textContent);
  });
})();
