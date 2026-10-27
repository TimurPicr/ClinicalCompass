import React, { createContext, useContext, useEffect, useState } from "react";
import {
  LoaderCircle,
  ArrowUpRight,
  Check,
  CircleAlert,
  TriangleAlert,
  AlertCircle,
  Info,
} from "lucide-react";
import { api } from "../api/client";
import { date } from "../api/time.js";
export { date, localInput, zonedIso } from "../api/time.js";
export const AppContext = createContext({
  user: null,
  refresh: () => {},
  revision: 0,
  notify: () => {},
});
export const useApp = () => useContext(AppContext);
export function useData(path) {
  const { revision } = useApp();
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  const [counter, setCounter] = useState(0);
  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    api(path)
      .then((value) => {
        if (current) setData(value);
      })
      .catch((e) => {
        if (current) setError(e.message);
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [path, revision, counter]);
  return { data, error, loading, reload: () => setCounter((n) => n + 1) };
}
export function useAction() {
  const { refresh, notify } = useApp();
  const [pending, setPending] = useState(false),
    [error, setError] = useState("");
  async function run(fn, success = "Изменения сохранены") {
    setError("");
    setPending(true);
    try {
      const result = await fn();
      refresh();
      if (success) notify(success);
      return result;
    } catch (e) {
      setError(e.message);
      return undefined;
    } finally {
      setPending(false);
    }
  }
  return { pending, error, run };
}
export function DateText({ value, time = true }) {
  const { user } = useApp();
  return date(value, user?.timezone, time);
}
export function Empty({ children = "Пока нет данных", icon: Icon = Info }) {
  return (
    <div className="empty">
      <Icon size={28} />
      <p>{children}</p>
    </div>
  );
}
export function ErrorBox({ error }) {
  return error ? (
    <div className="error" role="alert">
      <AlertCircle size={17} />
      <span>{error}</span>
    </div>
  ) : null;
}
export function Loading() {
  return (
    <div className="loading">
      <LoaderCircle className="spin" size={23} />
      <span>Загрузка данных…</span>
    </div>
  );
}
export function DataState({ request, children }) {
  if (request.loading && request.data === null) return <Loading />;
  if (request.error && request.data === null)
    return (
      <>
        <ErrorBox error={request.error} />
        <button className="btn secondary" onClick={request.reload}>
          Повторить
        </button>
      </>
    );
  // A failed background refresh must not discard an unsaved form draft.
  return (
    <>
      {request.error && <ErrorBox error={request.error} />}
      {children}
    </>
  );
}
export function Status({ value = "green", label = true }) {
  const names = {
    green: "Стабильно",
    yellow: "Внимание",
    red: "Срочная оценка",
  };
  const icons = { green: Check, yellow: CircleAlert, red: TriangleAlert };
  const Icon = icons[value] || CircleAlert;
  return (
    <span className={`status ${value}`} aria-label={!label ? names[value] : undefined}>
      <Icon size={20} strokeWidth={1.7} aria-hidden="true" />
      {label && names[value]}
    </span>
  );
}
export function Section({ title, sub, action, children, className = "" }) {
  return (
    <section className={`card ${className}`}>
      <div className="section-head">
        <div>
          <h2>{title}</h2>
          {sub && <p>{sub}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function Submit({ pending, children = "Сохранить" }) {
  return (
    <button className="btn" disabled={pending} type="submit">
      {pending ? <LoaderCircle className="spin" size={16} /> : null}
      {pending ? "Сохраняем…" : children}
    </button>
  );
}
export function Field({ label, children, hint }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function Modal({ title, onClose, children }) {
  useEffect(() => {
    const listener = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", listener);
    return () => document.removeEventListener("keydown", listener);
  }, [onClose]);
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="section-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}
export function Timeline({ items, render }) {
  return items?.length ? (
    <div className="timeline">
      {items.map((item, i) => (
        <div className="timeline-item" key={item.id || i}>
          <span className="timeline-dot" />
          {render(item)}
        </div>
      ))}
    </div>
  ) : (
    <Empty>История пока пуста</Empty>
  );
}
export function SourceLink({ url, children }) {
  return url && /^https?:\/\//.test(url) ? (
    <a href={url} target="_blank" rel="noreferrer">
      {children}
      <ArrowUpRight size={13} />
    </a>
  ) : (
    <span>{children}</span>
  );
}
export const initial = (name = "") =>
  name
    .split(" ")
    .slice(0, 2)
    .map((v) => v[0])
    .join("")
    .toUpperCase();
