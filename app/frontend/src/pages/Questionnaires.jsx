import React, { useState } from "react";
import {
  Plus,
  ClipboardList,
  ChevronDown,
  ArrowUp,
  ArrowDown,
  Trash2,
  CheckCircle2,
  Edit3,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { api } from "../api/client";
import {
  useApp,
  useData,
  useAction,
  DataState,
  Section,
  Empty,
  DateText,
  Field,
  Submit,
  ErrorBox,
  Modal,
  date,
  SourceLink,
  zonedIso,
} from "../components/common";
const typeNames = {
  single: "Один вариант",
  multiple: "Несколько вариантов",
  number: "Числовая шкала",
  text: "Свободный текст",
};
export default function Questionnaires({ id }) {
  const { user } = useApp(),
    templates = useData("/templates"),
    assignments = useData(`/patients/${id}/assignments`);
  const [assign, setAssign] = useState(false),
    [builder, setBuilder] = useState(null),
    [filling, setFilling] = useState(null);
  const doctor = user.role === "doctor";
  return (
    <>
      <Section
        title="Назначенные опросники"
        sub="Клинические шкалы и индивидуальные вопросы врача"
        action={
          doctor && (
            <button className="btn" onClick={() => setAssign(true)}>
              <Plus size={16} />
              Назначить опросник
            </button>
          )
        }
      >
        <DataState request={assignments}>
          {assignments.data?.length ? (
            <div className="assignment-list">
              {assignments.data.map((a) => (
                <div className="assignment" key={a.id}>
                  <div className="assignment-head">
                    <span className="task-icon lavender">
                      <ClipboardList size={21} />
                    </span>
                    <div className="grow">
                      <h3>{a.snapshot.name}</h3>
                      <p>
                        {a.schedule?.frequency === "daily"
                          ? "Ежедневно"
                          : a.schedule?.frequency === "weekly"
                            ? "Еженедельно"
                            : "Разовое назначение"}{" "}
                        · Срок: <DateText value={a.due_at} />
                        {a.schedule?.times?.length
                          ? ` · ${a.schedule.times.join(", ")}`
                          : ""}
                      </p>
                    </div>
                    {!doctor && a.active && (
                      <button
                        disabled={new Date(a.due_at) > new Date()}
                        title={
                          new Date(a.due_at) > new Date()
                            ? "Следующее заполнение доступно в срок назначения"
                            : undefined
                        }
                        className="btn"
                        onClick={() => setFilling(a)}
                      >
                        Заполнить
                      </button>
                    )}
                  </div>
                  <div className="assignment-footer">
                    <span className="tag">
                      {a.snapshot.kind === "custom"
                        ? "Пользовательский"
                        : "Стандартизированная шкала"}
                    </span>
                    <span>{a.responses?.length || 0} заполнений</span>
                  </div>
                  {a.responses?.length > 0 && (
                    <details>
                      <summary>Ответы и динамика</summary>
                      {a.responses.some(
                        (r) => r.score !== null && r.score !== undefined,
                      ) && <ScoreChart responses={a.responses} />}
                      <div className="response-list">
                        {[...a.responses]
                          .sort(
                            (a, b) =>
                              new Date(b.created_at) - new Date(a.created_at),
                          )
                          .map((response) => (
                            <details key={response.id}>
                              <summary>
                                <DateText value={response.created_at} />
                                {response.score !== null &&
                                  response.score !== undefined && (
                                    <span className="tag">
                                      {response.score} баллов
                                    </span>
                                  )}
                              </summary>
                              {a.snapshot.schema.questions.map((q) => (
                                <div className="answer-row" key={q.id}>
                                  <span>{q.label}</span>
                                  <strong>
                                    {formatAnswer(q, response.answers[q.id])}
                                  </strong>
                                </div>
                              ))}
                            </details>
                          ))}
                      </div>
                    </details>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <Empty icon={ClipboardList}>Опросники пока не назначены</Empty>
          )}
        </DataState>
      </Section>
      {doctor && (
        <Section
          title="Библиотека шаблонов"
          sub="Изменение шаблона не меняет уже сохранённые ответы"
          action={
            <button className="btn secondary" onClick={() => setBuilder({})}>
              <Plus size={16} />
              Создать шаблон
            </button>
          }
        >
          <DataState request={templates}>
            <div className="template-grid">
              {templates.data?.map((t) => (
                <div className="template-card" key={t.id}>
                  <span className="tag">
                    {t.kind === "custom"
                      ? "Собственный опросник"
                      : "Клиническая шкала"}
                  </span>
                  <h3>{t.name}</h3>
                  <p>
                    {t.schema.questions.length} вопросов · версия {t.version}
                  </p>
                  {t.kind === "custom" ? (
                    <button className="text-btn" onClick={() => setBuilder(t)}>
                      <Edit3 size={14} />
                      Редактировать
                    </button>
                  ) : (
                    <small className="muted">
                      Вопросы и подсчёт фиксированы
                    </small>
                  )}
                </div>
              ))}
            </div>
          </DataState>
        </Section>
      )}
      {assign && (
        <Modal title="Назначить опросник" onClose={() => setAssign(false)}>
          <AssignmentForm
            id={id}
            templates={templates.data || []}
            onDone={() => setAssign(false)}
          />
        </Modal>
      )}
      {builder && (
        <Modal
          title={builder.id ? "Изменить шаблон" : "Новый опросник"}
          onClose={() => setBuilder(null)}
        >
          <Builder template={builder} onDone={() => setBuilder(null)} />
        </Modal>
      )}
      {filling && (
        <Modal title={filling.snapshot.name} onClose={() => setFilling(null)}>
          <ResponseForm assignment={filling} onDone={() => setFilling(null)} />
        </Modal>
      )}
    </>
  );
}
function formatAnswer(q, value) {
  if (value === undefined) return "Нет ответа";
  if (Array.isArray(value))
    return value
      .map(
        (v) =>
          q.options?.find((o) => String(o.value) === String(v))?.label || v,
      )
      .join(", ");
  return (
    q.options?.find((o) => String(o.value) === String(value))?.label ||
    String(value)
  );
}
function ScoreChart({ responses }) {
  const { user } = useApp();
  const data = [...responses]
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
    .map((r) => ({ ...r, label: date(r.created_at, user.timezone, false) }));
  return (
    <div className="chart-container">
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 20, left: -20, right: 10 }}>
          <CartesianGrid strokeDasharray="3 4" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
          <Tooltip />
          <Line dataKey="score" name="Баллы" stroke="#2d8172" strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
function AssignmentForm({ id, templates, onDone }) {
  const patient = useData(`/patients/${id}`);
  const action = useAction();
  const timezone = patient.data?.timezone || "Europe/Moscow";
  async function submit(e) {
    e.preventDefault();
    const form = Object.fromEntries(new FormData(e.currentTarget));
    const result = await action.run(() =>
      api(`/patients/${id}/assignments`, {
        method: "POST",
        body: {
          template_id: Number(form.template_id),
          due_at: zonedIso(form.due_at, timezone),
          schedule: {
            frequency: form.frequency,
            times: form.times
              .split(",")
              .map((v) => v.trim())
              .filter(Boolean),
          },
        },
      }),
    );
    if (result) onDone();
  }
  return (
    <form className="form-stack" onSubmit={submit}>
      <Field label="Опросник">
        <select name="template_id" required defaultValue="">
          <option value="" disabled>
            Выберите шаблон
          </option>
          {templates.map((t) => (
            <option value={t.id} key={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="Срок заполнения"
        hint={`Время в часовом поясе пациента: ${timezone}`}
      >
        <input type="datetime-local" name="due_at" required />
      </Field>
      <Field label="Повторение">
        <select name="frequency">
          <option value="once">Разово</option>
          <option value="daily">Ежедневно</option>
          <option value="weekly">Еженедельно</option>
        </select>
      </Field>
      <Field
        label="Время напоминаний через запятую"
        hint="В часовом поясе пациента"
      >
        <input
          name="times"
          defaultValue="09:00"
          required
          pattern="([0-1][0-9]|2[0-3]):[0-5][0-9](,\s*([0-1][0-9]|2[0-3]):[0-5][0-9])*"
        />
      </Field>
      <ErrorBox error={action.error} />
      <Submit pending={action.pending}>Назначить</Submit>
    </form>
  );
}
function ResponseForm({ assignment, onDone }) {
  const action = useAction(),
    [answers, setAnswers] = useState({});
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [validation, setValidation] = useState("");
  const questions = assignment.snapshot.schema.questions;
  function change(q, value) {
    setAnswers({ ...answers, [q.id]: value });
  }
  async function submit(e) {
    e.preventDefault();
    if (
      questions.some(
        (q) =>
          answers[q.id] === undefined ||
          answers[q.id] === "" ||
          (Array.isArray(answers[q.id]) && !answers[q.id].length),
      )
    ) {
      setValidation("Пожалуйста, ответьте на каждый вопрос.");
      return;
    }
    const result = await action.run(
      () =>
        api(`/assignments/${assignment.id}/responses`, {
          method: "POST",
          body: { answers, idempotency_key: idempotencyKey },
        }),
      "Ответы сохранены",
    );
    if (result) onDone();
  }
  return (
    <form className="form-stack" onSubmit={submit}>
      {assignment.snapshot.schema.instructions && (
        <p className="notice">{assignment.snapshot.schema.instructions}</p>
      )}
      {assignment.snapshot.schema.notice && (
        <p className="notice">{assignment.snapshot.schema.notice}</p>
      )}
      {questions.map((q, i) => (
        <fieldset className="question" key={q.id}>
          <legend>
            {i + 1}. {q.label}
          </legend>
          {["single", "multiple"].includes(q.type) ? (
            <div className="question-options">
              {q.options?.map((option, j) => (
                <label key={j}>
                  <input
                    type={q.type === "single" ? "radio" : "checkbox"}
                    name={q.id}
                    checked={
                      q.type === "single"
                        ? answers[q.id] === option.value
                        : (answers[q.id] || []).includes(option.value)
                    }
                    onChange={(e) =>
                      change(
                        q,
                        q.type === "single"
                          ? option.value
                          : e.target.checked
                            ? [...(answers[q.id] || []), option.value]
                            : (answers[q.id] || []).filter(
                                (v) => v !== option.value,
                              ),
                      )
                    }
                  />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
          ) : q.type === "number" ? (
            <>
              <input
                type="number"
                min={q.min ?? 0}
                max={q.max ?? 10}
                value={answers[q.id] ?? ""}
                onChange={(e) =>
                  change(q, e.target.value === "" ? "" : Number(e.target.value))
                }
                required
              />
              <small className="muted">
                От {q.min} до {q.max}
              </small>
            </>
          ) : (
            <textarea
              rows="3"
              maxLength="5000"
              value={answers[q.id] || ""}
              onChange={(e) => change(q, e.target.value)}
              required
            />
          )}
        </fieldset>
      ))}
      {assignment.snapshot.schema.sources?.length > 0 && (
        <details>
          <summary>Источники шкалы</summary>
          {assignment.snapshot.schema.sources.map((s, i) => (
            <p key={i}>
              {typeof s === "string" ? (
                <SourceLink url={s}>{s}</SourceLink>
              ) : (
                <SourceLink url={s.url}>{s.title || s.url}</SourceLink>
              )}
            </p>
          ))}
        </details>
      )}
      <ErrorBox error={action.error || validation} />
      <Submit pending={action.pending}>Отправить ответы</Submit>
    </form>
  );
}
function Builder({ template, onDone }) {
  const action = useAction();
  const [name, setName] = useState(template.name || ""),
    [instructions, setInstructions] = useState(
      template.schema?.instructions || "",
    ),
    [questions, setQuestions] = useState(
      template.schema?.questions?.map((q) => ({
        ...q,
        optionsText: q.options?.map((o) => o.label).join("\n") || "",
      })) || [
        {
          id: "q1",
          label: "",
          type: "single",
          optionsText: "Да\nНет",
          min: 0,
          max: 10,
        },
      ],
    );
  function update(i, patch) {
    setQuestions(questions.map((q, j) => (i === j ? { ...q, ...patch } : q)));
  }
  function move(i, offset) {
    const array = [...questions];
    [array[i], array[i + offset]] = [array[i + offset], array[i]];
    setQuestions(array);
  }
  async function submit(e) {
    e.preventDefault();
    const schema = {
      instructions,
      questions: questions.map(({ optionsText, ...q }) => ({
        ...q,
        min: Number(q.min ?? 0),
        max: Number(q.max ?? 10),
        options: ["single", "multiple"].includes(q.type)
          ? optionsText
              .split("\n")
              .map((v) => v.trim())
              .filter(Boolean)
              .map((label, value) => ({ value, label }))
          : [],
      })),
    };
    const result = await action.run(() =>
      api(template.id ? `/templates/${template.id}` : "/templates", {
        method: template.id ? "PUT" : "POST",
        body: { name, schema },
      }),
    );
    if (result) onDone();
  }
  return (
    <form className="form-stack" onSubmit={submit}>
      <Field label="Название опросника">
        <input
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength="200"
        />
      </Field>
      <Field label="Инструкция для пациента">
        <textarea
          rows="2"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
      </Field>
      {questions.map((q, i) => (
        <div className="builder-question" key={q.id}>
          <div className="section-head">
            <strong>Вопрос {i + 1}</strong>
            <div className="button-row">
              <button
                type="button"
                className="icon-btn"
                disabled={i === 0}
                onClick={() => move(i, -1)}
                aria-label="Вопрос выше"
              >
                <ArrowUp size={16} />
              </button>
              <button
                type="button"
                className="icon-btn"
                disabled={i === questions.length - 1}
                onClick={() => move(i, 1)}
                aria-label="Вопрос ниже"
              >
                <ArrowDown size={16} />
              </button>
              <button
                type="button"
                className="icon-btn"
                disabled={questions.length === 1}
                onClick={() =>
                  setQuestions(questions.filter((_, j) => i !== j))
                }
                aria-label="Удалить вопрос"
              >
                <Trash2 size={16} />
              </button>
            </div>
          </div>
          <Field label="Формулировка">
            <input
              required
              value={q.label}
              onChange={(e) => update(i, { label: e.target.value })}
            />
          </Field>
          <Field label="Тип ответа">
            <select
              value={q.type}
              onChange={(e) => update(i, { type: e.target.value })}
            >
              {Object.entries(typeNames).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          {["single", "multiple"].includes(q.type) ? (
            <Field label="Варианты, каждый с новой строки">
              <textarea
                required
                rows="3"
                value={q.optionsText}
                onChange={(e) => update(i, { optionsText: e.target.value })}
              />
            </Field>
          ) : q.type === "number" ? (
            <div className="form-grid">
              <Field label="Минимум">
                <input
                  type="number"
                  value={q.min}
                  onChange={(e) => update(i, { min: e.target.value })}
                />
              </Field>
              <Field label="Максимум">
                <input
                  type="number"
                  value={q.max}
                  onChange={(e) => update(i, { max: e.target.value })}
                />
              </Field>
            </div>
          ) : null}
        </div>
      ))}
      <button
        className="btn secondary"
        type="button"
        onClick={() =>
          setQuestions([
            ...questions,
            {
              id: crypto.randomUUID(),
              label: "",
              type: "text",
              optionsText: "",
              min: 0,
              max: 10,
            },
          ])
        }
      >
        <Plus size={16} />
        Добавить вопрос
      </button>
      <ErrorBox error={action.error} />
      <Submit pending={action.pending}>Сохранить шаблон</Submit>
    </form>
  );
}
