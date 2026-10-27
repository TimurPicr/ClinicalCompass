import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from './api'
import { AuthPage } from './pages/AuthPage'
import { Questionnaires } from './components/Questionnaires'
import { Chat } from './components/Chat'
import { Treatment } from './components/Treatment'
import { Alerts } from './components/Alerts'
import { Monitoring } from './components/Monitoring'
import { Dashboard } from './pages/Dashboard'
import type { Plan, Scale, User } from './types'

vi.mock('./api', () => ({ api: vi.fn() }))
const mockedApi = vi.mocked(api)
const patient: User = { id: 1, full_name: 'Тестовый пациент', email: 'patient@example.com', role: 'patient', doctor_id: 2 }
const doctor: User = { ...patient, id: 2, full_name: 'Тестовый врач', role: 'doctor', doctor_id: null }
const plan: Plan = { id: 1, title: 'Наблюдение', instructions: 'Учебные инструкции', version: 1, status: 'active', confirmed_at: '2026-01-01T12:00:00Z', prescriptions: [] }
const scale: Scale = { id: 1, code: 'demo', version: '1', title: 'Учебный опрос', active: true, review_status: 'demo_only', validation_source: null, license: null,
  questions: [1, 2, 3, 4, 5].map(id => ({ id, text: `Вопрос ${id}`, options: ['Никогда', 'Иногда', 'Часто', 'Всегда'] })) }
beforeEach(() => { mockedApi.mockReset() })

it('выполняет вход', async () => {
  mockedApi.mockResolvedValue(patient)
  const onLogin = vi.fn(), user = userEvent.setup()
  render(<AuthPage onLogin={onLogin} />)
  await user.type(screen.getByLabelText('Email'), patient.email)
  await user.type(screen.getByLabelText('Пароль'), 'synthetic-password')
  await user.click(screen.getByRole('button', { name: 'Войти' }))
  await waitFor(() => expect(onLogin).toHaveBeenCalledWith(patient))
  expect(mockedApi).toHaveBeenCalledWith('/auth/login', { email: patient.email, password: 'synthetic-password' })
})

it('регистрирует пациента и затем выполняет вход', async () => {
  mockedApi.mockResolvedValue(patient)
  const user = userEvent.setup()
  render(<AuthPage onLogin={vi.fn()} />)
  await user.click(screen.getByText('Создать аккаунт пациента'))
  await user.type(screen.getByLabelText('Имя и фамилия'), patient.full_name)
  await user.type(screen.getByLabelText('Email'), patient.email)
  await user.type(screen.getByLabelText('Пароль'), 'synthetic-password')
  await user.click(screen.getByRole('button', { name: 'Зарегистрироваться и войти' }))
  await waitFor(() => expect(mockedApi).toHaveBeenCalledTimes(2))
  expect(mockedApi.mock.calls[0]).toEqual(['/auth/register', { email: patient.email, password: 'synthetic-password', full_name: patient.full_name }])
})

it('показывает ошибку входа', async () => {
  mockedApi.mockRejectedValue(new Error('Неверный email или пароль'))
  const user = userEvent.setup()
  render(<AuthPage onLogin={vi.fn()} />)
  await user.type(screen.getByLabelText('Email'), patient.email)
  await user.type(screen.getByLabelText('Пароль'), 'wrong')
  await user.click(screen.getByRole('button', { name: 'Войти' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Неверный email')
  expect((screen.getByRole('button', { name: 'Войти' }) as HTMLButtonElement).disabled).toBe(false)
})

it('отправляет ответы и показывает результат; клиническая шкала неактивна', async () => {
  mockedApi.mockResolvedValue({ score: 5, max_score: 15, note: 'Учебный результат' })
  const reload = vi.fn(), user = userEvent.setup()
  render(<Questionnaires scales={[scale, { ...scale, id: 2, active: false, title: 'PHQ-9' }]} reload={reload} />)
  for (const radio of screen.getAllByLabelText('Иногда')) await user.click(radio)
  await user.click(screen.getByRole('button', { name: 'Завершить опрос' }))
  await waitFor(() => expect(reload).toHaveBeenCalled())
  expect(mockedApi).toHaveBeenCalledWith('/scales/demo/1/submit', { answers: [1, 1, 1, 1, 1] })
  expect(screen.getByText(/Сохранено: 5/).textContent).toContain('Учебный результат')
  expect(screen.getAllByRole('button', { name: 'Завершить опрос' })).toHaveLength(1)
})

it('сохраняет сообщение при ошибке и очищает после успеха', async () => {
  let attempts = 0
  mockedApi.mockImplementation(async (path, body) => {
    if (body === undefined) return []
    if (path.endsWith('/messages') && ++attempts === 1) throw new Error('Нет соединения')
    return { id: 1, sender_id: patient.id, text: 'Учебный вопрос', created_at: '2026-01-01T12:00:00Z' }
  })
  const user = userEvent.setup()
  render(<Chat messages={[]} patientId={1} user={patient} />)
  await user.type(screen.getByLabelText('Сообщение'), 'Учебный вопрос')
  await user.click(screen.getByRole('button', { name: 'Отправить' }))
  await screen.findByRole('alert')
  expect((screen.getByLabelText('Сообщение') as HTMLTextAreaElement).value).toBe('Учебный вопрос')
  await user.click(screen.getByRole('button', { name: 'Отправить' }))
  await waitFor(() => expect((screen.getByLabelText('Сообщение') as HTMLTextAreaElement).value).toBe(''))
  expect(screen.getByText('Учебный вопрос')).not.toBeNull()
})

it('пациент не видит управление планом', () => {
  render(<Treatment plans={[plan]} drugs={[]} user={patient} patientId={1} reload={vi.fn()} />)
  expect(screen.queryByText('Подтвердить план')).toBeNull()
  expect(screen.queryByText('Создать черновик плана')).toBeNull()
  expect(screen.getByText('Учебные инструкции')).not.toBeNull()
})

it('врач отдельно подтверждает план', async () => {
  mockedApi.mockResolvedValue({})
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const user = userEvent.setup()
  render(<Treatment plans={[{ ...plan, status: 'draft', confirmed_at: null }]} drugs={[]} user={doctor} patientId={1} reload={vi.fn()} />)
  await user.click(screen.getByText('Подтвердить план'))
  await waitFor(() => expect(mockedApi).toHaveBeenCalledWith('/patients/1/plans/1/confirm', {}))
})

it('повторяет запрос связи с прежним ключом при сетевой ошибке', async () => {
  mockedApi.mockRejectedValueOnce(new Error('Ошибка сети')).mockResolvedValueOnce({})
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const user = userEvent.setup()
  render(<Alerts alerts={[]} user={patient} reload={vi.fn()} />)
  await user.click(screen.getByText('Запросить срочную связь'))
  await screen.findByRole('alert')
  await user.click(screen.getByText('Запросить срочную связь'))
  await waitFor(() => expect(mockedApi).toHaveBeenCalledTimes(2))
  expect(mockedApi.mock.calls[0]).toEqual(mockedApi.mock.calls[1])
})

it('разделяет графики несовместимых версий', () => {
  const point = { result_id: 1, at: '2026-01-01T12:00:00Z', score: 3, max_score: 15 }
  render(<Monitoring results={[]} scales={[scale]} series={[{ scale: 'demo', version: '1', points: [point] }, { scale: 'demo', version: '2', points: [point] }]} onFilter={vi.fn()} />)
  expect(screen.getAllByRole('img')).toHaveLength(2)
  expect(screen.getByRole('img', { name: 'Динамика demo, версия 2' })).not.toBeNull()
})

it('врач видит список пациентов', async () => {
  mockedApi.mockImplementation(async path => path === '/patients' ? [patient] : [])
  render(<Dashboard user={doctor} />)
  expect(await screen.findByText(patient.email)).not.toBeNull()
  expect(screen.getByRole('button', { name: /Открыть карточку/ })).not.toBeNull()
})
