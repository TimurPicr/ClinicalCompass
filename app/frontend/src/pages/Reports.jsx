import React, { useEffect, useState } from "react";
import {
  Sparkles,
  Upload,
  Download,
  FileText,
  AlertTriangle,
  CheckCircle2,
  Clock,
  ExternalLink,
  RefreshCw,
} from "lucide-react";
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
  SourceLink,
  Timeline,
} from "../components/common";
const jobNames = {
  analysis: "Анализ состояния",
  document: "Обработка документа",
  knowledge: "Индексация источника",
  sync: "Обновление источников",
};
const proposalNames = {
  diagnosis: "Диагноз, указанный в документе",
  comorbidities: "Сопутствующие заболевания",
  history: "Анамнез",
  anamnesis: "Анамнез",
  allergies: "Аллергии",
  examinations: "Результаты обследований",
  treatment_history: "История лечения",
};
const categoryNames = {
  self_harm_screen: "Ответ PHQ-9 требует срочной оценки",
  scale_threshold: "Повышенный балл клинической шкалы",
  adherence: "Пропуски приёма препаратов",
  side_effect: "Предполагаемый побочный эффект",
  missing_questionnaire: "Опросник не заполнен вовремя",
  missing_diary: "Нет записей дневника",
  demo_critical: "Демонстрационный критический сценарий",
  ai: "Предупреждение AI-анализа",
};
export function AiSummary({ id }) {
  const { user } = useApp(),
    request = useData(`/patients/${id}/ai`),
    action = useAction();
  const analysis = request.data?.analysis;
  const result = analysis?.result;
  const jobs = request.data?.jobs || [];
  const processing = jobs.some((j) =>
    ["queued", "running", "pending", "retry"].includes(j.status),
  );
  useEffect(() => {
    if (processing) {
      const timer = setInterval(request.reload, 6000);
      return () => clearInterval(timer);
    }
  }, [processing]);
  return (
    <>
      <Section
        title="AI-анализ состояния"
        sub="Локальная модель рассматривает записи, динамику и медицинские источники"
        action={
          user.role === "doctor" && (
            <button
              className="btn"
              disabled={action.pending || processing}
              onClick={() =>
                action.run(
                  () => api(`/patients/${id}/ai`, { method: "POST" }),
                  "Анализ добавлен в очередь",
                )
              }
            >
              <Sparkles size={16} />
              {processing ? "Анализ в очереди" : "Запустить анализ"}
            </button>
          )
        }
      >
        <ErrorBox error={action.error} />
        <DataState request={request}>
          {result ? (
            <>
              <div className="ai-summary-box">
                <Sparkles size={22} />
                <div>
                  <h3>Сводка состояния</h3>
                  <p>
                    {user.role === "doctor"
                      ? result.summary
                      : result.patient_summary}
                  </p>
                  <small>
                    Обновлено <DateText value={analysis.created_at} /> ·{" "}
                    {analysis.model}
                  </small>
                </div>
              </div>
              <div className="two-col">
                <AnalysisList
                  title="Выявленные изменения"
                  items={result.changes}
                />
                <AnalysisList
                  title="Фактические сведения"
                  items={result.facts}
                />
              </div>
              {result.risks?.length > 0 && (
                <div className="analysis-block">
                  <h3>Потенциальные риски</h3>
                  {result.risks.map((r, i) => (
                    <div className={`risk-note ${r.level}`} key={i}>
                      <Status value={r.level} />
                      <p>{r.description}</p>
                      {r.evidence?.map((e, j) => (
                        <small key={j}>{e}</small>
                      ))}
                    </div>
                  ))}
                </div>
              )}
              {user.role === "doctor" && (
                <>
                  <AnalysisList
                    title="Гипотезы, требующие проверки"
                    items={result.hypotheses}
                  />
                  <AnalysisList
                    title="Для рассмотрения врачом"
                    items={result.recommendations}
                  />
                </>
              )}
              {result.explanation && (
                <div className="analysis-block">
                  <h3>Обоснование</h3>
                  <p>{result.explanation}</p>
                </div>
              )}
              {result.sources?.length > 0 && (
                <div className="analysis-block">
                  <h3>Использованные источники</h3>
                  <div className="source-list">
                    {result.sources.map((s, i) => (
                      <div key={s.id || i}>
                        <FileText size={16} />
                        <SourceLink url={s.url}>{s.title}</SourceLink>
                        {s.page && <small>стр. {s.page}</small>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <Empty icon={Sparkles}>
              Готового анализа пока нет. Основные функции и проверка правил
              работают независимо от модели.
            </Empty>
          )}
        </DataState>
      </Section>
      <Section
        title="Задачи анализа"
        sub="Тяжёлые задачи выполняются последовательно на локальном сервере"
      >
        <DataState request={request}>
          {jobs.length ? (
            <div className="list">
              {jobs.map((j) => (
                <div className="list-item job-item" key={j.id}>
                  <Clock size={18} />
                  <div className="grow">
                    <strong>{jobNames[j.kind] || "Фоновая обработка"}</strong>
                    <small>
                      <DateText value={j.created_at} /> · попыток: {j.attempts}
                    </small>
                    {j.error && <p className="job-error">{j.error}</p>}
                  </div>
                  <span className="tag">
                    {{
                      queued: "В очереди",
                      pending: "Ожидает",
                      running: "Выполняется",
                      completed: "Готово",
                      done: "Готово",
                      failed: "Ошибка",
                      retry: "Повтор",
                    }[j.status] || j.status}
                  </span>
                  {user.role === "doctor" && j.status === "failed" && (
                    <button
                      className="btn secondary"
                      disabled={action.pending}
                      onClick={() =>
                        action.run(
                          () =>
                            api(`/ai/jobs/${j.id}/retry`, { method: "POST" }),
                          "Задача добавлена в очередь повторно",
                        )
                      }
                    >
                      <RefreshCw size={14} />
                      Повторить
                    </button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <Empty>Задач пока нет</Empty>
          )}
        </DataState>
      </Section>
    </>
  );
}
function AnalysisList({ title, items }) {
  return items?.length ? (
    <div className="analysis-block">
      <h3>{title}</h3>
      <ul className="analysis-list">
        {items.map((item, i) => (
          <li key={i}>
            {typeof item === "string" ? item : JSON.stringify(item)}
          </li>
        ))}
      </ul>
    </div>
  ) : null;
}
export function Documents({ id }) {
  const { user } = useApp(),
    request = useData(`/patients/${id}/documents`),
    action = useAction();
  const [filename, setFilename] = useState("");
  const processing = request.data?.some((d) =>
    ["queued", "pending", "processing"].includes(d.status),
  );
  useEffect(() => {
    if (processing) {
      const timer = setInterval(request.reload, 6000);
      return () => clearInterval(timer);
    }
  }, [processing]);
  async function upload(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const result = await action.run(
      () =>
        api(`/patients/${id}/documents`, {
          method: "POST",
          body: new FormData(form),
        }),
      "Документ загружен и добавлен в очередь",
    );
    if (result) {
      form.reset();
      setFilename("");
    }
  }
  return (
    <>
      <Section
        title="Медицинские документы"
        sub="Оригиналы доступны только пациенту и его лечащему врачу"
      >
        <form className="upload-form" onSubmit={upload}>
          <label className="upload-zone">
            <Upload size={25} />
            <strong>{filename || "Выберите PDF или фотографию"}</strong>
            <span>PDF, JPEG или PNG · не более 15 МБ</span>
            <input
              type="file"
              name="file"
              accept="application/pdf,image/jpeg,image/png"
              required
              onChange={(e) => setFilename(e.target.files[0]?.name || "")}
            />
          </label>
          <ErrorBox error={action.error} />
          <Submit pending={action.pending}>Загрузить документ</Submit>
        </form>
      </Section>
      <Section
        title="Загруженные документы"
        sub="Извлечённые сведения требуют проверки врача"
      >
        <DataState request={request}>
          {request.data?.length ? (
            <div className="document-list">
              {request.data.map((doc) => (
                <Document
                  key={doc.id}
                  doc={doc}
                  doctor={user.role === "doctor"}
                />
              ))}
            </div>
          ) : (
            <Empty icon={FileText}>Документов пока нет</Empty>
          )}
        </DataState>
      </Section>
    </>
  );
}
function Document({ doc, doctor }) {
  const action = useAction();
  async function review(e) {
    e.preventDefault();
    const form = Object.fromEntries(new FormData(e.currentTarget));
    await action.run(
      () => api(`/documents/${doc.id}/review`, { method: "POST", body: form }),
      "Проверка документа сохранена",
    );
  }
  const extraction = doc.extraction || {};
  return (
    <div className="document">
      <div className="document-head">
        <span className="task-icon lavender">
          <FileText size={22} />
        </span>
        <div className="grow">
          <h3>{doc.name}</h3>
          <p>
            <DateText value={doc.created_at} /> · {Math.ceil(doc.size / 1024)}{" "}
            КБ
          </p>
        </div>
        <a
          className="btn secondary"
          href={`/api/documents/${doc.id}/download`}
          target="_blank"
          rel="noreferrer"
        >
          <Download size={15} />
          Оригинал
        </a>
      </div>
      <div className="document-tags">
        <span className="tag">
          {{
            queued: "В очереди",
            pending: "В очереди",
            processed: "Обработано",
            processing: "Обработка",
            completed: "Обработано",
            done: "Обработано",
            failed: "Ошибка обработки",
          }[doc.status] || doc.status}
        </span>
        <span
          className={`tag ${extraction.review_status === "confirmed" ? "positive" : ""}`}
        >
          {{
            unconfirmed: "Не подтверждено",
            confirmed: "Проверено врачом",
            rejected: "Отклонено",
          }[extraction.review_status] || "Не подтверждено"}
        </span>
      </div>
      {extraction.proposals?.length > 0 && (
        <details open>
          <summary>Предлагаемые сведения для карты</summary>
          <div className="notice">
            Предложения не изменяют медицинскую карту автоматически. Проверенные
            сведения врач вносит в карту отдельно.
          </div>
          {extraction.proposals.map((p, i) => (
            <div className="proposal" key={i}>
              <strong>
                {proposalNames[p.field] || "Медицинские сведения"}
              </strong>
              <p>
                {typeof p.value === "string"
                  ? p.value
                  : JSON.stringify(p.value)}
              </p>
              <blockquote>{p.quote}</blockquote>
              <small>Страница {p.page || "не определена"}</small>
            </div>
          ))}
        </details>
      )}
      {extraction.error && <ErrorBox error={extraction.error} />}{" "}
      {extraction.review_comment && (
        <p>Комментарий врача: {extraction.review_comment}</p>
      )}
      {doctor && (
        <form className="review-form" onSubmit={review}>
          <div className="form-grid">
            <Field label="Результат проверки">
              <select name="status">
                <option value="confirmed">Подтверждено</option>
                <option value="rejected">Отклонено</option>
              </select>
            </Field>
            <Field label="Комментарий">
              <input name="comment" placeholder="Основание решения" />
            </Field>
          </div>
          <ErrorBox error={action.error} />
          <Submit pending={action.pending}>Сохранить проверку</Submit>
        </form>
      )}
    </div>
  );
}
export function Alerts({ id }) {
  const request = useData(`/patients/${id}/alerts`);
  return (
    <Section
      title="Предупреждения"
      sub="Индикаторы для оценки врачом. Все решения сохраняются в истории."
    >
      <DataState request={request}>
        {request.data?.length ? (
          <div className="alert-list">
            {request.data.map((alert) => (
              <Alert key={alert.id} alert={alert} />
            ))}
          </div>
        ) : (
          <Empty icon={CheckCircle2}>Выявленных предупреждений нет</Empty>
        )}
      </DataState>
    </Section>
  );
}
function Alert({ alert }) {
  const action = useAction();
  async function submit(e) {
    e.preventDefault();
    const form = Object.fromEntries(new FormData(e.currentTarget));
    await action.run(
      () => api(`/alerts/${alert.id}/actions`, { method: "POST", body: form }),
      "Решение по предупреждению сохранено",
    );
  }
  return (
    <div className={`alert-card ${alert.level}`}>
      <div className="section-head">
        <Status value={alert.level} />
        <span className="tag">
          {{
            new: "Новое",
            resolved: "Условие больше не выявляется",
            seen: "Просмотрено",
            confirmed: "Подтверждено",
            dismissed: "Отклонено",
          }[alert.state] || alert.state}
        </span>
      </div>
      <h3>{categoryNames[alert.category] || "Изменение состояния"}</h3>
      <p>{alert.reason}</p>
      <div className="alert-source">
        <SourceLink url={alert.source_url}>
          {alert.source.startsWith("rule:")
            ? "Детерминированное правило"
            : "Локальный AI-анализ"}
        </SourceLink>
        <span>·</span>
        <DateText value={alert.created_at} />
      </div>
      <form className="review-form" onSubmit={submit}>
        <div className="form-grid">
          <Field label="Действие">
            <select name="action">
              <option value="seen">Отметить просмотренным</option>
              <option value="confirmed">Подтвердить</option>
              <option value="dismissed">Отклонить</option>
            </select>
          </Field>
          <Field label="Комментарий врача">
            <input name="comment" placeholder="Результат оценки" />
          </Field>
        </div>
        <ErrorBox error={action.error} />
        <Submit pending={action.pending}>Сохранить решение</Submit>
      </form>
      {alert.actions?.length > 0 && (
        <details>
          <summary>История действий ({alert.actions.length})</summary>
          <Timeline
            items={alert.actions}
            render={(a) => (
              <>
                <strong>
                  {{
                    seen: "Просмотрено",
                    confirmed: "Подтверждено",
                    dismissed: "Отклонено",
                  }[a.action] || a.action}
                </strong>
                <small>
                  <DateText value={a.created_at} />
                </small>
                <p>{a.comment}</p>
              </>
            )}
          />
        </details>
      )}
    </div>
  );
}
