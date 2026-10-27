import { useState } from 'react'
import { api } from '../api'
import type { Scale, Result } from '../types'
import { Form } from './Form'
import { text } from '../format'

export function Questionnaires({ scales, reload }: { scales: Scale[]; reload: () => void }) {
  const [result, setResult] = useState<Result | null>(null)
  return <section className="card"><h2>Опросники</h2>
    {scales.map(scale => <details key={scale.id} open={scale.active}><summary>{scale.title} · v{scale.version} <span className="badge">{scale.active ? 'Учебный' : 'Неактивен'}</span></summary>
      {!scale.active ? <p>Ожидает проверки валидированной русскоязычной версии, источника и условий использования.</p> : <Form submit="Завершить опрос" action={async data => {
        const answers = scale.questions.map(q => Number(text(data, `q-${q.id}`)))
        setResult(await api<Result>(`/scales/${scale.code}/${scale.version}/submit`, { answers })); reload()
      }}>{scale.questions.map(q => <fieldset className="question" key={q.id}><legend>{q.text}</legend>{q.options.map((option, index) => <label className="option" key={option}><input required type="radio" name={`q-${q.id}`} value={index} />{option}</label>)}</fieldset>)}</Form>}
      <p className="muted">{scale.validation_source ?? 'Источник валидации не подтверждён'}</p>
    </details>)}
    {result && <p role="status" className="success">Сохранено: {result.score} / {result.max_score}. {result.note}</p>}
  </section>
}
