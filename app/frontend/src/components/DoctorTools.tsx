import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Drug } from '../types'
import { Form, Empty } from './Form'
import { text } from '../format'

export function DoctorTools({ reload }: { reload: () => void }) {
  return <section className="card"><h2>Пригласить пациента</h2><p>Пациент получит письмо с кнопкой принятия приглашения. Ссылка действует 48 часов.</p>
    <Form submit="Отправить приглашение" successMessage="Приглашение отправлено на почту" action={async data => { await api('/invitations', { email: text(data, 'email') }); reload() }}><label>Email пациента<input name="email" type="email" required /></label></Form>
  </section>
}

export function DrugCatalog() {
  const [drugs, setDrugs] = useState<Drug[] | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => { let active = true; api<Drug[]>('/drugs').then(data => { if (active) { setDrugs(data); setError('') } }).catch(e => { if (active) setError(e.message) }); return () => { active = false } }, [revision])
  const reload = () => setRevision(r => r + 1)
  return <section className="card"><h2>Справочник лекарств</h2><p className="notice">Информация вводится из действующей инструкции ГРЛС и проверяется врачом вручную. Приложение не проверяет документ и регистрацию автоматически.</p>
    {error && <p className="error" role="alert">{error}<button onClick={reload}>Повторить</button></p>}
    {!drugs && !error && <p role="status">Загрузка…</p>}{drugs?.length === 0 && <Empty />}
    {drugs?.map(drug => <details key={drug.id}><summary>{drug.name} · {drug.status === 'verified' ? 'Проверено врачом' : 'Ожидает проверки'}</summary>
      <dl><dt>Показания</dt><dd>{drug.indications || 'Не заполнены'}</dd><dt>Противопоказания</dt><dd>{drug.contraindications || 'Не заполнены'}</dd><dt>Режимы дозирования из инструкции</dt><dd>{drug.dosing || 'Не заполнены'}</dd></dl>
      {drug.source_url && <><a href={drug.source_url} target="_blank" rel="noreferrer">Открыть запись ГРЛС</a><p>Регистрационный номер: {drug.registration_number}</p></>}
      {drug.status !== 'verified' && drug.source_url && <Form submit="Подтвердить ручную проверку" action={async data => {
        if (!window.confirm('Вы проверили действующую инструкцию, регистрацию в РФ и все внесённые сведения?')) throw new Error('Проверка отменена')
        await api(`/drugs/${drug.id}/verify`, { registered_rf: true, comment: text(data, 'comment') }); reload()
      }}><label>Основание проверки<textarea name="comment" required maxLength={5000} /></label></Form>}
    </details>)}
    <details><summary>Добавить сведения из ГРЛС</summary><Form submit="Сохранить для проверки" reset action={async data => {
      await api('/drugs', Object.fromEntries(['name', 'indications', 'contraindications', 'dosing', 'source_url', 'registration_number'].map(key => [key, text(data, key)]))); reload()
    }}>{[['name', 'Название'], ['registration_number', 'Регистрационный номер'], ['source_url', 'HTTPS-ссылка на конкретную запись ГРЛС']].map(([name, label]) => <label key={name}>{label}<input name={name} required maxLength={name === 'source_url' ? 2048 : name === 'registration_number' ? 100 : 255} type={name === 'source_url' ? 'url' : 'text'} /></label>)}
      {[['indications', 'Показания'], ['contraindications', 'Противопоказания'], ['dosing', 'Режимы дозирования из инструкции']].map(([name, label]) => <label key={name}>{label}<textarea name={name} required maxLength={5000} /></label>)}
    </Form></details>
  </section>
}
