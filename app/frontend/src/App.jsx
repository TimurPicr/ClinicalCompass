import React, { useEffect, useRef, useState } from "react";
import {
  Activity,
  LayoutDashboard,
  BookOpen,
  MessageCircle,
  LogOut,
  Plus,
  Check,
  HeartPulse,
  Menu,
  ShieldCheck,
  ArrowRight,
  Compass,
  Bell,
  X,
} from "lucide-react";
import { api } from "./api/client";
import {
  AppContext,
  ErrorBox,
  Loading,
  Field,
  Submit,
  initial,
} from "./components/common";
import { Dashboard, Invitations } from "./pages/Dashboard";
import Patient from "./pages/Patient";
import Knowledge from "./pages/Knowledge";
import Notifications from "./pages/Notifications";
import Messages from "./pages/Messages";

function Auth({ onLogin }) {
  const params = new URLSearchParams(location.search);
  const token =
    params.get("invite") || params.get("reset") || params.get("token");
  const mode =
    params.has("invite") || location.pathname.includes("register")
      ? "register"
      : params.has("reset") || location.pathname.includes("reset")
        ? "reset"
        : "login";
  const [pending, setPending] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  async function submit(event) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      if (mode === "login") {
        await api("/auth/login", { method: "POST", body: form });
        onLogin(await api("/auth/me"));
      } else if (mode === "register") {
        await api("/auth/register", {
          method: "POST",
          body: {
            ...form,
            token,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          },
        });
        location.href = "/";
      } else {
        await api("/auth/reset", {
          method: "POST",
          body: { token, password: form.password },
        });
        setMessage("Пароль изменён. Можно войти в приложение.");
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="auth-layout">
      <div className="auth-story">
        <div className="brand">
          <span className="brand-mark">
            <Compass size={26} />
          </span>
          <span>
            Clinical<span className="brand-light">Compass</span>
          </span>
        </div>
        <div>
          <span className="eyebrow light">ВНИМАНИЕ К КАЖДОМУ ИЗМЕНЕНИЮ</span>
          <h1>Поддержка рядом.</h1>
          <p>
            Самочувствие, лечение и общение с врачом в одном понятном
            пространстве.
          </p>
          <div className="auth-illustration">
            <div className="illustration-orbit" />
            <HeartPulse size={80} strokeWidth={1.1} />
          </div>
        </div>
        <small>
          Локальное хранение данных
        </small>
      </div>
      <main className="auth-main">
        <form className="auth-form" onSubmit={submit}>
          <span className="eyebrow">ЛИЧНЫЙ КАБИНЕТ</span>
          <h1>
            {mode === "register"
              ? "Добро пожаловать"
              : mode === "reset"
                ? "Новый пароль"
                : "Рады видеть вас"}
          </h1>
          <p>
            {mode === "register"
              ? "Завершите регистрацию по приглашению врача."
              : mode === "reset"
                ? "Задайте новый пароль для своего аккаунта."
                : "Войдите, чтобы продолжить заботиться о здоровье."}
          </p>
          <ErrorBox error={error} />
          {message ? (
            <div className="notice success">
              {message}
              <a href="/">Войти →</a>
            </div>
          ) : (
            <>
              {mode === "register" && (
                <Field label="Ваше имя">
                  <input
                    name="name"
                    autoComplete="name"
                    required
                    placeholder="Фамилия Имя Отчество"
                  />
                </Field>
              )}
              {mode === "login" && (
                <Field label="Электронная почта">
                  <input
                    name="email"
                    type="email"
                    autoComplete="email"
                    required
                    placeholder="you@example.ru"
                  />
                </Field>
              )}
              <Field
                label={
                  mode === "login" ? "Пароль" : "Пароль, не менее 12 символов"
                }
              >
                <input
                  name="password"
                  type="password"
                  minLength={mode === "login" ? 1 : 12}
                  autoComplete={
                    mode === "login" ? "current-password" : "new-password"
                  }
                  required
                  placeholder="Введите пароль"
                />
              </Field>
              <Submit pending={pending}>
                {mode === "login"
                  ? "Войти в кабинет"
                  : mode === "register"
                    ? "Создать аккаунт"
                    : "Сохранить пароль"}
                <ArrowRight size={17} />
              </Submit>
            </>
          )}
          {mode === "login" && (
            <div className="auth-help">
              <ShieldCheck size={18} />
              <p>
                Нет доступа? Обратитесь к разработчику для получения
                персональной ссылки восстановления.
              </p>
            </div>
          )}
        </form>
        <footer>Clinical Compass</footer>
      </main>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState(null),
    [loading, setLoading] = useState(true),
    [revision, setRevision] = useState(0),
    [page, setPage] = useState("dashboard"),
    [patientId, setPatientId] = useState(null),
    [toast, setToast] = useState(""),
    [mobile, setMobile] = useState(false),
    [accountOpen, setAccountOpen] = useState(false),
    [patientTab, setPatientTab] = useState("overview");
  const accountRef = useRef(null);
  const accountTriggerRef = useRef(null);
  const mobileTriggerRef = useRef(null);
  useEffect(() => {
    api("/auth/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
    if ("serviceWorker" in navigator)
      navigator.serviceWorker.register("/sw.js").catch(() => {});
  }, []);
  useEffect(() => {
    if (!user) return;
    // Rules update immediately; queued AI results and reminders can arrive later.
    const timer = setInterval(() => setRevision((value) => value + 1), 30000);
    return () => clearInterval(timer);
  }, [user]);
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(""), 4500);
      return () => clearTimeout(timer);
    }
  }, [toast]);
  useEffect(() => {
    function dismiss(event) {
      if (event.type === "keydown") {
        if (event.key !== "Escape") return;
        if (accountRef.current?.querySelector(".account-menu")?.contains(document.activeElement)) {
          accountTriggerRef.current?.focus();
        } else if (document.activeElement?.closest("#mobile-navigation")) {
          mobileTriggerRef.current?.focus();
        }
        setMobile(false);
        setAccountOpen(false);
      } else if (accountRef.current && !accountRef.current.contains(event.target)) {
        setAccountOpen(false);
      }
    }
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", dismiss);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", dismiss);
    };
  }, []);
  const doctor = user?.role === "doctor";
  function navigate(value) {
    setPage(value);
    setPatientId(null);
    setMobile(false);
    setAccountOpen(false);
    window.scrollTo({ top: 0 });
  }
  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
      setUser(null);
      setPatientId(null);
      setAccountOpen(false);
      setPage("dashboard");
      setPatientTab("overview");
      setMobile(false);
    } catch (e) {
      setToast(e.message);
    }
  }
  if (loading) return <Loading />;
  if (
    !user ||
    new URLSearchParams(location.search).has("invite") ||
    new URLSearchParams(location.search).has("reset") ||
    location.pathname.includes("register") ||
    location.pathname.includes("reset")
  )
    return <Auth onLogin={setUser} />;
  const openPatient = (id, tab = "overview") => {
    setPatientId(id);
    setPatientTab(tab);
    setPage("patient");
    setMobile(false);
    window.scrollTo({ top: 0 });
  };
  const nav = doctor
    ? [
        ["dashboard", LayoutDashboard, "Обзор"],
        ["messages", MessageCircle, "Сообщения"],
        ["knowledge", BookOpen, "База знаний"],
        ["invitations", Plus, "Приглашения"],
      ]
    : [
        ["dashboard", LayoutDashboard, "Моё самочувствие"],
        ["record", HeartPulse, "Медицинская карта"],
        ["prescriptions", Activity, "Назначения"],
        ["questionnaires", BookOpen, "Опросники"],
        ["diary", Activity, "Дневник"],
        ["documents", BookOpen, "Документы"],
        ["chat", MessageCircle, "Сообщения"],
      ];
  const isActive = (id) => page === id || (doctor && id === "dashboard" && ["patient", "patients"].includes(page));
  return (
    <AppContext.Provider
      value={{
        user,
        revision,
        refresh: () => setRevision((n) => n + 1),
        notify: setToast,
      }}
    >
      <div className="app-shell reference-shell">
        <header className={`primary-header ${doctor ? "doctor-header" : "patient-header"}`}>
          <a
            className="brand"
            href="/"
            onClick={(e) => {
              e.preventDefault();
              navigate("dashboard");
            }}
          >
            <span className="brand-mark">
              <Compass size={25} />
            </span>
            <span>
              Clinical<span className="brand-light">Compass</span>
            </span>
          </a>
          <nav className={`primary-nav ${doctor ? "doctor-nav" : "patient-nav"}`} aria-label="Основная навигация">
            {nav.map(([id, , label]) => (
              <button
                key={id}
                className={
                  isActive(id) ? "active" : ""
                }
                onClick={() => navigate(id)}
                aria-current={isActive(id) ? "page" : undefined}
              >
                <span>{label}</span>
              </button>
            ))}
          </nav>
          <div className="header-account" ref={accountRef}>
            <span className="account-label">{doctor ? "Кабинет врача" : "Личный кабинет"}</span>
            <button
              className="account-trigger"
              ref={accountTriggerRef}
              onClick={() => setAccountOpen((open) => !open)}
              aria-label={accountOpen ? "Закрыть профиль" : "Открыть профиль"}
              aria-expanded={accountOpen}
              aria-controls="account-menu"
            >
              <span className="avatar account-avatar">{initial(user.name)}</span>
            </button>
            {accountOpen && (
              <div id="account-menu" className="account-menu" aria-label="Профиль">
                <div className="account-details">
                  <strong>{user.name}</strong>
                  <small>{user.email}</small>
                </div>
                {!doctor && (
                  <button onClick={() => navigate("notifications")}>
                    <Bell size={18} />Настройки уведомлений
                  </button>
                )}
                <button onClick={logout}><LogOut size={18} />Выйти из кабинета</button>
              </div>
            )}
            <button
              className="mobile-menu icon-btn"
              ref={mobileTriggerRef}
              aria-label={mobile ? "Закрыть меню" : "Открыть меню"}
              aria-expanded={mobile}
              aria-controls="mobile-navigation"
              onClick={() => setMobile((open) => !open)}
            >
              {mobile ? <X size={24} /> : <Menu size={24} />}
            </button>
          </div>
        </header>
        {mobile && (
          <nav id="mobile-navigation" className="mobile-navigation" aria-label="Мобильная навигация">
            {nav.map(([id, Icon, label]) => (
              <button key={id} className={isActive(id) ? "active" : ""} onClick={() => navigate(id)} aria-current={isActive(id) ? "page" : undefined}>
                <Icon size={20} />{label}
              </button>
            ))}
          </nav>
        )}
        <div className="main-shell">
          <main className="main-content">
            {doctor ? (
              page === "patient" && patientId ? (
                <Patient id={patientId} initialTab={patientTab} onBack={() => navigate("dashboard")} />
              ) : page === "messages" ? (
                <Messages />
              ) : page === "knowledge" ? (
                <Knowledge />
              ) : page === "invitations" ? (
                <Invitations />
              ) : (
                <Dashboard
                  openPatient={openPatient}
                  compact={page === "patients"}
                />
              )
            ) : page === "notifications" ? (
              <Notifications />
            ) : (
              <Patient
                id={user.patient_id}
                initialTab={page === "dashboard" ? "overview" : page}
                self
              />
            )}
          </main>
          <footer className="app-footer">
            <span><ShieldCheck size={22} />Данные на вашем сервере</span>
            <span>
              Clinical Compass · {doctor ? "Кабинет врача" : "Личный кабинет"}
            </span>
          </footer>
        </div>
        {toast && (
          <div className="toast" role="status">
            <Check size={18} />
            {toast}
            <button onClick={() => setToast("")} aria-label="Закрыть">
              ×
            </button>
          </div>
        )}
      </div>
    </AppContext.Provider>
  );
}
