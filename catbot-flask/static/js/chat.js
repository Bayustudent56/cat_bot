/* CatBot: antarmuka chat (Fetch API async ke /api/chat). */
(() => {
  "use strict";

  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const chips = document.querySelectorAll("#quick-replies .chip");
  if (!log || !form || !input) return;

  const SESSION_KEY = "catbot_session_id";
  const MIN_TYPING_MS = 450;
  let busy = false;

  function createSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID().replace(/-/g, "");
    }
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
  }

  function loadSessionId() {
    try {
      let id = window.localStorage.getItem(SESSION_KEY);
      if (!id) {
        id = createSessionId();
        window.localStorage.setItem(SESSION_KEY, id);
      }
      return id;
    } catch (_err) {
      return createSessionId(); // penyimpanan diblokir: sesi berlaku sementara
    }
  }

  let sessionId = loadSessionId();

  function scrollToBottom() {
    log.scrollTop = log.scrollHeight;
  }

  function addMessage(role, text, extraClass) {
    const row = document.createElement("div");
    row.className = "msg msg-" + role + (extraClass ? " " + extraClass : "");

    if (role !== "user") {
      const avatar = document.createElement("span");
      avatar.className = "avatar";
      avatar.setAttribute("aria-hidden", "true");
      row.appendChild(avatar);
    }

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text; // textContent mencegah injeksi HTML
    row.appendChild(bubble);

    log.appendChild(row);
    scrollToBottom();
    return row;
  }

  function showTyping() {
    const row = document.createElement("div");
    row.className = "msg msg-bot";
    row.setAttribute("aria-label", "CatBot sedang mengetik");

    const avatar = document.createElement("span");
    avatar.className = "avatar";
    avatar.setAttribute("aria-hidden", "true");

    const bubble = document.createElement("div");
    bubble.className = "bubble typing";
    for (let i = 0; i < 3; i += 1) bubble.appendChild(document.createElement("span"));

    row.append(avatar, bubble);
    log.appendChild(row);
    scrollToBottom();
    return row;
  }

  function setBusy(state) {
    busy = state;
    sendBtn.disabled = state;
    input.disabled = state;
    chips.forEach((chip) => { chip.disabled = state; });
    if (!state) input.focus();
  }

  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function sendMessage(rawText) {
    const text = rawText.trim();
    if (!text || busy) return;

    addMessage("user", text);
    input.value = "";
    setBusy(true);
    const typingRow = showTyping();
    const startedAt = Date.now();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });
      const data = await response.json().catch(() => ({}));

      const elapsed = Date.now() - startedAt;
      if (elapsed < MIN_TYPING_MS) await wait(MIN_TYPING_MS - elapsed);
      typingRow.remove();

      if (!response.ok) {
        addMessage("bot", data.error || "Maaf, terjadi kesalahan. Coba lagi sebentar.", "msg-error");
        return;
      }

      if (data.session_id && data.session_id !== sessionId) {
        sessionId = data.session_id;
        try { window.localStorage.setItem(SESSION_KEY, sessionId); } catch (_err) { /* diabaikan */ }
      }
      addMessage("bot", data.reply, data.intent === "darurat_kesehatan" ? "is-alert" : "");
    } catch (_err) {
      typingRow.remove();
      addMessage("bot", "Tidak bisa terhubung ke server. Periksa koneksimu, lalu coba lagi.", "msg-error");
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(input.value);
  });

  chips.forEach((chip) => {
    chip.addEventListener("click", () => sendMessage(chip.dataset.text || chip.textContent));
  });

  input.focus();
})();
