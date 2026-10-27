import React, { useMemo, useState } from "react";
import {
  AlertCircle,
  CalendarDays,
  Check,
  ChevronRight,
  Copy,
  Mail,
  Plus,
  Search,
  TriangleAlert,
  UserRound,
} from "lucide-react";
import { api } from "../api/client";
import {
  useApp,
  useData,
  useAction,
  DataState,
  ErrorBox,
  Field,
  Submit,
  Section,
  Empty,
  DateText,
  initial,
} from "../components/common";
import "./dashboard.css";

const statusOrder = { red: 0, yellow: 1, green: 2 };

function calendarDay(value, timezone) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const fields = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return Date.UTC(Number(fields.year), Number(fields.month) - 1, Number(fields.day));
}

function lastActivity(value, timezone) {
  if (!value) return "Нет данных";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Нет данных";
  const days = (calendarDay(new Date(), timezone) - calendarDay(parsed, timezone)) / 86400000;
  const day = days === 0 ? "Сегодня" : days === 1 ? "Вчера" : new Intl.DateTimeFormat("ru-RU", {
    timeZone: timezone,
    day: "numeric",
    month: "long",
  }).format(parsed);
  const time = new Intl.DateTimeFormat("ru-RU", {
    timeZone: timezone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(parsed);
  return `${day}, ${time}`;
}

function monitoringDate(value, timezone) {
  if (!value) return "Дата начала не указана";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Дата начала не указана";
  return "С " + new Intl.DateTimeFormat("ru-RU", {
    timeZone: /^\d{4}-\d{2}-\d{2}$/.test(value) ? "UTC" : timezone,
    day: "numeric",
    month: "long",
  }).format(parsed);
}

function RosterStatus({ value }) {
  const status = {
    red: { label: "Срочная оценка", Icon: TriangleAlert },
    yellow: { label: "Внимание", Icon: AlertCircle },
    green: { label: "Стабильно", Icon: Check },
  }[value] || { label: "Статус не определён", Icon: AlertCircle };
  return (
    <span className={`roster-status ${value || "unknown"}`}>
      <status.Icon size={21} strokeWidth={1.7} aria-hidden="true" />
      {status.label}
    </span>
  );
}

export function Dashboard({ openPatient }) {
  const { user } = useApp();
  const request = useData("/patients");
  const alerts = useData("/alerts");
  const [search, setSearch] = useState("");
  const timezone = user.timezone || "Europe/Moscow";
  const data = request.data || [];
  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("ru-RU");
    return data.filter((patient) =>
      [patient.name, patient.diagnosis, patient.diagnosis_code].filter(Boolean).join(" ").toLocaleLowerCase("ru-RU").includes(query),
    ).sort((a, b) =>
      (statusOrder[a.status] ?? 3) - (statusOrder[b.status] ?? 3) || a.name.localeCompare(b.name, "ru"),
    );
  }, [data, search]);
  const reasons = useMemo(() => {
    const grouped = new Map();
    [...(alerts.data || [])]
      .filter((alert) => !["dismissed", "resolved"].includes(alert.state))
      .sort((a, b) =>
        (statusOrder[a.level] ?? 3) - (statusOrder[b.level] ?? 3)
        || Number(b.source?.startsWith("rule:")) - Number(a.source?.startsWith("rule:"))
        || new Date(b.created_at) - new Date(a.created_at),
      )
      .forEach((alert) => {
        if (!grouped.has(alert.patient_id)) grouped.set(alert.patient_id, alert.reason);
      });
    return grouped;
  }, [alerts.data]);
  const words = user.name.trim().split(/\s+/);
  const greeting = words.length >= 3 ? words.slice(0, 2).join(" ") : words[0];
  const today = new Intl.DateTimeFormat("ru-RU", {
    timeZone: timezone,
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date());

  function reasonFor(patient) {
    if (reasons.has(patient.id)) return reasons.get(patient.id);
    if (alerts.error) return "Основание статуса временно недоступно";
    if (alerts.loading && alerts.data === null) return "Загружаем сведения мониторинга…";
    return "Нет активных предупреждений по доступным данным";
  }

  return (
    <div className="doctor-overview">
      <div className="doctor-greeting">
        <p className="doctor-date"><CalendarDays size={24} strokeWidth={1.6} aria-hidden="true" />{today}</p>
        <h1>Здравствуйте,<span>{greeting}</span></h1>
      </div>
      <section className="patient-roster" aria-labelledby="patient-roster-title">
        <div className="roster-heading">
          <h2 id="patient-roster-title">Ваши пациенты</h2>
          <span className="roster-count" aria-label={`Всего пациентов: ${data.length}`}>{data.length}</span>
        </div>
        <label className="roster-search">
          <Search size={23} strokeWidth={1.7} aria-hidden="true" />
          <input
            type="search"
            placeholder="Имя пациента или код диагноза"
            aria-label="Поиск пациентов по имени или коду диагноза"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <ErrorBox error={alerts.error} />
        <DataState request={request}>
          <div className="roster-table-wrap">
            <table className="roster-table">
              <colgroup><col className="roster-patient-column" /><col className="roster-status-column" /><col /><col className="roster-open-column" /></colgroup>
              <thead><tr><th scope="col">Пациент</th><th scope="col">Статус и основание</th><th scope="col">Последние данные</th><th scope="col"><span className="roster-sr-only">Открыть карту</span></th></tr></thead>
              <tbody>
                {filtered.map((patient) => (
                  <tr key={patient.id} onClick={() => openPatient(patient.id)}>
                    <td>
                      <div className="roster-patient">
                        <span className="roster-avatar" aria-hidden="true">{initial(patient.name)}</span>
                        <div>
                          <button className="roster-name" onClick={(event) => { event.stopPropagation(); openPatient(patient.id); }}>{patient.name}</button>
                          <p className="roster-patient-meta">{patient.diagnosis_code && <>{patient.diagnosis_code}<span> · </span></>}{monitoringDate(patient.monitoring_started_at, timezone)}</p>
                        </div>
                      </div>
                    </td>
                    <td data-label="Статус и основание">
                      <RosterStatus value={patient.status} />
                      <p className="roster-reason" title={reasonFor(patient)}>{reasonFor(patient)}</p>
                    </td>
                    <td data-label="Последние данные">
                      <div className="roster-activity">
                        <time dateTime={patient.last_activity || undefined}>{lastActivity(patient.last_activity, timezone)}</time>
                      </div>
                    </td>
                    <td>
                      <button className="roster-open" aria-label={`Открыть карту: ${patient.name}`} onClick={(event) => { event.stopPropagation(); openPatient(patient.id); }}><ChevronRight size={23} strokeWidth={1.7} /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!filtered.length && <Empty icon={UserRound}>{search.trim() ? "Пациентов по вашему запросу не найдено" : "Здесь появятся ваши пациенты"}</Empty>}
          </div>
        </DataState>
        <div className="roster-footer">
          <span aria-live="polite">Показано {filtered.length} из {data.length}</span>
          <span>Статус не является диагнозом</span>
        </div>
      </section>
    </div>
  );
}

export function Invitations() {
  const request = useData("/auth/invitations"),
    action = useAction();
  const [link, setLink] = useState("");
  async function submit(e) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const result = await action.run(
      () =>
        api("/auth/invitations", {
          method: "POST",
          body: {
            email: form.get("email"),
            expires_hours: Number(form.get("expires_hours")),
          },
        }),
      "Приглашение создано",
    );
    if (result) setLink(result.link || result.url);
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">НАЧАЛО НАБЛЮДЕНИЯ</span>
          <h1>Приглашения пациентам</h1>
          <p>
            Личная одноразовая ссылка автоматически прикрепляет пациента к вам.
          </p>
        </div>
      </div>
      <div className="two-col">
        <Section
          title="Создать приглашение"
          sub="Передайте ссылку пациенту безопасным способом"
        >
          <form className="form-stack" onSubmit={submit}>
            <Field label="Email пациента">
              <input
                type="email"
                name="email"
                required
                placeholder="patient@example.ru"
              />
            </Field>
            <Field label="Срок действия">
              <select name="expires_hours" defaultValue="48">
                <option value="24">24 часа</option>
                <option value="48">48 часов</option>
                <option value="168">7 дней</option>
              </select>
            </Field>
            <ErrorBox error={action.error} />
            <Submit pending={action.pending}>
              <Plus size={16} />
              Создать ссылку
            </Submit>
          </form>
          {link && (
            <div className="link-result">
              <strong>Приглашение готово</strong>
              <a href={link}>{link}</a>
              <button
                className="btn secondary"
                onClick={() =>
                  navigator.clipboard.writeText(link).catch(() => {})
                }
              >
                <Copy size={15} />
                Копировать ссылку
              </button>
            </div>
          )}
        </Section>
        <Section title="История приглашений">
          <DataState request={request}>
            {request.data?.length ? (
              <div className="list">
                {request.data.map((item) => (
                  <div className="list-item" key={item.id}>
                    <span className="small-icon">
                      <Mail size={18} />
                    </span>
                    <div className="grow">
                      <strong>{item.email}</strong>
                      <small>
                        Действует до <DateText value={item.expires_at} />
                      </small>
                    </div>
                    <span className="tag">
                      {item.used_at
                        ? "Использовано"
                        : new Date(item.expires_at) < new Date()
                          ? "Истекло"
                          : "Ожидает"}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <Empty>Приглашений пока нет</Empty>
            )}
          </DataState>
        </Section>
      </div>
    </>
  );
}
