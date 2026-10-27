import { useState } from 'react'
import { api } from '../api'
import type { Alert, User } from '../types'
import { Empty, Form } from './Form'
import { dateTime } from '../format'

export function Alerts({ alerts, user, reload, onOpenPatient }: { alerts: Alert[]; user: User; reload: () => void; onOpenPatient?: (id: number) => void }) {
  const [eventKey, setEventKey] = useState(() => crypto.randomUUID())
  return <section className="card"><div className="section-head"><h2>{user.role === 'patient' ? 'Запросы врачу' : 'Предупреждения и запросы связи'}</h2><button className="secondary" onClick={reload}>Обновить предупреждения</button></div>
    <p className="notice">Срочный ответ не гарантируется. При угрозе жизни обратитесь в экстренные службы.</p>
    {user.role === 'patient' && <Form submit="Запросить срочную связь" action={async () => {
      if (!window.confirm('Сохранить запрос связи в кабинете врача? Срочный ответ не гарантирован.')) throw new Error('Отправка отменена')
      await api('/urgent-help', { event_key: eventKey }); setEventKey(crypto.randomUUID()); reload()
    }}><p>Используйте кнопку, если хотите явно сообщить врачу о необходимости срочной связи.</p></Form>}
    {!alerts.length && <Empty />}
    {alerts.map(alert => <article key={alert.id} className={`event ${alert.severity === 'critical' && alert.status === 'active' ? 'critical' : ''}`}>
      <strong>{alert.text}</strong><p>{dateTime(alert.created_at)} · {alert.status === 'active' ? 'Ожидает врача' : 'Получение подтверждено'}</p>
      {user.role === 'doctor' && (onOpenPatient ? <button className="secondary" onClick={() => onOpenPatient(alert.patient_id)}>Открыть пациента #{alert.patient_id}</button> : <p>Пациент #{alert.patient_id}</p>)}
      {user.role === 'doctor' && alert.status === 'active' && <Form submit="Подтвердить получение" action={async () => { await api(`/alerts/${alert.id}/acknowledge`, {}); reload() }}>{null}</Form>}
    </article>)}
  </section>
}
