import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Alert, User } from '../types'
import { Empty } from '../components/Form'
import { DoctorTools, DrugCatalog } from '../components/DoctorTools'
import { Alerts } from '../components/Alerts'
import { Workspace } from './Workspace'

export function Dashboard({ user }: { user: User }) {
  return user.role === 'doctor' ? <DoctorDashboard user={user} /> : <>
    {!user.doctor_id && <section className="card"><h2>Ваш лечащий врач</h2><p>Врач отправит приглашение на ваш email. Нажмите «Принять приглашение» в письме.</p></section>}
    <Workspace patient={user} user={user} />
  </>
}

function DoctorDashboard({ user }: { user: User }) {
  const [patients, setPatients] = useState<User[] | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState('')
  const [section, setSection] = useState('patients')
  useEffect(() => {
    let active = true
    Promise.all([api<User[]>('/patients'), api<Alert[]>('/alerts')]).then(([patients, alerts]) => {
      if (active) { setPatients(patients); setAlerts(alerts); setError('') }
    }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [revision])
  const reload = () => setRevision(r => r + 1)
  const patient = patients?.find(p => p.id === selected)
  return <><nav className="tabs" aria-label="Кабинет врача">{[['patients', 'Пациенты'], ['alerts', `Предупреждения (${alerts.filter(a => a.status === 'active').length})`], ['drugs', 'Справочник']].map(([key, label]) => <button key={key} aria-current={section === key ? 'page' : undefined} onClick={() => setSection(key)}>{label}</button>)}</nav>
    {error && <p role="alert" className="error">{error}<button onClick={reload}>Повторить</button></p>}
    {section === 'drugs' && <DrugCatalog />}
    {section === 'alerts' && <Alerts alerts={alerts} user={user} reload={reload} onOpenPatient={id => { setSelected(id); setSection('patients') }} />}
    {section === 'patients' && (patient ? <><button className="secondary" onClick={() => { setSelected(null); reload() }}>← К списку пациентов</button><Workspace key={patient.id} patient={patient} user={user} /></> : <>
      <div className="section-head"><h1>Мои пациенты</h1><button className="secondary" onClick={reload}>Обновить список</button></div>
      <section className="card">{patients === null && !error && <p role="status">Загрузка пациентов…</p>}{patients?.length === 0 && <Empty>Пригласите первого пациента. После принятия кода он появится в списке.</Empty>}
        {patients?.map(p => <button className="patient-row" key={p.id} onClick={() => setSelected(p.id)}><span><strong>{p.full_name}</strong><small>{p.email}</small></span><span>Открыть карточку →</span></button>)}
      </section><DoctorTools reload={reload} />
    </>)}
  </>
}
