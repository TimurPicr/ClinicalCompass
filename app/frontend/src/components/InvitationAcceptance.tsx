import { useEffect, useState } from 'react'
import { api } from '../api'
import type { User } from '../types'

export function InvitationAcceptance({ token, onAccepted, onCancel }: { token: string; onAccepted: (user: User) => void; onCancel: () => void }) {
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    api<User>('/invitations/accept', { token }).then(user => { if (active) onAccepted(user) }).catch(error => { if (active) setError(error.message) })
    return () => { active = false }
  }, [token, onAccepted, attempt])
  return <section className="card"><h2>Приглашение к врачу</h2>
    {error ? <><p role="alert" className="error">{error}</p><p>Войдите с тем email, на который пришло письмо.</p><button onClick={() => { setError(''); setAttempt(a => a + 1) }}>Повторить</button><button className="secondary" onClick={onCancel}>Закрыть</button></> : <p role="status">Принимаем приглашение…</p>}
  </section>
}
