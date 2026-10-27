import React, { useEffect, useRef, useState } from "react";
import { Send, Paperclip, FileText, X, MessageCircle, ShieldCheck } from "lucide-react";
import { api, csrfToken } from "../api/client";
import { CHAT_TEXT_LIMIT, CHAT_FILE_LIMIT, withChatDeadline, mergeChatMessages, clearSubmittedDraft, shouldSendOnEnter } from "../api/chat.js";
import { useApp, DataState, Section, Empty, DateText, ErrorBox } from "../components/common";
import "./chat.css";

// A room switch must also replace drafts, pending requests and socket handlers.
export default function Chat(props) {
  return <ChatRoom key={props.id} {...props} />;
}

function ChatRoom({ id, onMessage, scrollRequest = 0, title = "Личный чат", subtitle = "Переписка пациента и его лечащего врача" }) {
  const { user } = useApp();
  const [history, setHistory] = useState({ data: null, loading: true, error: "" });
  const [draft, setDraft] = useState({ text: "", file: null });
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("connecting");
  const input = useRef(null);
  const scrollBox = useRef(null);
  const nearBottom = useRef(true);
  const scrollPending = useRef(false);
  const messages = useRef([]);
  const lifecycle = useRef(null);
  const reload = useRef(() => {});
  const ingest = useRef(() => {});
  const sendingNow = useRef(false);
  const uploaded = useRef(null);
  const currentDraft = useRef(draft);
  const notify = useRef(onMessage);
  currentDraft.current = draft;
  notify.current = onMessage;

  useEffect(() => {
    const room = { stopped: false };
    lifecycle.current = room;
    const controller = new AbortController();
    let socket, reconnectTimer, heartbeat;
    let connecting = false, terminal = false, loadingHistory = false, refreshAgain = false;
    let historyLoaded = false, lastHistoryAt = 0, lastSocketAt = 0;
    let mode = "connecting";
    const active = () => !room.stopped && lifecycle.current === room;
    function updateConnection(value) {
      if (!active()) return;
      mode = value;
      setConnection(value);
    }
    function apply(rows, announce = true, own = false) {
      if (!active()) return;
      const previous = new Set(messages.current.map((message) => message.id));
      const merged = mergeChatMessages(messages.current, rows, id);
      const additions = merged.filter((message) => !previous.has(message.id));
      messages.current = merged;
      if (additions.length && (!historyLoaded || own || nearBottom.current)) scrollPending.current = true;
      setHistory({ data: merged, loading: false, error: "" });
      if (announce) additions.forEach((message) => notify.current?.(message));
    }
    ingest.current = apply;
    async function loadHistory() {
      if (!active()) return;
      if (loadingHistory) { refreshAgain = true; return; }
      loadingHistory = true;
      try {
        const rows = await withChatDeadline((signal) => api(`/patients/${id}/chat`, { signal }), controller.signal);
        if (!active()) return;
        apply(rows, historyLoaded);
        historyLoaded = true;
        lastHistoryAt = Date.now();
      } catch (failure) {
        if (active()) setHistory((current) => ({ ...current, loading: false, error: failure.message }));
      } finally {
        loadingHistory = false;
        if (refreshAgain && active()) { refreshAgain = false; void loadHistory(); }
      }
    }
    reload.current = loadHistory;
    function scheduleReconnect() {
      clearTimeout(reconnectTimer);
      if (active() && !terminal) reconnectTimer = setTimeout(connect, 4000);
    }
    async function connect() {
      if (!active() || connecting || terminal || (socket && socket.readyState <= WebSocket.OPEN)) return;
      connecting = true;
      try {
        // Refresh a missing or stale authenticated CSRF cookie before the
        // handshake; origin and authorization checks remain on the server.
        await withChatDeadline((signal) => api("/auth/csrf", { signal }), controller.signal);
        if (!active()) return;
        const token = csrfToken();
        if (!token) throw new Error("Не удалось подготовить соединение");
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const current = new WebSocket(`${protocol}//${location.host}/ws/chat/${id}?csrf=${encodeURIComponent(token)}`);
        socket = current;
        current.onopen = () => {
          if (!active() || socket !== current) return;
          updateConnection("online");
          lastSocketAt = Date.now();
          void loadHistory();
          clearInterval(heartbeat);
          heartbeat = setInterval(() => {
            if (!active() || socket !== current || current.readyState !== WebSocket.OPEN) return;
            if (Date.now() - lastSocketAt > 45000) { updateConnection("polling"); current.close(); return; }
            current.send(JSON.stringify({ type: "ping" }));
          }, 15000);
        };
        current.onmessage = (event) => {
          if (!active() || socket !== current) return;
          lastSocketAt = Date.now();
          try {
            const payload = JSON.parse(event.data);
            if (payload.error) setError(payload.error);
            else if (payload.type !== "pong") {
              if (payload.id) apply([payload]);
              else void loadHistory();
            }
          } catch { void loadHistory(); }
        };
        current.onclose = (event) => {
          if (!active() || socket !== current) return;
          clearInterval(heartbeat);
          updateConnection("polling");
          terminal = [4401, 4403, 4404].includes(event.code);
          void loadHistory();
          scheduleReconnect();
        };
        current.onerror = () => {
          if (active() && socket === current) updateConnection("polling");
        };
      } catch {
        if (active()) { updateConnection("polling"); scheduleReconnect(); }
      } finally { connecting = false; }
    }
    function resume() {
      if (document.visibilityState === "hidden") return;
      void loadHistory();
      if (mode !== "online") { clearTimeout(reconnectTimer); void connect(); }
    }
    void loadHistory();
    void connect();
    const polling = setInterval(() => {
      if (document.visibilityState !== "hidden" && (mode !== "online" || Date.now() - lastHistoryAt >= 30000)) void loadHistory();
    }, 8000);
    window.addEventListener("focus", resume);
    document.addEventListener("visibilitychange", resume);
    return () => {
      room.stopped = true;
      controller.abort();
      clearTimeout(reconnectTimer);
      clearInterval(heartbeat);
      clearInterval(polling);
      window.removeEventListener("focus", resume);
      document.removeEventListener("visibilitychange", resume);
      socket?.close();
      if (lifecycle.current === room) lifecycle.current = null;
    };
  }, [id]);

  useEffect(() => {
    if (!scrollPending.current || !scrollBox.current) return;
    scrollBox.current.scrollTop = scrollBox.current.scrollHeight;
    scrollPending.current = false;
  }, [history.data]);

  useEffect(() => {
    // On mobile the same room can be hidden behind its contact list. Opening
    // it again must reveal the latest messages without discarding the draft.
    nearBottom.current = true;
    const box = scrollBox.current;
    if (box?.clientHeight) box.scrollTop = box.scrollHeight;
  }, [scrollRequest]);

  async function send(event) {
    event.preventDefault();
    if ((!draft.text.trim() && !draft.file) || sendingNow.current) return;
    if (draft.text.trim().length > CHAT_TEXT_LIMIT) { setError(`В сообщении может быть не более ${CHAT_TEXT_LIMIT} символов`); return; }
    const room = lifecycle.current;
    if (!room || room.stopped) return;
    const active = () => !room.stopped && lifecycle.current === room;
    const submitted = { ...draft };
    sendingNow.current = true;
    setSending(true);
    setError("");
    try {
      let attachmentId;
      if (submitted.file) {
        if (uploaded.current?.file === submitted.file) attachmentId = uploaded.current.id;
        else {
          const form = new FormData();
          form.append("file", submitted.file);
          const result = await api(`/patients/${id}/chat/attachments`, { method: "POST", body: form });
          attachmentId = result.id;
          if (active()) uploaded.current = { file: submitted.file, id: attachmentId };
        }
      }
      const message = await api(`/patients/${id}/chat`, {
        method: "POST",
        body: { text: submitted.text.trim(), ...(attachmentId ? { attachment_id: attachmentId } : {}) },
      });
      if (!active()) return;
      ingest.current([message], true, true);
      if (currentDraft.current.file === submitted.file && input.current) input.current.value = "";
      setDraft((current) => clearSubmittedDraft(current, submitted));
      uploaded.current = null;
      void reload.current();
    } catch (failure) {
      if (active()) { setError(failure.message); void reload.current(); }
    } finally {
      sendingNow.current = false;
      if (active()) setSending(false);
    }
  }

  const stateLabel = connection === "online" ? "Подключено" : connection === "connecting" ? "Проверяем соединение…" : "Сообщения обновляются";
  return (
    <Section title={title} sub={subtitle} className="chat-card" action={
      <span className={`connection-state ${connection === "online" ? "online" : ""}`} role="status"><span className="status-dot" />{stateLabel}</span>
    }>
      <div className="chat-disclaimer"><ShieldCheck size={15} /><span>Ответ может быть не сразу. Для экстренной помощи звоните 112.</span></div>
      <div className="chat-messages" ref={scrollBox} role="log" aria-label="История переписки" aria-live="polite" aria-relevant="additions text" onScroll={() => {
        const box = scrollBox.current;
        if (box) nearBottom.current = box.scrollHeight - box.scrollTop - box.clientHeight < 96;
      }}>
        <DataState request={{ ...history, reload: () => reload.current() }}>
          {history.data?.length ? history.data.map((message) => (
            <div key={message.id} className={`chat-message ${message.sender_id === user.id ? "own" : ""}`}>
              <small className="chat-sender">{message.sender_name}</small>
              {message.text && <p>{message.text}</p>}
              {message.attachment && <a className="chat-attachment" href={message.attachment.url || `/api/chat/attachments/${message.attachment.id}`} target="_blank" rel="noreferrer"><FileText size={21} /><span>{message.attachment.name}<small>{Math.ceil(message.attachment.size / 1024)} КБ · Открыть</small></span></a>}
              <time className="chat-time" dateTime={message.created_at}><DateText value={message.created_at} /></time>
            </div>
          )) : <Empty icon={MessageCircle}>Начните разговор — сообщения сохранятся здесь</Empty>}
        </DataState>
      </div>
      <ErrorBox error={error} />
      <form className="chat-compose" onSubmit={send}>
        {draft.file && <div className="attached-file"><Paperclip size={15} /><span>{draft.file.name}</span><button type="button" className="icon-btn" disabled={sending} aria-label="Удалить вложение" onClick={() => {
          setDraft((current) => ({ ...current, file: null }));
          uploaded.current = null;
          if (input.current) input.current.value = "";
        }}><X size={15} /></button></div>}
        <div className="chat-input-row">
          <button type="button" className="icon-btn attach-button" disabled={sending} aria-label="Прикрепить файл" onClick={() => input.current?.click()}><Paperclip size={21} /></button>
          <input type="file" ref={input} hidden accept="application/pdf,image/jpeg,image/png" disabled={sending} onChange={(event) => {
            const selected = event.target.files[0];
            if (selected?.size > CHAT_FILE_LIMIT) { setError("Максимальный размер файла — 15 МБ"); event.target.value = ""; return; }
            setDraft((current) => ({ ...current, file: selected || null }));
            uploaded.current = null;
            setError("");
          }} />
          <textarea value={draft.text} onChange={(event) => setDraft((current) => ({ ...current, text: event.target.value }))} placeholder="Напишите сообщение…" aria-label="Сообщение" rows="2" maxLength={CHAT_TEXT_LIMIT} onKeyDown={(event) => {
            if (shouldSendOnEnter(event)) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); }
          }} />
          <button className="btn send-button" type="submit" disabled={sending || (!draft.text.trim() && !draft.file)} aria-label="Отправить сообщение"><Send size={18} /><span>{sending ? "Отправка…" : "Отправить"}</span></button>
        </div>
        <div className="chat-compose-hint"><span>Enter — отправить · Shift + Enter — новая строка</span><span>{draft.text.length} / {CHAT_TEXT_LIMIT}</span></div>
      </form>
    </Section>
  );
}
