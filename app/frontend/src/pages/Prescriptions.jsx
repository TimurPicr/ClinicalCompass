import React, { useState } from "react";
import {
  Pill,
  Plus,
  Clock,
  ChevronDown,
  CheckCircle2,
  History,
} from "lucide-react";
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
  Timeline,
  localInput,
  zonedIso,
} from "../components/common";
export function Prescriptions({ id }) {
  const { user } = useApp(),
    request = useData(`/patients/${id}/prescriptions`);
  const [editing, setEditing] = useState(null),
    [intake, setIntake] = useState(null);
  const doctor = user.role === "doctor";
  return (
    <>
      <Section
        title="Назначения препаратов"
        sub="Дозировки и расписание определяет лечащий врач"
        action={
          doctor && (
            <button className="btn" onClick={() => setEditing({})}>
              <Plus size={16} />
              Добавить назначение
            </button>
          )
        }
      >
        <DataState request={request}>
          {request.data?.length ? (
            <div className="prescription-list">
              {request.data.map((item) => (
                <div
                  className={`prescription ${item.active ? "" : "inactive"}`}
                  key={item.id}
                >
                  <div className="prescription-head">
                    <span className="task-icon mint">
                      <Pill size={22} />
                    </span>
                    <div className="grow">
                      <h3>
                        {item.data.name}
                        <span className="tag">
                          {item.active ? "Действует" : "Завершено"}
                        </span>
                      </h3>
                      <p>
                        {item.data.substance ||
                          "Действующее вещество не указано"}
                      </p>
                    </div>
                    {doctor ? (
                      <button
                        className="btn secondary"
                        onClick={() => setEditing(item)}
                      >
                        Изменить
                      </button>
                    ) : (
                      item.active && (
                        <button className="btn" onClick={() => setIntake(item)}>
                          <CheckCircle2 size={15} />
                          Отметить приём
                        </button>
                      )
                    )}
                  </div>
                  <div className="prescription-meta">
                    <div>
                      <small>Дозировка</small>
                      <strong>
                        {item.data.dose} {item.data.unit}
                      </strong>
                    </div>
                    <div>
                      <small>Время приёма</small>
                      <strong>
                        <Clock size={13} />
                        {item.data.times.join(" · ")}
                      </strong>
                    </div>
                    <div>
                      <small>Период</small>
                      <strong>
                        <DateText value={item.data.start_date} time={false} />
                        {item.data.end_date && (
                          <>
                            {" "}
                            —{" "}
                            <DateText value={item.data.end_date} time={false} />
                          </>
                        )}
                      </strong>
                    </div>
                  </div>
                  {item.data.comment && (
                    <p className="doctor-comment">{item.data.comment}</p>
                  )}
                  <details>
                    <summary>
                      <History size={15} />
                      История назначения и приёма
                    </summary>
                    <h4>Версии назначения</h4>
                    <Timeline
                      items={item.versions}
                      render={(v) => (
                        <>
                          <strong>
                            Версия {v.version} · {v.data.dose} {v.data.unit} ·{" "}
                            {v.data.times?.join(", ")}
                          </strong>
                          <small>
                            <DateText value={v.created_at} />
                          </small>
                          <p>{v.data.comment}</p>
                        </>
                      )}
                    />
                    <h4>Отметки пациента</h4>
                    <Timeline
                      items={item.intakes}
                      render={(v) => (
                        <>
                          <strong>
                            {v.status === "taken" ? "Принято" : "Пропущено"}
                          </strong>
                          <small>
                            По расписанию <DateText value={v.scheduled_at} />
                            {v.actual_at && (
                              <>
                                {" "}
                                · Фактически <DateText value={v.actual_at} />
                              </>
                            )}
                          </small>
                          {v.reason && <p>Причина: {v.reason}</p>}
                          {v.side_effect && (
                            <p>
                              Предполагаемый побочный эффект: {v.side_effect} ·
                              выраженность {v.severity}/10
                            </p>
                          )}
                        </>
                      )}
                    />
                  </details>
                </div>
              ))}
            </div>
          ) : (
            <Empty icon={Pill}>Назначений пока нет</Empty>
          )}
        </DataState>
      </Section>
      {editing && (
        <Modal
          title={editing.id ? "Изменить назначение" : "Новое назначение"}
          onClose={() => setEditing(null)}
        >
          <PrescriptionForm
            id={id}
            item={editing}
            onDone={() => setEditing(null)}
          />
        </Modal>
      )}
      {intake && (
        <Modal
          title={`Приём: ${intake.data.name}`}
          onClose={() => setIntake(null)}
        >
          <IntakeForm item={intake} onDone={() => setIntake(null)} />
        </Modal>
      )}
    </>
  );
}
function PrescriptionForm({ id, item, onDone }) {
  const action = useAction();
  const data = item.data || {};
  async function submit(e) {
    e.preventDefault();
    const raw = Object.fromEntries(new FormData(e.currentTarget));
    const body = {
      ...raw,
      dose: raw.dose,
      times: raw.times
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean),
      end_date: raw.end_date || null,
      active: raw.active !== "false",
    };
    const result = await action.run(() =>
      api(
        item.id ? `/prescriptions/${item.id}` : `/patients/${id}/prescriptions`,
        { method: item.id ? "PUT" : "POST", body },
      ),
    );
    if (result) onDone();
  }
  return (
    <form onSubmit={submit} className="form-stack">
      <div className="form-grid">
        <Field label="Название препарата">
          <input
            name="name"
            defaultValue={data.name}
            required
            maxLength="200"
          />
        </Field>
        <Field label="Действующее вещество">
          <input name="substance" defaultValue={data.substance || ""} />
        </Field>
        <Field label="Дозировка">
          <input name="dose" defaultValue={data.dose} required />
        </Field>
        <Field label="Единицы измерения">
          <input name="unit" defaultValue={data.unit || "мг"} required />
        </Field>
        <Field
          label="Время приёма через запятую"
          hint="В часовом поясе пациента, формат ЧЧ:ММ"
        >
          <input
            name="times"
            defaultValue={data.times?.join(", ") || "09:00"}
            required
            pattern="([0-1][0-9]|2[0-3]):[0-5][0-9](,\s*([0-1][0-9]|2[0-3]):[0-5][0-9])*"
          />
        </Field>
        <Field label="Дата начала">
          <input
            type="date"
            name="start_date"
            defaultValue={
              data.start_date || new Date().toISOString().slice(0, 10)
            }
            required
          />
        </Field>
        <Field label="Дата окончания">
          <input
            type="date"
            name="end_date"
            defaultValue={data.end_date || ""}
          />
        </Field>
        {item.id && (
          <Field label="Статус">
            <select name="active" defaultValue={String(item.active)}>
              <option value="true">Действует</option>
              <option value="false">Завершено</option>
            </select>
          </Field>
        )}
      </div>
      <Field label="Комментарий врача">
        <textarea name="comment" defaultValue={data.comment || ""} rows="3" />
      </Field>
      <ErrorBox error={action.error} />
      <Submit pending={action.pending} />
    </form>
  );
}
function IntakeForm({ item, onDone }) {
  const { user } = useApp();
  const action = useAction(),
    [status, setStatus] = useState("taken");
  const timezone = user.timezone || "Europe/Moscow";
  const today = localInput(new Date(), timezone);
  const clocks = item.data.times;
  const previous = clocks.filter((t) => t <= today.slice(11)).at(-1);
  const defaultDay = previous
    ? today.slice(0, 10)
    : localInput(new Date(Date.now() - 86400000), timezone).slice(0, 10);
  async function submit(e) {
    e.preventDefault();
    const raw = Object.fromEntries(new FormData(e.currentTarget));
    const result = await action.run(() => {
      const body = {
        status,
        scheduled_at: zonedIso(`${raw.day}T${raw.clock}`, timezone),
        actual_at:
          status === "taken" ? zonedIso(raw.actual_at, timezone) : null,
        reason: raw.reason || "",
        side_effect: raw.side_effect || "",
        severity: Number(raw.severity || 0),
      };
      return api(`/prescriptions/${item.id}/intakes`, { method: "POST", body });
    }, "Отметка о приёме сохранена");
    if (result) onDone();
  }
  return (
    <form className="form-stack" onSubmit={submit}>
      <div className="segmented">
        <button
          type="button"
          className={status === "taken" ? "active" : ""}
          onClick={() => setStatus("taken")}
        >
          Принято
        </button>
        <button
          type="button"
          className={status === "missed" ? "active" : ""}
          onClick={() => setStatus("missed")}
        >
          Пропущено
        </button>
      </div>
      <div className="notice">
        Время в вашем часовом поясе: {timezone}. Выберите приём по назначенному
        расписанию.
      </div>
      <div className="form-grid">
        <Field label="Дата приёма">
          <input type="date" name="day" defaultValue={defaultDay} required />
        </Field>
        <Field label="Плановое время">
          <select name="clock" defaultValue={previous || clocks.at(-1)}>
            {clocks.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {status === "taken" ? (
        <Field label="Фактическое время">
          <input
            type="datetime-local"
            name="actual_at"
            defaultValue={today}
            required
          />
        </Field>
      ) : (
        <Field label="Причина пропуска">
          <textarea name="reason" rows="2" required maxLength="3000" />
        </Field>
      )}
      <Field
        label="Предполагаемый побочный эффект"
        hint="Совпадение по времени не означает причинную связь"
      >
        <textarea name="side_effect" rows="2" maxLength="3000" />
      </Field>
      <Field label="Выраженность эффекта: 0 — нет, 10 — максимальная">
        <input
          type="number"
          name="severity"
          min="0"
          max="10"
          defaultValue="0"
        />
      </Field>
      <ErrorBox error={action.error} />
      <Submit pending={action.pending}>Сохранить отметку</Submit>
    </form>
  );
}
