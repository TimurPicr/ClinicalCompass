import React, { useEffect, useState } from "react";
import {
  ArrowLeft,
  ClipboardList,
  Activity,
  Pill,
  BookOpen,
  FileText,
  MessageCircle,
  Sparkles,
  ChevronRight,
  CalendarDays,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { api } from "../api/client";
import {
  useApp,
  useData,
  useAction,
  DataState,
  Section,
  Status,
  Empty,
  DateText,
  Field,
  Submit,
  ErrorBox,
  initial,
  date,
  Timeline,
} from "../components/common";
import { Prescriptions } from "./Prescriptions";
import Questionnaires from "./Questionnaires";
import { Documents, AiSummary, Alerts } from "./Reports";
import Chat from "./Chat";

export default function Patient({
  id,
  self = false,
  onBack,
  initialTab = "overview",
}) {
  const { user } = useApp();
  const request = useData(`/patients/${id}`);
  const [tab, setTab] = useState(initialTab);
  useEffect(() => setTab(initialTab), [initialTab, id]);
  const patient = request.data;
  const tabs = [
    ["overview", "Обзор"],
    ["record", "Медицинская карта"],
    ["prescriptions", "Назначения"],
    ["questionnaires", "Опросники"],
    ["diary", "Дневник"],
    ["ai", "AI-сводка"],
    ...(!self ? [["alerts", "Предупреждения"]] : []),
    ["documents", "Документы"],
    ["chat", "Чат"],
  ];
  return (
    <DataState request={request}>
      {patient && (
        <>
          {!self && (
            <button className="back-btn" onClick={onBack}>
              <ArrowLeft size={15} />
              Все пациенты
            </button>
          )}
          <div className="patient-heading">
            <span className="avatar large">{initial(patient.name)}</span>
            <div className="grow">
              <span className="eyebrow">
                {self ? "МОЁ САМОЧУВСТВИЕ" : "КАРТОЧКА ПАЦИЕНТА"}
              </span>
              <h1>
                {self
                  ? `Здравствуйте, ${user.name.trim().split(/\s+/)[0]}`
                  : patient.name}
              </h1>
              <div className="patient-metadata">
                <p className="patient-diagnosis">
                  {patient.diagnosis_code && `${patient.diagnosis_code} · `}
                  {patient.diagnosis || "Диагноз пока не указан"}
                </p>
                <p className="patient-monitoring">
                  <CalendarDays size={18} aria-hidden="true" />
                  <span>
                    Наблюдение с{" "}
                    <DateText value={patient.monitoring_started_at} time={false} />
                  </span>
                </p>
              </div>
            </div>
            <Status value={patient.status} />
          </div>
          {patient.status === "red" && (
            <div className="notice danger">
              <strong>Необходима срочная оценка состояния специалистом.</strong>{" "}
              При непосредственной угрозе жизни или безопасности обратитесь за
              экстренной помощью по номеру 112. Приложение не обеспечивает
              круглосуточное наблюдение.
            </div>
          )}
          {!self && (
            <nav className="workspace-tabs" aria-label="Разделы карты пациента">
              {tabs.map(([key, title]) => (
                <button
                  key={key}
                  className={tab === key ? "active" : ""}
                  aria-current={tab === key ? "page" : undefined}
                  onClick={() => setTab(key)}
                >
                  {title}
                </button>
              ))}
            </nav>
          )}
          {tab === "overview" ? (
            <Overview id={id} self={self} setTab={setTab} />
          ) : tab === "record" ? (
            <MedicalRecord id={id} />
          ) : tab === "prescriptions" ? (
            <Prescriptions id={id} />
          ) : tab === "questionnaires" ? (
            <Questionnaires id={id} />
          ) : tab === "diary" ? (
            <Diary id={id} patient={patient} />
          ) : tab === "ai" ? (
            <AiSummary id={id} />
          ) : tab === "alerts" ? (
            <Alerts id={id} />
          ) : tab === "documents" ? (
            <Documents id={id} />
          ) : (
            <Chat id={id} />
          )}
        </>
      )}
    </DataState>
  );
}
function Overview({ id, self, setTab }) {
  const diary = useData(`/patients/${id}/diary`),
    prescriptions = useData(`/patients/${id}/prescriptions`),
    assignments = useData(`/patients/${id}/assignments`),
    ai = useData(`/patients/${id}/ai`);
  const active = (prescriptions.data || []).filter((p) => p.active);
  const todo = (assignments.data || []).filter((a) => a.active);
  const last = diary.data?.at(-1);
  return (
    <>
      <div className="overview-grid">
        <Section
          title={self ? "Сегодня для вас" : "План наблюдения"}
          sub="Регулярные небольшие шаги помогают видеть динамику"
        >
          <div className="task-list">
            <button
              onClick={() => setTab("prescriptions")}
              className="task-row"
            >
              <span className="task-icon mint">
                <Pill size={20} />
              </span>
              <div className="grow">
                <strong>Приём препаратов</strong>
                <small>{active.length} действующих назначений</small>
              </div>
              <ChevronRight size={18} />
            </button>
            <button
              onClick={() => setTab("questionnaires")}
              className="task-row"
            >
              <span className="task-icon lavender">
                <ClipboardList size={20} />
              </span>
              <div className="grow">
                <strong>Опросники</strong>
                <small>{todo.length} назначено для заполнения</small>
              </div>
              <ChevronRight size={18} />
            </button>
            <button onClick={() => setTab("diary")} className="task-row">
              <span className="task-icon peach">
                <BookOpen size={20} />
              </span>
              <div className="grow">
                <strong>Дневник самочувствия</strong>
                <small>
                  {last ? (
                    <>
                      Последняя запись <DateText value={last.created_at} />
                    </>
                  ) : (
                    "Расскажите, как вы себя чувствуете"
                  )}
                </small>
              </div>
              <ChevronRight size={18} />
            </button>
          </div>
        </Section>
        <Section
          title="Краткая AI-сводка"
          sub="Дополняет наблюдение лечащего врача"
          className="ai-card"
          action={<Sparkles size={21} />}
        >
          <DataState request={ai}>
            {ai.data?.analysis ? (
              <>
                <p className="summary-text">
                  {self
                    ? ai.data.analysis.result.patient_summary
                    : ai.data.analysis.result.summary}
                </p>
                <small className="muted">
                  Обновлено <DateText value={ai.data.analysis.created_at} />
                </small>
                <button className="text-btn" onClick={() => setTab("ai")}>
                  Сводка и обоснование
                  <ChevronRight size={16} />
                </button>
              </>
            ) : (
              <Empty>
                Сводка появится после обработки новых данных локальной моделью.
              </Empty>
            )}
          </DataState>
        </Section>
      </div>
      <Section
        title="Динамика самочувствия"
        sub="Шкала 0–10. Для настроения и сна выше — лучше; для тревоги выше — хуже."
        action={
          <button className="text-btn" onClick={() => setTab("diary")}>
            Все записи
            <ChevronRight size={15} />
          </button>
        }
      >
        <DataState request={diary}>
          <DiaryChart entries={diary.data || []} />
        </DataState>
      </Section>
      <div className="dashboard-bottom">
        <div className="info-card">
          <MessageCircle size={23} />
          <div>
            <strong>На связи с врачом</strong>
            <p>
              Задавайте вопросы о наблюдении в личном чате. Для неотложной
              помощи используйте 112.
            </p>
            <button className="text-btn" onClick={() => setTab("chat")}>
              Открыть чат
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
        <div className="info-card">
          <FileText size={23} />
          <div>
            <strong>Вся история в одном месте</strong>
            <p>
              Добавляйте документы и сведения. Врач проверит их и подтвердит
              медицинскую информацию.
            </p>
            <button className="text-btn" onClick={() => setTab("record")}>
              Медицинская карта
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
const recordFields = {
  diagnosis_code: "Код диагноза · МКБ-10",
  diagnosis: "Основной диагноз",
  comorbidities: "Сопутствующие заболевания",
  anamnesis: "Анамнез",
  allergies: "Аллергии",
  treatment_history: "История лечения",
  examinations: "Результаты обследований",
  notes: "Примечания",
};
function MedicalRecord({ id }) {
  const { user } = useApp(),
    request = useData(`/patients/${id}/record`),
    action = useAction(),
    patient = useData(`/patients/${id}`);
  const doctor = user.role === "doctor";
  const [edit, setEdit] = useState(false),
    [view, setView] = useState(doctor ? "confirmed" : "reported");
  async function save(e) {
    e.preventDefault();
    const form = Object.fromEntries(new FormData(e.currentTarget));
    const birth_date = form.birth_date;
    delete form.birth_date;
    const result = await action.run(() =>
      api(`/patients/${id}/record`, {
        method: "PUT",
        body: { data: form, ...(birth_date ? { birth_date } : {}) },
      }),
    );
    if (result) setEdit(false);
  }
  return (
    <>
      <Section
        title="Медицинская карта"
        sub="Сведения со слов пациента отделены от данных, проверенных врачом"
        action={
          <button
            className="btn secondary"
            onClick={() => {
              setEdit(!edit);
              setView(doctor ? "confirmed" : "reported");
            }}
          >
            {edit ? "Отменить" : "Редактировать"}
          </button>
        }
      >
        <div className="segmented">
          <button
            className={view === "confirmed" ? "active" : ""}
            onClick={() => {
              setView("confirmed");
              setEdit(false);
            }}
          >
            Подтверждено врачом
          </button>
          <button
            className={view === "reported" ? "active" : ""}
            onClick={() => {
              setView("reported");
              setEdit(false);
            }}
          >
            Со слов пациента
          </button>
        </div>
        <DataState request={request}>
          {edit ? (
            <form className="form-stack" onSubmit={save}>
              <div className="form-grid">
                <Field label="Дата рождения">
                  <input
                    type="date"
                    name="birth_date"
                    defaultValue={
                      (view === "reported"
                        ? request.data?.reported?.birth_date
                        : patient.data?.birth_date) || ""
                    }
                  />
                </Field>
                {Object.entries(recordFields)
                  .filter(
                    ([key]) =>
                      doctor || !["diagnosis", "diagnosis_code"].includes(key),
                  )
                  .map(([key, label]) => (
                    <Field key={key} label={label}>
                      {["diagnosis", "diagnosis_code"].includes(key) ? (
                        <input
                          name={key}
                          required={key === "diagnosis_code"}
                          defaultValue={request.data?.[view]?.[key] || ""}
                          placeholder={
                            key === "diagnosis_code"
                              ? "Например, F32.0"
                              : "Наименование диагноза"
                          }
                        />
                      ) : (
                        <textarea
                          name={key}
                          rows="3"
                          defaultValue={
                            typeof request.data?.[view]?.[key] === "object"
                              ? JSON.stringify(request.data[view][key])
                              : request.data?.[view]?.[key] || ""
                          }
                        />
                      )}
                    </Field>
                  ))}
              </div>
              <ErrorBox error={action.error} />
              <Submit pending={action.pending} />
            </form>
          ) : (
            <div className="record-grid">
              <div>
                <span className="record-label">Дата рождения</span>
                <p>
                  {(
                    view === "reported"
                      ? request.data?.reported?.birth_date
                      : patient.data?.birth_date
                  ) ? (
                    <DateText
                      value={
                        view === "reported"
                          ? request.data?.reported?.birth_date
                          : patient.data.birth_date
                      }
                      time={false}
                    />
                  ) : (
                    "Не указана"
                  )}
                </p>
              </div>
              {Object.entries(recordFields).map(([key, label]) => (
                <div key={key}>
                  <span className="record-label">{label}</span>
                  <p>
                    {typeof request.data?.[view]?.[key] === "object"
                      ? JSON.stringify(request.data[view][key])
                      : request.data?.[view]?.[key] || (
                          <span className="muted">Пока не заполнено</span>
                        )}
                  </p>
                </div>
              ))}
            </div>
          )}
        </DataState>
      </Section>
      <Section
        title="История изменений"
        sub="Каждое изменение сохраняется вместе с автором и предыдущими значениями"
      >
        <Timeline
          items={request.data?.history}
          render={(item) => (
            <>
              <strong>Автор #{item.actor_id}</strong>
              <small>
                <DateText value={item.created_at} />
              </small>
              <details>
                <summary>Изменённые сведения</summary>
                <div className="history-diff">
                  <div>
                    <strong>До</strong>
                    <pre>{JSON.stringify(item.before, null, 2)}</pre>
                  </div>
                  <div>
                    <strong>После</strong>
                    <pre>{JSON.stringify(item.after, null, 2)}</pre>
                  </div>
                </div>
              </details>
            </>
          )}
        />
      </Section>
    </>
  );
}
export function DiaryChart({ entries }) {
  const { user } = useApp();
  const data = [...entries]
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
    .slice(-30)
    .map((item) => ({
      ...item,
      label: date(item.created_at, user.timezone, false),
    }));
  return data.length ? (
    <div className="chart-container">
      <ResponsiveContainer width="100%" height={265}>
        <LineChart
          data={data}
          margin={{ top: 15, right: 15, left: -22, bottom: 0 }}
        >
          <CartesianGrid
            strokeDasharray="3 4"
            vertical={false}
            stroke="#dfe5f2"
          />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 13, fill: "#7c87a0" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={[0, 10]}
            tick={{ fontSize: 13, fill: "#7c87a0" }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{
              border: "1px solid #dfe5f2",
              borderRadius: 16,
              color: "#2b3146",
              fontSize: 13,
              padding: 12,
            }}
          />
          <Legend
            iconType="circle"
            wrapperStyle={{ fontSize: 13, color: "#7c87a0", paddingTop: 12 }}
          />
          <Line
            name="Настроение"
            type="monotone"
            dataKey="mood"
            stroke="#315fd1"
            strokeWidth={2.5}
            dot={{ r: 3 }}
          />
          <Line
            name="Тревожность"
            type="monotone"
            dataKey="anxiety"
            stroke="#b88b38"
            strokeWidth={2.5}
            dot={{ r: 3 }}
          />
          <Line
            name="Качество сна"
            type="monotone"
            dataKey="sleep"
            stroke="#9096c8"
            strokeWidth={2.5}
            dot={{ r: 3 }}
          />
          <Line
            name="Уровень энергии"
            type="monotone"
            dataKey="energy"
            stroke="#83a6df"
            strokeWidth={2}
            dot={{ r: 2 }}
          />
          <Line
            name="Общее самочувствие"
            type="monotone"
            dataKey="wellbeing"
            stroke="#7886a5"
            strokeWidth={2}
            dot={{ r: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  ) : (
    <Empty icon={Activity}>
      Записи дневника появятся на графике после заполнения
    </Empty>
  );
}
const metrics = {
  mood: "Настроение",
  anxiety: "Тревожность",
  sleep: "Качество сна",
  energy: "Уровень энергии",
  wellbeing: "Общее самочувствие",
};
function Diary({ id, patient }) {
  const { user } = useApp(),
    request = useData(`/patients/${id}/diary`),
    action = useAction();
  const doctor = user.role === "doctor";
  const [values, setValues] = useState({
    mood: 5,
    anxiety: 5,
    sleep: 5,
    energy: 5,
    wellbeing: 5,
  });
  async function submit(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const result = await action.run(
      () =>
        api(`/patients/${id}/diary`, {
          method: "POST",
          body: { ...values, comment: new FormData(form).get("comment") },
        }),
      "Запись дневника сохранена",
    );
    if (result) form.reset();
  }
  async function schedule(e) {
    e.preventDefault();
    const times = String(new FormData(e.currentTarget).get("times"))
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
    await action.run(() =>
      api(`/patients/${id}/diary-schedule`, { method: "PUT", body: { times } }),
    );
  }
  return (
    <>
      {!doctor ? (
        <Section
          title="Как вы себя чувствуете?"
          sub="Выберите значение от 0 до 10 для каждого показателя"
        >
          <form onSubmit={submit} className="form-stack">
            <div className="form-grid">
              {Object.entries(metrics).map(([key, label]) => (
                <Field
                  key={key}
                  label={
                    <>
                      {label}
                      <strong className="range-value">{values[key]}</strong>
                    </>
                  }
                  hint={
                    key === "anxiety"
                      ? "0 — нет тревоги · 10 — максимальная тревога"
                      : "0 — очень плохо · 10 — очень хорошо"
                  }
                >
                  <input
                    type="range"
                    min="0"
                    max="10"
                    name={key}
                    value={values[key]}
                    onChange={(e) =>
                      setValues({ ...values, [key]: Number(e.target.value) })
                    }
                  />
                </Field>
              ))}
            </div>
            <Field label="Что ещё важно рассказать?" hint="Необязательно">
              <textarea
                name="comment"
                rows="3"
                maxLength="5000"
                placeholder="Что повлияло на ваше самочувствие сегодня?"
              />
            </Field>
            <ErrorBox error={action.error} />
            <Submit pending={action.pending}>Сохранить запись</Submit>
          </form>
        </Section>
      ) : (
        <Section
          title="Расписание дневника"
          sub="Время указывается в часовом поясе пациента"
        >
          <form className="inline-form" onSubmit={schedule}>
            <Field label="Время заполнения через запятую">
              <input
                name="times"
                required
                defaultValue={(patient.diary_times || []).join(", ")}
                placeholder="09:00, 20:00"
                pattern="([0-1][0-9]|2[0-3]):[0-5][0-9](,\s*([0-1][0-9]|2[0-3]):[0-5][0-9])*"
              />
            </Field>
            <Submit pending={action.pending} />
          </form>
          <ErrorBox error={action.error} />
        </Section>
      )}
      <Section
        title="Динамика самочувствия"
        sub="Настроение и сон: выше — лучше. Тревожность: выше — хуже."
      >
        <DataState request={request}>
          <DiaryChart entries={request.data || []} />
        </DataState>
      </Section>
      <Section title="Записи дневника">
        <DataState request={request}>
          <Timeline
            items={request.data ? [...request.data].reverse() : []}
            render={(item) => (
              <>
                <strong>
                  <DateText value={item.created_at} />
                </strong>
                <div className="metric-pills">
                  {Object.entries(metrics).map(([key, label]) => (
                    <span key={key}>
                      {label} <b>{item[key]}/10</b>
                    </span>
                  ))}
                </div>
                {item.comment && <p>{item.comment}</p>}
              </>
            )}
          />
        </DataState>
      </Section>
    </>
  );
}
