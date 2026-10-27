import type { Result, Series, Scale } from '../types'
import { Empty, Form } from './Form'
import { dateTime, text } from '../format'

export function Monitoring({ results, series, scales, onFilter }: { results: Result[]; series: Series[]; scales: Scale[]; onFilter: (query: string) => Promise<void> }) {
  return <><section className="card"><h2>Динамика самочувствия</h2>
    <Form submit="Применить фильтр" action={async data => {
      const query = new URLSearchParams()
      if (text(data, 'scale')) { const [code, version] = text(data, 'scale').split('|'); query.set('scale', code); query.set('version', version) }
      if (text(data, 'start')) query.set('start', new Date(`${text(data, 'start')}T00:00:00`).toISOString())
      if (text(data, 'end')) query.set('end', new Date(`${text(data, 'end')}T23:59:59.999`).toISOString())
      await onFilter(query.toString())
    }}><div className="row"><label>Шкала и версия<select name="scale"><option value="">Все (раздельные графики)</option>{scales.map(s => <option key={s.id} value={`${s.code}|${s.version}`}>{s.code} · v{s.version}</option>)}</select></label>
      <label>С даты<input name="start" type="date" /></label><label>По дату<input name="end" type="date" /></label></div></Form>
    {!series.length && <Empty>Пройдите первый опрос, чтобы появилась динамика.</Empty>}
    {series.map(group => {
      const first = new Date(group.points[0].at).getTime(), last = new Date(group.points.at(-1)!.at).getTime()
      const max = Math.max(...group.points.map(p => p.max_score), 1)
      const points = group.points.map((p, i) => ({ ...p, x: group.points.length === 1 ? 300 : first === last ? 40 + i * 520 / (group.points.length - 1) : 40 + (new Date(p.at).getTime() - first) * 520 / (last - first), y: 175 - p.score * 150 / max }))
      return <figure key={`${group.scale}:${group.version}`}><figcaption>{group.scale} · версия {group.version}</figcaption>
        <svg viewBox="0 0 600 220" role="img" aria-label={`Динамика ${group.scale}, версия ${group.version}`}>
          <path d="M40 20V175H570" fill="none" stroke="#a8b6b2" /><text x="10" y="30">{max}</text><text x="15" y="180">0</text>
          <polyline points={points.map(p => `${p.x},${p.y}`).join(' ')} fill="none" stroke="#247465" strokeWidth="3" />
          {points.map(p => <circle key={p.result_id} cx={p.x} cy={p.y} r="5" fill="#247465"><title>{dateTime(p.at)}: {p.score} / {p.max_score}</title></circle>)}
          <text x="40" y="205" fontSize="12">{dateTime(group.points[0].at)}</text><text x="560" y="205" fontSize="12" textAnchor="end">{group.points.length > 1 ? dateTime(group.points.at(-1)!.at) : ''}</text>
        </svg><p className="muted">Учебные баллы, без диагностической интерпретации.</p></figure>
    })}
  </section><section className="card"><h2>История обследований</h2>{!results.length ? <Empty /> : <div className="table-wrap"><table><thead><tr><th>Дата</th><th>Шкала</th><th>Версия</th><th>Баллы</th></tr></thead><tbody>{[...results].reverse().map(r => <tr key={r.id}><td>{dateTime(r.created_at)}</td><td>{r.scale_code}</td><td>{r.scale_version}</td><td>{r.score} / {r.max_score}</td></tr>)}</tbody></table></div>}</section></>
}
