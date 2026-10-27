import { useState } from 'react'
import type { ReactNode, SubmitEvent } from 'react'

interface Props { children: ReactNode; submit: string; action: (data: FormData) => Promise<void>; reset?: boolean; disabled?: boolean; successMessage?: string }
export function Form({ children, submit, action, reset = false, disabled = false, successMessage = 'Сохранено' }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  async function send(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    if (busy) return
    setBusy(true); setError(''); setSuccess(false)
    try { await action(new FormData(form)); if (reset) form.reset(); setSuccess(true) }
    catch (error) { setError(error instanceof Error ? error.message : 'Не удалось выполнить запрос') }
    finally { setBusy(false) }
  }
  return <form onSubmit={send}><fieldset disabled={busy || disabled} className="form-fields">{children}
    <button type="submit">{busy ? 'Отправка…' : submit}</button></fieldset>
    {error && <p role="alert" className="error">{error}</p>}
    {success && <p role="status" className="success">{successMessage}</p>}
  </form>
}
export function Empty({ children = 'Пока нет записей' }: { children?: ReactNode }) { return <p className="empty">{children}</p> }
