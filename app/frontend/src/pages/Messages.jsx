import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ChevronRight, MessageCircle, Paperclip, RefreshCw, Search } from "lucide-react";
import { api } from "../api/client";
import { Empty, ErrorBox, Loading, initial, useApp } from "../components/common";
import Chat from "./Chat";
import "./messages.css";

const POLL_INTERVAL = 8000;

function useChatInbox(revision) {
  const [request, setRequest] = useState({ data: null, error: "", loading: true });
  const mounted = useRef(false);
  const sequence = useRef(0);
  const controller = useRef(null);
  const queued = useRef(false);
  const refreshRef = useRef(null);
  const previousRevision = useRef(revision);

  const refresh = useCallback(() => {
    if (!mounted.current || document.visibilityState === "hidden") return;
    // A message arriving during an existing request must cause one more fetch,
    // but interval/focus/message events never create competing requests.
    if (controller.current) {
      queued.current = true;
      return;
    }
    const current = new AbortController();
    const token = ++sequence.current;
    controller.current = current;
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      current.abort();
    }, 15000);
    setRequest((value) => ({ ...value, loading: true, error: "" }));
    api("/chats", { signal: current.signal })
      .then((data) => {
        if (mounted.current && sequence.current === token && !current.signal.aborted)
          setRequest({ data, error: "", loading: false });
      })
      .catch((error) => {
        if (mounted.current && sequence.current === token && (timedOut || !current.signal.aborted))
          setRequest((value) => ({ ...value, error: timedOut ? "Сервер долго отвечает. Попробуйте обновить диалоги." : error.message, loading: false }));
      })
      .finally(() => {
        clearTimeout(timeout);
        if (controller.current !== current) return;
        controller.current = null;
        const shouldRefresh = queued.current;
        queued.current = false;
        if (mounted.current && shouldRefresh && document.visibilityState !== "hidden")
          refreshRef.current?.();
      });
  }, []);
  refreshRef.current = refresh;

  useEffect(() => {
    mounted.current = true;
    refresh();
    const timer = setInterval(refresh, POLL_INTERVAL);
    const onVisible = () => {
      if (document.visibilityState !== "hidden") refresh();
    };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      mounted.current = false;
      sequence.current += 1;
      queued.current = false;
      clearInterval(timer);
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
      controller.current?.abort();
      controller.current = null;
    };
  }, [refresh]);

  useEffect(() => {
    if (previousRevision.current !== revision) {
      previousRevision.current = revision;
      refresh();
    }
  }, [revision, refresh]);

  return { ...request, refresh };
}

function roomTime(value, timezone) {
  if (!value) return "";
  const messageDate = new Date(value);
  if (Number.isNaN(messageDate.getTime())) return "";
  const dayFormatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit",
  });
  const now = new Date();
  if (dayFormatter.format(messageDate) === dayFormatter.format(now))
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: timezone, hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).format(messageDate);
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: timezone, day: "numeric", month: "short",
    ...(new Intl.DateTimeFormat("en", { timeZone: timezone, year: "numeric" }).format(messageDate) !== new Intl.DateTimeFormat("en", { timeZone: timezone, year: "numeric" }).format(now) ? { year: "numeric" } : {}),
  }).format(messageDate);
}

function roomPreview(room, userId) {
  const message = room.last_message;
  if (!message) return "Начните переписку";
  const content = message.text || message.attachment?.name || "Вложение";
  return `${message.sender_id === userId ? "Вы: " : ""}${content}`;
}

export default function Messages() {
  const { user, revision } = useApp();
  const inbox = useChatInbox(revision);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [threadOpen, setThreadOpen] = useState(false);
  const [scrollRequest, setScrollRequest] = useState(0);
  const rooms = inbox.data || [];
  const timezone = user.timezone || "Europe/Moscow";

  useEffect(() => {
    if (inbox.data === null) return;
    if (inbox.data.some((room) => room.patient_id === selectedId)) return;
    setSelectedId(inbox.data[0]?.patient_id ?? null);
    setThreadOpen(false);
  }, [inbox.data, selectedId]);

  const visibleRooms = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("ru-RU");
    return rooms.filter((room) => room.patient_name.toLocaleLowerCase("ru-RU").includes(query));
  }, [rooms, search]);
  const selected = rooms.find((room) => room.patient_id === selectedId);
  const onMessage = useCallback(() => inbox.refresh(), [inbox.refresh]);

  function openRoom(room) {
    setSelectedId(room.patient_id);
    setThreadOpen(true);
    setScrollRequest((value) => value + 1);
  }

  return (
    <div className="messages-page">
      <div className="page-heading messages-page-heading">
        <div>
          <span className="eyebrow">ЛИЧНАЯ ПЕРЕПИСКА</span>
          <h1>Сообщения</h1>
          <p>Диалоги с вашими пациентами в одном месте.</p>
        </div>
      </div>
      <section className={`messages-inbox ${threadOpen ? "messages-thread-open" : ""}`} aria-label="Переписка с пациентами">
        <aside className="messages-sidebar" aria-label="Список диалогов">
          <div className="messages-list-header">
            <div className="messages-list-title">
              <h2>Ваши диалоги</h2>
              <button type="button" className="messages-refresh" onClick={inbox.refresh} aria-label="Обновить список диалогов" title="Обновить список диалогов">
                <RefreshCw size={18} strokeWidth={1.7} aria-hidden="true" />
              </button>
            </div>
            <label className="messages-search">
              <Search size={20} strokeWidth={1.7} aria-hidden="true" />
              <input type="search" placeholder="Поиск пациента" aria-label="Поиск диалога по имени пациента" value={search} onChange={(event) => setSearch(event.target.value)} />
            </label>
          </div>
          {inbox.error && <div className="messages-list-error"><ErrorBox error={inbox.error} /><button type="button" className="text-btn" onClick={inbox.refresh}>Повторить</button></div>}
          {inbox.loading && inbox.data === null ? <Loading /> : (
            <>
              {visibleRooms.length ? (
                <nav className="messages-list" aria-label="Диалоги с пациентами">
                  <ul>
                    {visibleRooms.map((room) => (
                      <li key={room.patient_id}>
                        <button type="button" className={`messages-room ${selectedId === room.patient_id ? "messages-room-selected" : ""}`} aria-current={selectedId === room.patient_id ? "true" : undefined} onClick={() => openRoom(room)}>
                          <span className="messages-avatar" aria-hidden="true">{initial(room.patient_name)}</span>
                          <span className="messages-room-content">
                            <span className="messages-room-top"><strong>{room.patient_name}</strong><time dateTime={room.last_message?.created_at}>{roomTime(room.last_message?.created_at, timezone)}</time></span>
                            <span className="messages-preview">{room.last_message?.attachment && <Paperclip size={14} aria-hidden="true" />}<span className="messages-preview-text">{roomPreview(room, user.id)}</span></span>
                          </span>
                          <ChevronRight className="messages-room-arrow" size={16} aria-hidden="true" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </nav>
              ) : !inbox.error && (
                <div className="messages-list-empty"><Empty icon={MessageCircle}>{search.trim() ? "Диалогов по вашему запросу не найдено" : "Пока нет пациентов для переписки"}</Empty></div>
              )}
              {inbox.data !== null && <p className="messages-list-caption" aria-live="polite">{search.trim() ? `Найдено диалогов: ${visibleRooms.length}` : `Всего диалогов: ${rooms.length}`}</p>}
            </>
          )}
        </aside>
        <div className="messages-thread">
          {selected ? (
            <>
              <div className="messages-mobile-back"><button type="button" onClick={() => setThreadOpen(false)}><ArrowLeft size={19} />Все диалоги</button></div>
              <Chat key={selected.patient_id} id={selected.patient_id} title={selected.patient_name} subtitle="Личная переписка с пациентом" onMessage={onMessage} scrollRequest={scrollRequest} />
            </>
          ) : (
            <div className="messages-thread-empty"><MessageCircle size={42} strokeWidth={1.2} /><h2>Ваши разговоры — здесь</h2><p>Выберите пациента, чтобы открыть переписку.</p></div>
          )}
        </div>
      </section>
    </div>
  );
}
