import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { Message, User } from '../types'
import { Empty, Form } from './Form'
import { text, dateTime } from '../format'

export function Chat({ messages: initial, patientId, user }: { messages: Message[]; patientId: number; user: User; reload?: () => void }) {
  const [messages, setMessages] = useState(initial)
  const [error, setError] = useState('')
  const [connected, setConnected] = useState(false)
  const lastId = useRef(Math.max(0, ...initial.map(message => message.id)))
  const list = useRef<HTMLDivElement>(null)
  const nearBottom = useRef(true)
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    async function poll() {
      let retry = true
      try {
        const incoming = await api<Message[]>(`/patients/${patientId}/messages?after_id=${lastId.current}`, undefined, { signal: controller.signal })
        if (!active) return
        if (incoming.length) {
          lastId.current = Math.max(lastId.current, ...incoming.map(message => message.id))
          setMessages(current => [...new Map([...current, ...incoming].map(message => [message.id, message])).values()].sort((a, b) => a.id - b.id))
        }
        setConnected(true); setError('')
      } catch (error) {
        if (!active) return
        setConnected(false)
        retry = !(error instanceof ApiError && [401, 403, 404].includes(error.status))
        setError(retry ? 'Нет соединения. Пробуем подключиться снова…' : 'Переписка недоступна. Войдите в систему повторно.')
      } finally {
        if (active && retry) timer = setTimeout(poll, 2000)
      }
    }
    void poll()
    return () => { active = false; controller.abort(); clearTimeout(timer) }
  }, [patientId])
  useEffect(() => { if (nearBottom.current && list.current) list.current.scrollTop = list.current.scrollHeight }, [messages.length])
  return <section className="card chat"><div className="section-head"><h2>Чат с {user.role === 'patient' ? 'врачом' : 'пациентом'}</h2><small role="status">{connected ? 'На связи' : 'Подключение…'}</small></div>
    <p className="muted">Не для экстренной помощи.</p>
    {error && <p role="status" className="error">{error}</p>}
    <div className="messages" role="log" aria-label="Сообщения" aria-live="polite" ref={list} onScroll={() => { if (list.current) nearBottom.current = list.current.scrollHeight - list.current.scrollTop - list.current.clientHeight < 80 }}>
      {!messages.length && <Empty>Напишите первое сообщение</Empty>}
      {messages.map(message => <article key={message.id} className={`message ${message.sender_id === user.id ? 'mine' : ''}`}><strong>{message.sender_id === user.id ? 'Вы' : user.role === 'patient' ? 'Врач' : 'Пациент'}</strong><p>{message.text}</p><small>{dateTime(message.created_at)}</small></article>)}
    </div>
    <Form submit="Отправить" reset action={async data => {
      const sent = await api<Message>(`/patients/${patientId}/messages`, { text: text(data, 'message') })
      nearBottom.current = true
      setMessages(current => [...new Map([...current, sent].map(message => [message.id, message])).values()].sort((a, b) => a.id - b.id))
      // Only polling advances the cursor: a simultaneous incoming message must not be skipped.
    }}><label>Сообщение<textarea name="message" maxLength={5000} required rows={2} placeholder="Напишите сообщение…" /></label></Form>
  </section>
}
