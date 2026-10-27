import { useState } from 'react'
import { api } from '../api'
import type { Plan, Drug, User, Recommendation } from '../types'
import { Empty, Form } from './Form'
import { text, dateTime } from '../format'

export function Treatment({ plans, drugs, user, patientId, reload }: { plans: Plan[]; drugs: Drug[]; user: User; patientId: number; reload: () => void }) {
  const [copy, setCopy] = useState<Plan | undefined>()
  const [editorKey, setEditorKey] = useState(0)
  return <section className="card"><h2>{user.role === 'patient' ? 'Мои назначения' : 'Планы наблюдения и лечения'}</h2>
    {user.role === 'doctor' && <p className="muted">Изменение плана создаёт новую версию. Черновики видны только врачу; активация требует отдельного подтверждения.</p>}
    {!plans.length && <Empty>{user.role === 'patient' ? 'Назначений пока нет.' : 'Подтверждённых планов пока нет.'}</Empty>}
    {plans.map(plan => <article className="event" key={plan.id}><div className="section-head"><h3>{plan.title}{user.role === 'doctor' ? ` · v${plan.version}` : ''}</h3><span className="badge">{plan.status === 'active' ? 'Действующий' : plan.status === 'draft' ? 'Черновик' : 'Архив'}</span></div>
      <p className="prewrap">{plan.instructions}</p>
      {plan.prescriptions.map((p, i) => <div key={i}><strong>{p.drug.name}</strong><p>{p.regimen}</p>{user.role === 'doctor' && <><a href={p.drug.source_url} target="_blank" rel="noreferrer">Источник ГРЛС</a><p className="muted">Проверено врачом: {p.drug.verified_at ? dateTime(p.drug.verified_at) : '—'}. Регистрация: {p.drug.registration_number}</p></>}</div>)}
      {plan.confirmed_at && <small>Подтверждено врачом {dateTime(plan.confirmed_at)}</small>}
      {user.role === 'doctor' && <div className="row"><button className="secondary" onClick={() => { setCopy(plan); setEditorKey(key => key + 1) }}>Создать новую версию</button>
        {plan.status === 'draft' && <Form submit="Подтвердить план" action={async () => {
          if (!window.confirm('Подтвердить план и заменить действующую версию? Решение о терапии принимает врач.')) throw new Error('Подтверждение отменено')
          await api(`/patients/${patientId}/plans/${plan.id}/confirm`, {}); reload()
        }}>{null}</Form>}</div>}
    </article>)}
    {user.role === 'doctor' && <PlanEditor key={editorKey} copy={copy} patientId={patientId} drugs={drugs} reload={reload} />}
  </section>
}

function PlanEditor({ copy, patientId, drugs, reload }: { copy?: Plan; patientId: number; drugs: Drug[]; reload: () => void }) {
  const [rows, setRows] = useState(copy?.prescriptions.length ?? 0)
  const verified = drugs.filter(drug => drug.status === 'verified')
  return <details open={!!copy}><summary>{copy ? `Новая версия на основе v${copy.version}` : 'Создать черновик плана'}</summary>
    <Form submit="Сохранить черновик" action={async data => {
      const prescriptions = Array.from({ length: rows }, (_, i) => ({ drug_id: Number(text(data, `drug-${i}`)), regimen: text(data, `regimen-${i}`) }))
      await api(`/patients/${patientId}/plans`, { title: text(data, 'title'), instructions: text(data, 'instructions'), prescriptions }); reload()
    }}><label>Название<input name="title" defaultValue={copy?.title} maxLength={255} required /></label>
      <label>Инструкции врача<textarea name="instructions" defaultValue={copy?.instructions} maxLength={5000} rows={4} required /></label>
      <p className="notice">Лекарства доступны только после ручной проверки врачом записи ГРЛС. Непроверенный «Авиандр» заблокирован. Для демонстрации можно создать план наблюдения без лекарств.</p>
      {Array.from({ length: rows }, (_, i) => <fieldset key={i}><legend>Назначение {i + 1}</legend><label>Проверенный препарат<select name={`drug-${i}`} defaultValue={copy?.prescriptions[i]?.drug_id ?? ''} required><option value="">Выберите</option>{verified.map(drug => <option key={drug.id} value={drug.id}>{drug.name} · {drug.registration_number}</option>)}</select></label><label>Режим, определённый врачом<textarea name={`regimen-${i}`} defaultValue={copy?.prescriptions[i]?.regimen} maxLength={5000} required /></label></fieldset>)}
      <div className="row"><button type="button" className="secondary" disabled={!verified.length || rows >= 30} onClick={() => setRows(rows + 1)}>Добавить назначение</button>{rows > 0 && <button type="button" className="secondary" onClick={() => setRows(rows - 1)}>Убрать последнее</button>}</div>
    </Form></details>
}

export function Recommendations({ items, patientId, reload }: { items: Recommendation[]; patientId: number; reload: () => void }) {
  return <section className="card"><h2>Предложения для рассмотрения врачом</h2><p className="notice">Предложения требуют проверки источников врачом. Учебные правила demo_rule_v1 не имеют клинической валидации. Принятие предложения не создаёт назначений.</p>
    <details><summary>Запрос к существующей RAG-системе (опционально)</summary><p className="muted">Требует отдельно настроенного локального сервиса и проверенного корпуса документов. История пациента автоматически не передаётся.</p><Form submit="Получить черновик" action={async data => { await api(`/patients/${patientId}/recommendations/generate-rag`, { question: text(data, 'question') }); reload() }}><label>Вопрос врача<textarea name="question" maxLength={5000} required /></label></Form></details>
    {!items.length && <Empty />}{items.map(item => <article className="event" key={item.id}><h3>{item.title}</h3><p>{item.explanation}</p><small>Источник: {item.source} · Версия: {item.rule_version}</small>
      {item.evidence?.sources?.map((source, i) => <p key={i}>PDF-источник: {source.document}, стр. {source.page}. Клиническая проверка ожидается.</p>)}
      {item.evidence?.missing_information?.map((missing, i) => <p key={i} className="notice">Недостающие сведения: {missing}</p>)}
      <p>Статус: {item.status === 'pending' ? 'Ожидает рассмотрения' : item.status === 'accepted' ? 'Принято врачом' : 'Отклонено врачом'}</p>{item.review_comment && <p>{item.review_comment}</p>}
      {item.status === 'pending' && <Form submit="Сохранить решение" action={async data => {
        if (!window.confirm('Сохранить решение по предложению?')) throw new Error('Решение отменено')
        await api(`/patients/${patientId}/recommendations/${item.id}/review`, { status: text(data, 'status'), comment: text(data, 'comment') }); reload()
      }}><label>Решение<select name="status"><option value="accepted">Принять к рассмотрению</option><option value="rejected">Отклонить</option></select></label><label>Обоснование<textarea name="comment" maxLength={5000} required /></label></Form>}
    </article>)}
  </section>
}
