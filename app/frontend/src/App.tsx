import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from './api'
import type { User } from './types'
import { AuthPage } from './pages/AuthPage'
import { Dashboard } from './pages/Dashboard'
import { InvitationAcceptance } from './components/InvitationAcceptance'
import './App.css'

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [invitation, setInvitation] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('invite') ?? '')
  const clearInvitation = useCallback(() => { setInvitation(''); window.history.replaceState(null, '', window.location.pathname + window.location.search) }, [])
  const acceptInvitation = useCallback((user: User) => { setUser(user); clearInvitation() }, [clearInvitation])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const updateInvitation = () => setInvitation(new URLSearchParams(window.location.hash.slice(1)).get('invite') ?? '')
    window.addEventListener('hashchange', updateInvitation)
    return () => window.removeEventListener('hashchange', updateInvitation)
  }, [])
  useEffect(() => {
    let active = true
    api<User>('/auth/me').then(user => { if (active) setUser(user) }).catch(e => {
      if (active && !(e instanceof ApiError && e.status === 401)) setError(e.message)
    }).finally(() => { if (active) setLoading(false) })
    const expired = () => { setUser(null); setError('Сессия завершена. Войдите снова.') }
    window.addEventListener('session-expired', expired)
    return () => { active = false; window.removeEventListener('session-expired', expired) }
  }, [revision])
  if (loading) return <main className="auth" role="status">Загрузка Clinical Compass…</main>
  if (!user) return <>{error && <div role="alert" className="banner error">{error}<button onClick={() => { setError(''); setLoading(true); setRevision(r => r + 1) }}>Повторить</button></div>}<AuthPage invitation={!!invitation} onLogin={user => { setError(''); setUser(user) }} /></>
  return <><header><a href="#" className="brand">✦ Clinical Compass</a><span>{user.full_name} · {user.role === 'doctor' ? 'Врач' : 'Пациент'}</span><button className="secondary" onClick={async () => { try { await api('/auth/logout', {}); setUser(null); setError('') } catch (e) { setError(e instanceof Error ? e.message : 'Ошибка выхода') } }}>Выйти</button></header>
    <main className="container">
      {error && <p role="alert" className="error">{error}</p>}{invitation ? <InvitationAcceptance token={invitation} onAccepted={acceptInvitation} onCancel={clearInvitation} /> : <Dashboard user={user} />}
    </main><footer>Clinical Compass</footer>
  </>
}
