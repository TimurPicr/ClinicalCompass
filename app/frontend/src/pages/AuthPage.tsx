import { useState } from 'react'
import { api } from '../api'
import type { User } from '../types'
import { Form } from '../components/Form'
import { text } from '../format'

export function AuthPage({ onLogin, invitation = false }: { onLogin: (user: User) => void; invitation?: boolean }) {
  const [register, setRegister] = useState(false)
  return <main className="auth"><div className="brand">✦ Clinical Compass</div>
    <h1>Наблюдение с заботой</h1><p>Ваше самочувствие и связь с лечащим врачом в одном месте.</p>
    {invitation && <p className="notice">Войдите или зарегистрируйтесь с email из письма, чтобы принять приглашение врача.</p>}
    <section className="card"><h2>{register ? 'Регистрация пациента' : 'Вход в кабинет'}</h2>
      <Form key={String(register)} submit={register ? 'Зарегистрироваться и войти' : 'Войти'} action={async data => {
        const credentials = { email: text(data, 'email'), password: String(data.get('password')) }
        if (register) await api('/auth/register', { ...credentials, full_name: text(data, 'full_name') })
        onLogin(await api<User>('/auth/login', credentials))
      }}>
        {register && <label>Имя и фамилия<input name="full_name" autoComplete="name" maxLength={255} required /></label>}
        <label>Email<input name="email" type="email" autoComplete="email" required /></label>
        <label>Пароль<input name="password" type="password" minLength={register ? 12 : 1} maxLength={128} autoComplete={register ? 'new-password' : 'current-password'} required /></label>
      </Form>
      <button className="secondary" onClick={() => setRegister(!register)}>{register ? 'У меня уже есть аккаунт' : 'Создать аккаунт пациента'}</button>
      
    </section>
  </main>
}
