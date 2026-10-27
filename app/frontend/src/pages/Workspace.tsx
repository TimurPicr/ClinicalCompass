import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Adverse, Alert, Drug, Message, Plan, Recommendation, Report, Result, Scale, Series, User } from '../types'
import { Alerts } from '../components/Alerts'
import { Chat } from '../components/Chat'
import { Followup } from '../components/Followup'
import { Monitoring } from '../components/Monitoring'
import { DiaryCalendar } from '../components/DiaryCalendar'
import { Recommendations, Treatment } from '../components/Treatment'

interface Bundle { results: Result[]; series: Series[]; scales: Scale[]; plans: Plan[]; reports: Report[]; events: Adverse[]; messages: Message[]; alerts: Alert[]; recommendations: Recommendation[]; drugs: Drug[] }

export function Workspace({ patient, user }: { patient: User; user: User }) {
  const [data, setData] = useState<Bundle | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [filter, setFilter] = useState('')
  const [tab, setTab] = useState('monitoring')
  const [updating, setUpdating] = useState(false)
  useEffect(() => {
    let active = true
    const base = `/patients/${patient.id}`
    const query = filter ? `?${filter}` : ''
    Promise.all([
      user.role === 'doctor' ? api<Result[]>(`${base}/results${query}`) : Promise.resolve([] as Result[]), user.role === 'doctor' ? api<Series[]>(`${base}/series${query}`) : Promise.resolve([] as Series[]), user.role === 'doctor' ? api<Scale[]>('/scales') : Promise.resolve([] as Scale[]),
      api<Plan[]>(`${base}/plans`), api<Report[]>(`${base}/adherence`), api<Adverse[]>(`${base}/adverse-events`),
      Promise.resolve([] as Message[]), api<Alert[]>(`${base}/alerts`),
      user.role === 'doctor' ? api<Recommendation[]>(`${base}/recommendations`) : Promise.resolve([] as Recommendation[]),
      user.role === 'doctor' ? api<Drug[]>('/drugs') : Promise.resolve([] as Drug[]),
    ]).then(([results, series, scales, plans, reports, events, messages, alerts, recommendations, drugs]) => {
      if (active) { setData({ results, series, scales, plans, reports, events, messages, alerts, recommendations, drugs }); setError('') }
    }).catch(e => { if (active) setError(e.message) }).finally(() => { if (active) setUpdating(false) })
    return () => { active = false }
  }, [patient.id, user.role, revision, filter])
  const reload = () => { setUpdating(true); setRevision(r => r + 1) }
  if (!data && !error) return <p role="status">Загрузка карточки пациента…</p>
  return <><div className="section-head"><div><p className="eyebrow">{user.role === 'doctor' ? 'Карточка пациента' : 'Личный кабинет'}</p><h1>{patient.full_name}</h1>{user.role === 'doctor' && <p className="muted">{patient.email}</p>}</div><button className="secondary" onClick={reload} disabled={updating}>{updating ? 'Обновление…' : 'Обновить данные'}</button></div>
    {error && <p role="alert" className="error">{error} · Повторите обновление данных.</p>}
    {data && <>{user.role === 'doctor' && <div className="stats"><div><strong>{data.results.length}</strong><span>обследований в выбранном периоде</span></div><div><strong>{data.alerts.filter(a => a.status === 'active').length}</strong><span>активных предупреждений</span></div><div><strong>{data.plans.find(p => p.status === 'active') ? 'Есть' : 'Нет'}</strong><span>подтверждённый план</span></div></div>}
      <nav className="tabs" aria-label="Разделы карточки">{[['monitoring', user.role === 'patient' ? 'Дневник' : 'Дневник и динамика'], ['treatment', user.role === 'patient' ? 'Назначения' : 'План и наблюдение'], ['alerts', user.role === 'patient' ? 'Связь с врачом' : 'Предупреждения'], ['chat', 'Чат']].map(([key, label]) => <button key={key} aria-current={tab === key ? 'page' : undefined} onClick={() => setTab(key)}>{label}</button>)}</nav>
      {tab === 'monitoring' && <><DiaryCalendar refreshKey={revision} patientId={patient.id} readOnly={user.role === 'doctor'} />{user.role === 'doctor' && <details><summary>История всех опросов</summary><Monitoring results={data.results} series={data.series} scales={data.scales} onFilter={async query => { if (query === filter) reload(); else { setUpdating(true); setFilter(query) } }} /></details>}</>}
      {tab === 'treatment' && <>{user.role === 'doctor' && <Recommendations items={data.recommendations} patientId={patient.id} reload={reload} />}<Treatment plans={data.plans} drugs={data.drugs} user={user} patientId={patient.id} reload={reload} /><Followup reports={data.reports} events={data.events} plans={data.plans} user={user} patientId={patient.id} reload={reload} /></>}
      {tab === 'alerts' && <Alerts alerts={data.alerts} user={user} reload={reload} />}
      {tab === 'chat' && <Chat messages={data.messages} user={user} patientId={patient.id} reload={reload} />}
    </>}
  </>
}
