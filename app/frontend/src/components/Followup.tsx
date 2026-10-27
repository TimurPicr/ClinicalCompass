import { api } from '../api'
import type { Adverse, Plan, Report, User } from '../types'
import { Empty, Form } from './Form'
import { text, today } from '../format'

const statusLabel = (status: string) => ({ completed: 'Выполнено со слов пациента', partial: 'Частично', missed: 'Пропуск' })[status] ?? status

export function Followup({ reports, events, plans, user, patientId, reload }: { reports: Report[]; events: Adverse[]; plans: Plan[]; user: User; patientId: number; reload: () => void }) {
  const active = plans.find(p => p.status === 'active')
  return <><section className="card"><h2>{user.role === 'patient' ? 'Выполнение назначений' : 'Приверженность: самоотчёты'}</h2>{user.role === 'doctor' && <p className="muted">Самоотчёт не подтверждает фактический приём лекарства. Один отчёт на план за день.</p>}
    {user.role === 'patient' && (active ? <Form submit="Отметить выполнение" action={async data => { await api(`/patients/${patientId}/adherence`, { plan_id: active.id, report_date: text(data, 'date'), status: text(data, 'status'), note: text(data, 'note') }); reload() }}>
      <p>Действующий план: {active.title}</p><div className="row"><label>Дата<input name="date" type="date" defaultValue={today()} max={today()} required /></label><label>Выполнение<select name="status"><option value="completed">Выполнено</option><option value="partial">Частично</option><option value="missed">Пропущено</option></select></label></div><label>Комментарий<textarea name="note" maxLength={5000} /></label>
    </Form> : <Empty>Форма появится после подтверждения плана врачом.</Empty>)}
    <p>Отчётов: {reports.length} · Выполнено: {reports.filter(r => r.status === 'completed').length} · Частично: {reports.filter(r => r.status === 'partial').length} · Пропусков: {reports.filter(r => r.status === 'missed').length}</p>
    {!reports.length ? <Empty /> : <div className="table-wrap"><table><thead><tr><th>Дата</th>{user.role === 'doctor' && <th>План</th>}<th>{user.role === 'patient' ? 'Выполнение' : 'Самоотчёт'}</th><th>Комментарий</th></tr></thead><tbody>{reports.map(r => <tr key={r.id}><td>{r.report_date}</td>{user.role === 'doctor' && <td>#{r.plan_id}</td>}<td>{user.role === 'patient' && r.status === 'completed' ? 'Выполнено' : statusLabel(r.status)}</td><td>{r.note}</td></tr>)}</tbody></table></div>}
  </section><section className="card"><h2>Нежелательные явления</h2>{user.role === 'doctor' && <p className="notice">Сообщение не устанавливает причинную связь с препаратом.</p>}
    {user.role === 'patient' && <Form submit="Сообщить врачу" reset action={async data => {
      if (!window.confirm('Отправить описание лечащему врачу?')) throw new Error('Отправка отменена')
      await api(`/patients/${patientId}/adverse-events`, { description: text(data, 'description'), onset_date: text(data, 'onset'), plan_id: text(data, 'plan') ? Number(text(data, 'plan')) : null }); reload()
    }}><label>Дата появления<input type="date" name="onset" max={today()} defaultValue={today()} required /></label><label>План (при наличии)<select name="plan"><option value="">Не связан с планом</option>{plans.filter(p => p.confirmed_at).map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select></label><label>Что произошло<textarea name="description" maxLength={5000} rows={3} required /></label></Form>}
    {!events.length && <Empty />}{events.map(event => <article className="event" key={event.id}><strong>{event.onset_date} · {event.status === 'pending' ? 'Ожидает рассмотрения' : 'Рассмотрено'}</strong><p className="prewrap">{event.description}</p>{event.comment && <p>Комментарий врача: {event.comment}</p>}
      {user.role === 'doctor' && event.status === 'pending' && <Form submit="Отметить рассмотренным" action={async data => { await api(`/patients/${patientId}/adverse-events/${event.id}/review`, { comment: text(data, 'comment') }); reload() }}><label>Комментарий врача<textarea name="comment" maxLength={5000} required /></label></Form>}
    </article>)}
  </section></>
}
