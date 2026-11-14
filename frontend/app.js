const $ = (selector) => document.querySelector(selector);
const messages = $("#messages");
const messageInput = $("#message");
const sendButton = $("#sendButton");
const recordButton = $("#record");
const stopButton = $("#stop");
const quickButtons = [...document.querySelectorAll("[data-q]")];

let recorder = null;
let chunks = [];
let isBusy = false;
let isRecording = false;

function setBusy(busy, label = "Working on your request…") {
  isBusy = busy;
  messageInput.disabled = busy;
  sendButton.disabled = busy;
  quickButtons.forEach((button) => { button.disabled = busy; });
  recordButton.disabled = busy;
  stopButton.disabled = !busy || !isRecording;
  $("#processingStatus").classList.toggle("hidden", !busy);
  $("#processingText").textContent = label;
  if (busy) {
    $("#voiceStatus").textContent = label;
  }
}

function appendInline(parent, text) {
  // Safe, small Markdown subset. Text is always inserted as text, never raw HTML.
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parent.appendChild(document.createTextNode(text.slice(last, match.index)));
    const token = match[0];
    const el = document.createElement(token.startsWith("**") ? "strong" : token.startsWith("`") ? "code" : "em");
    el.textContent = token.startsWith("**") ? token.slice(2, -2) : token.slice(1, -1);
    parent.appendChild(el);
    last = match.index + token.length;
  }
  if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
}

function isTableRow(line) {
  return /^\s*\|.*\|\s*$/.test(line);
}
function cellsFromRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}
function isSeparatorRow(line) {
  return isTableRow(line) && cellsFromRow(line).every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s/g, "")));
}

function renderAssistantContent(container, rawText) {
  const lines = String(rawText ?? "").replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i].trim();
    if (!line) { i++; continue; }

    // Markdown table -> responsive, styled HTML table.
    if (isTableRow(line) && i + 1 < lines.length && isSeparatorRow(lines[i + 1])) {
      const headers = cellsFromRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && isTableRow(lines[i])) {
        rows.push(cellsFromRow(lines[i]));
        i++;
      }
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const headRow = document.createElement("tr");
      headers.forEach((value) => {
        const th = document.createElement("th");
        appendInline(th, value);
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      const tbody = document.createElement("tbody");
      rows.forEach((row) => {
        const tr = document.createElement("tr");
        headers.forEach((_, index) => {
          const td = document.createElement("td");
          appendInline(td, row[index] || "");
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.append(thead, tbody);
      wrap.appendChild(table);
      container.appendChild(wrap);
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const h = document.createElement(`h${heading[1].length}`);
      appendInline(h, heading[2]);
      container.appendChild(h);
      i++;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const list = document.createElement("ul");
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        const li = document.createElement("li");
        appendInline(li, lines[i].trim().replace(/^[-*]\s+/, ""));
        list.appendChild(li);
        i++;
      }
      container.appendChild(list);
      continue;
    }

    if (/^\d+[.)]\s+/.test(line)) {
      const list = document.createElement("ol");
      while (i < lines.length && /^\d+[.)]\s+/.test(lines[i].trim())) {
        const li = document.createElement("li");
        appendInline(li, lines[i].trim().replace(/^\d+[.)]\s+/, ""));
        list.appendChild(li);
        i++;
      }
      container.appendChild(list);
      continue;
    }

    if (line.startsWith(">")) {
      const quote = document.createElement("blockquote");
      appendInline(quote, line.replace(/^>\s?/, ""));
      container.appendChild(quote);
      i++;
      continue;
    }

    const paragraphLines = [line];
    i++;
    while (i < lines.length && lines[i].trim() &&
      !isTableRow(lines[i].trim()) &&
      !/^(#{1,3})\s+/.test(lines[i].trim()) &&
      !/^[-*]\s+/.test(lines[i].trim()) &&
      !/^\d+[.)]\s+/.test(lines[i].trim()) &&
      !lines[i].trim().startsWith(">")) {
      paragraphLines.push(lines[i].trim());
      i++;
    }
    const p = document.createElement("p");
    appendInline(p, paragraphLines.join(" "));
    container.appendChild(p);
  }
}

function addMessage(role, text) {
  const row = document.createElement("div");
  row.className = `message-row ${role === "user" ? "user-row" : "assistant-row"}`;
  const avatar = document.createElement("div");
  avatar.className = `avatar ${role === "user" ? "user-avatar" : "assistant-avatar"}`;
  avatar.textContent = role === "user" ? "Y" : "K";
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  if (role === "assistant") renderAssistantContent(bubble, text);
  else bubble.textContent = text;
  if (role === "user") row.append(bubble, avatar);
  else row.append(avatar, bubble);
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;
  return bubble;
}

async function api(url, opts = {}) {
  const response = await fetch(url, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) }
  });
  const data = await response.json().catch(() => ({ detail: response.statusText }));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

async function playAssistantSpeech(text) {
  try {
    const response = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || `Speech service returned ${response.status}`);
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const audio = new Audio(objectUrl);
    await new Promise((resolve) => {
      const finish = () => {
        URL.revokeObjectURL(objectUrl);
        resolve();
      };
      audio.addEventListener("ended", finish, { once: true });
      audio.addEventListener("error", finish, { once: true });
      audio.play().then(() => {
        $("#voiceStatus").textContent = "Playing assistant response…";
      }).catch(finish);
    });
  } catch (error) {
    // Keep the text answer usable even if TTS is unavailable.
    $("#voiceStatus").textContent = `Voice playback unavailable: ${error.message}`;
  }
}

async function send(text, alreadyBusy = false) {
  const cleanText = String(text || "").trim();
  if (!cleanText || (isBusy && !alreadyBusy)) return;

  if (!alreadyBusy) setBusy(true, "Thinking and checking KIT services…");
  addMessage("user", cleanText);
  messageInput.value = "";

  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message: cleanText })
    });
    const answer = data.answer || "I couldn't find an answer for that request.";
    addMessage("assistant", answer);
    setBusy(true, "Preparing spoken response…");
    await playAssistantSpeech(answer);
  } catch (error) {
    addMessage("assistant", `I couldn't complete that request: ${error.message}`);
  } finally {
    isRecording = false;
    recorder = null;
    setBusy(false);
    if (!$("#voiceStatus").textContent.startsWith("Voice playback unavailable")) {
      $("#voiceStatus").textContent = "";
    }
    messageInput.focus();
  }
}

$("#chatForm").addEventListener("submit", (event) => {
  event.preventDefault();
  send(messageInput.value);
});

quickButtons.forEach((button) => {
  button.addEventListener("click", () => send(button.dataset.q));
});

$("#logout").addEventListener("click", async () => {
  if (isBusy) return;
  try {
    await api("/api/logout", { method: "POST" });
    location.reload();
  } catch (error) {
    addMessage("assistant", `Logout failed: ${error.message}`);
  }
});

(async () => {
  try {
    const me = await api("/api/me");
    $("#identity").textContent = me.authenticated
      ? `Signed in: ${me.user?.full_name || me.login_id} · ${me.role}`
      : "Public visitor mode";
    if (me.authenticated) {
      $("#logout").classList.remove("hidden");
      $("#loginLink").classList.add("hidden");
    }
  } catch {
    // Keep public visitor mode if profile lookup is unavailable.
  }
})();

// MediaRecorder captures audio only. Deepgram performs speech-to-text on the backend.
recordButton.addEventListener("click", async () => {
  if (isBusy) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    $("#voiceStatus").textContent = "Audio recording is not supported by this browser.";
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    chunks = [];
    recorder = new MediaRecorder(stream);
    isRecording = true;
    setBusy(true, "Recording… speak now, then select Stop recording.");
    stopButton.disabled = false;

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) chunks.push(event.data);
    });

    recorder.addEventListener("stop", async () => {
      stream.getTracks().forEach((track) => track.stop());
      isRecording = false;
      setBusy(true, "Transcribing your audio…");
      const audioBlob = new Blob(chunks, { type: recorder?.mimeType || "audio/webm" });
      const formData = new FormData();
      formData.append("audio", audioBlob, "voice.webm");

      try {
        const response = await fetch("/api/transcribe", { method: "POST", body: formData });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `Transcription failed (${response.status})`);
        if (data.transcript?.trim()) {
          await send(data.transcript, true);
        } else {
          $("#voiceStatus").textContent = "No speech detected. Please try again.";
          setBusy(false);
        }
      } catch (error) {
        $("#voiceStatus").textContent = `Transcription error: ${error.message}`;
        setBusy(false);
      }
    }, { once: true });

    recorder.start();
  } catch (error) {
    isRecording = false;
    setBusy(false);
    $("#voiceStatus").textContent = `Microphone unavailable: ${error.message}`;
  }
});

stopButton.addEventListener("click", () => {
  if (recorder && recorder.state !== "inactive") {
    stopButton.disabled = true;
    $("#voiceStatus").textContent = "Finishing recording…";
    recorder.stop();
  }
});

