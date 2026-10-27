import { useEffect, useState } from 'react'
import { api } from '../api'
import type { DiaryEntry, Question } from '../types'
import { Empty, Form } from './Form'
import { text, today } from '../format'

function monthRange(month: string) {
  const [year, number] = month.split('-').map(Number)
  const days = new Date(year, number, 0).getDate()
  return { year, number, days, start: `${month}-01`, end: `${month}-${days}`, offset: (new Date(year, number - 1, 1).getDay() + 6) % 7 }
}

export function DiaryCalendar({ patientId, readOnly = false, onSaved, refreshKey = 0 }: { patientId: number; readOnly?: boolean; onSaved?: () => void; refreshKey?: number }) {
  const [month, setMonth] = useState(() => today().slice(0, 7))
  const [selected, setSelected] = useState(today)
  const [loaded, setLoaded] = useState('')
  const [entries, setEntries] = useState<DiaryEntry[]>([])
  const [questions, setQuestions] = useState<Question[]>([])
  const [error, setError] = useState('')
  const [savedDate, setSavedDate] = useState('')
  const [attempt, setAttempt] = useState(0)
  const range = monthRange(month)
  useEffect(() => {
    let active = true
    const { start, end } = monthRange(month)
    Promise.all([api<DiaryEntry[]>(`/patients/${patientId}/diary?start=${start}&end=${end}`), api<{ questions: Question[] }>('/questionnaires/demo')])
      .then(([entries, questionnaire]) => { if (active) { setEntries(entries); setQuestions(questionnaire.questions); setLoaded(month); setError('') } })
      .catch(error => { if (active) setError(error.message) })
    return () => { active = false }
  }, [patientId, month, attempt, refreshKey])
  function changeMonth(delta: number) {
    const date = new Date(range.year, range.number - 1 + delta, 1)
    const next = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
    setSavedDate(''); setMonth(next); setSelected(next === today().slice(0, 7) ? today() : `${next}-01`); setError('')
  }
  const visible = loaded === month ? entries.filter(entry => entry.entry_date.startsWith(month)) : []
  const entry = visible.find(entry => entry.entry_date === selected)
  return <><section className="card"><div className="section-head"><h2>{readOnly ? 'Дневник пациента' : 'Мой дневник'}</h2><div className="row"><button className="secondary" onClick={() => changeMonth(-1)} aria-label="Предыдущий месяц">←</button><strong>{new Date(range.year, range.number - 1).toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' })}</strong><button className="secondary" disabled={month >= today().slice(0, 7)} onClick={() => changeMonth(1)} aria-label="Следующий месяц">→</button></div></div>
    {error && <p role="alert" className="error">{error}<button onClick={() => setAttempt(a => a + 1)}>Повторить</button></p>}
    {loaded !== month && !error && <p role="status">Загрузка дневника…</p>}
    <div className="calendar" aria-label="Календарь записей"><div className="calendar-week">{['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(day => <span key={day}>{day}</span>)}</div><div className="calendar-days">
      {Array.from({ length: range.offset }, (_, i) => <span key={`blank-${i}`} />)}
      {Array.from({ length: range.days }, (_, i) => { const day = `${month}-${String(i + 1).padStart(2, '0')}`; const filled = visible.some(entry => entry.entry_date === day); return <button key={day} disabled={day > today()} aria-label={`${day}${filled ? ', есть запись' : ''}`} aria-pressed={selected === day} className={filled ? 'filled' : ''} onClick={() => { setSavedDate(''); setSelected(day) }}>{i + 1}{filled && <span className="calendar-dot" />}</button> })}
    </div></div>
    {savedDate === selected && <p role="status" className="success">Запись сохранена</p>}
    <h3>{new Date(`${selected}T12:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })}</h3>
    {loaded === month && (readOnly ? (entry ? <><dl>{questions.map((question, i) => <div key={question.id}><dt>{question.text}</dt><dd>{question.options[entry.answers[i]]}</dd></div>)}</dl><h3>Запись пациента</h3><p className="prewrap">{entry.text || 'Без комментария'}</p></> : <Empty>За этот день записи нет.</Empty>) : <Form key={`${selected}:${entry?.result_id ?? 'new'}:${entry?.updated_at ?? ''}`} submit={entry ? 'Сохранить изменения' : 'Сохранить запись'} action={async data => {
      const answers = questions.map(question => Number(text(data, `q-${question.id}`)))
      const saved = await api<DiaryEntry>(`/patients/${patientId}/diary`, { entry_date: selected, answers, text: text(data, 'diary') })
      setEntries(current => [...current.filter(entry => entry.entry_date !== selected), saved].sort((a, b) => a.entry_date.localeCompare(b.entry_date)))
      setSavedDate(selected)
      onSaved?.()
    }}>{questions.map((question, i) => <fieldset className="question" key={question.id}><legend>{question.text}</legend>{question.options.map((option, value) => <label className="option" key={value}><input type="radio" name={`q-${question.id}`} value={value} required defaultChecked={entry?.answers[i] === value} />{option}</label>)}</fieldset>)}<label>Мои заметки<textarea name="diary" defaultValue={entry?.text ?? ''} rows={5} maxLength={10000} placeholder="Как прошёл день? Что повлияло на ваше самочувствие?" /></label></Form>)}
  </section><DiaryChart entries={visible} /></>
}

function DiaryChart({ entries }: { entries: DiaryEntry[] }) {
  const groups = new Map<string, DiaryEntry[]>()
  for (const entry of entries) { const key = `${entry.scale_code}:${entry.scale_version}`; groups.set(key, [...(groups.get(key) ?? []), entry]) }
  return <section className="card"><h2>Динамика за месяц</h2>{entries.length === 0 && <Empty>График появится после первой записи в дневнике.</Empty>}
    {[...groups].map(([key, entries]) => { const max = Math.max(...entries.map(entry => entry.max_score), 1); const first = Date.parse(entries[0].entry_date), last = Date.parse(entries.at(-1)!.entry_date)
      const points = entries.map(entry => ({ ...entry, x: entries.length === 1 ? 300 : 40 + (Date.parse(entry.entry_date) - first) / (last - first) * 520, y: 170 - entry.score / max * 140 }))
      return <figure key={key}><figcaption>Частота отмеченных трудностей</figcaption><svg viewBox="0 0 600 215" role="img" aria-label="Динамика по записям дневника"><path d="M40 20V170H570" fill="none" stroke="#a8b6b2" /><text x="10" y="30">{max}</text><text x="15" y="175">0</text><polyline points={points.map(point => `${point.x},${point.y}`).join(' ')} fill="none" stroke="#247465" strokeWidth="3" />{points.map(point => <circle key={point.id} cx={point.x} cy={point.y} r="5" fill="#247465"><title>{point.entry_date}: {point.score} из {point.max_score}{point.text ? ` · ${point.text}` : ''}</title></circle>)}<text x="40" y="200" fontSize="12">{entries[0].entry_date}</text><text x="560" y="200" fontSize="12" textAnchor="end">{entries.length > 1 ? entries.at(-1)!.entry_date : ''}</text></svg></figure>
    })}
  </section>
}
