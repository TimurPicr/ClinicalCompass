import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from './api'
import App from './App'
import { today } from './format'
import { DiaryCalendar } from './components/DiaryCalendar'
import { InvitationAcceptance } from './components/InvitationAcceptance'
import { DoctorTools } from './components/DoctorTools'
import { Chat } from './components/Chat'
import type { DiaryEntry, User } from './types'

vi.mock('./api', async importOriginal => ({ ...await importOriginal<typeof import('./api')>(), api: vi.fn() }))
const mockApi = vi.mocked(api)
const patient: User = { id: 1, full_name: 'Пациент', email: 'test@example.com', role: 'patient', doctor_id: 2 }
const questions = Array.from({ length: 5 }, (_, i) => ({ id: i + 1, text: `Вопрос ${i + 1}`, options: ['Нет', 'Да'] }))
const entry: DiaryEntry = { id: 1, entry_date: today(), text: 'Запись пациента', answers: [1, 1, 1, 1, 1], score: 5, max_score: 15, scale_code: 'demo', scale_version: '1', result_id: 1, updated_at: '2026-01-01T00:00:00Z' }
beforeEach(() => { mockApi.mockReset() })
afterEach(() => { vi.useRealTimers(); window.history.replaceState(null, '', '/') })

it('сохраняет фиксированные ответы и свободную запись за выбранный день', async () => {
  mockApi.mockImplementation(async (path, body) => {
    if (path === '/questionnaires/demo') return { questions }
    if (body !== undefined) return entry
    return []
  })
  const user = userEvent.setup()
  render(<DiaryCalendar patientId={1} />)
  await screen.findByLabelText('Мои заметки')
  for (const radio of screen.getAllByLabelText('Да')) await user.click(radio)
  await user.type(screen.getByLabelText('Мои заметки'), 'Запись пациента')
  await user.click(screen.getByRole('button', { name: 'Сохранить запись' }))
  await waitFor(() => expect(mockApi).toHaveBeenCalledWith('/patients/1/diary', { entry_date: today(), answers: [1, 1, 1, 1, 1], text: 'Запись пациента' }))
  expect(await screen.findByRole('img', { name: 'Динамика по записям дневника' })).not.toBeNull()
  expect(screen.getByLabelText(`${today()}, есть запись`)).not.toBeNull()
})

it('врач читает дневник без возможности редактирования', async () => {
  mockApi.mockImplementation(async path => path === '/questionnaires/demo' ? { questions } : [entry])
  render(<DiaryCalendar patientId={1} readOnly />)
  expect(await screen.findByText('Запись пациента', { selector: 'p' })).not.toBeNull()
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.queryByText('Сохранить изменения')).toBeNull()
})

it('принимает ссылку из письма автоматически после авторизации', async () => {
  mockApi.mockResolvedValue(patient)
  const accepted = vi.fn()
  render(<InvitationAcceptance token={'t'.repeat(43)} onAccepted={accepted} onCancel={vi.fn()} />)
  await waitFor(() => expect(accepted).toHaveBeenCalledWith(patient))
  expect(mockApi).toHaveBeenCalledWith('/invitations/accept', { token: 't'.repeat(43) })
})

it('врач отправляет приглашение без ручной передачи кода', async () => {
  mockApi.mockResolvedValue({ delivery_status: 'sent' })
  const user = userEvent.setup()
  render(<DoctorTools reload={vi.fn()} />)
  await user.type(screen.getByLabelText('Email пациента'), patient.email)
  await user.click(screen.getByText('Отправить приглашение'))
  await waitFor(() => expect(mockApi).toHaveBeenCalledWith('/invitations', { email: patient.email }))
  expect(screen.queryByText('Код приглашения')).toBeNull()
})

it('чат автоматически получает новые сообщения и останавливается при закрытии', async () => {
  vi.useFakeTimers()
  mockApi.mockImplementation(async path => path.endsWith('after_id=0')
    ? [{ id: 1, sender_id: 2, text: 'Первое сообщение', created_at: '2026-01-01T12:00:00Z' }]
    : [{ id: 2, sender_id: 2, text: 'Новое сообщение', created_at: '2026-01-01T12:01:00Z' }])
  const view = render(<Chat messages={[]} patientId={1} user={patient} />)
  await act(async () => { await Promise.resolve() })
  expect(screen.getByText('Первое сообщение')).not.toBeNull()
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  expect(screen.getByText('Новое сообщение')).not.toBeNull()
  expect(mockApi.mock.calls[1][0]).toBe('/patients/1/messages?after_id=1')
  view.unmount()
  const count = mockApi.mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(mockApi.mock.calls).toHaveLength(count)
})

it('отправка сообщения не пропускает одновременное сообщение врача', async () => {
  vi.useFakeTimers()
  const sent = { id: 3, sender_id: patient.id, text: 'Мой ответ', created_at: '2026-01-01T12:01:00Z' }
  const incoming = { id: 2, sender_id: 2, text: 'Вопрос врача', created_at: '2026-01-01T12:00:00Z' }
  let polls = 0
  mockApi.mockImplementation(async (_path, body) => body === undefined ? (++polls === 1 ? [] : [incoming, sent]) : sent)
  render(<Chat messages={[]} patientId={1} user={patient} />)
  await act(async () => { await Promise.resolve() })
  await act(async () => {
    fireEvent.change(screen.getByLabelText('Сообщение'), { target: { value: sent.text } })
    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))
  })
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  expect(screen.getByText(incoming.text)).not.toBeNull()
  expect(screen.getAllByText(sent.text)).toHaveLength(1)
  expect(mockApi.mock.calls.filter(([, body]) => body === undefined)[1][0]).toBe('/patients/1/messages?after_id=0')
})

it('открытие ссылки прикрепляет пациента и убирает служебные сведения из кабинета', async () => {
  const token = 't'.repeat(43)
  window.history.replaceState(null, '', `/#invite=${token}`)
  mockApi.mockImplementation(async path => {
    if (path === '/auth/me' || path === '/invitations/accept') return patient
    if (path === '/questionnaires/demo') return { questions }
    return []
  })
  render(<App />)
  await screen.findByRole('heading', { name: 'Мой дневник' })
  expect(mockApi).toHaveBeenCalledWith('/invitations/accept', { token })
  expect(window.location.hash).toBe('')
  expect(screen.queryByText(/Демонстрационная CDSS/)).toBeNull()
  expect(screen.queryByText(/Источник валидации/)).toBeNull()
  expect(screen.queryByText('Код приглашения')).toBeNull()
})

it('принимает приглашение при открытии ссылки в уже загруженной вкладке', async () => {
  const token = 't'.repeat(43)
  mockApi.mockImplementation(async path => {
    if (path === '/auth/me' || path === '/invitations/accept') return patient
    if (path === '/questionnaires/demo') return { questions }
    return []
  })
  render(<App />)
  await screen.findByRole('heading', { name: 'Мой дневник' })
  await act(async () => {
    window.history.replaceState(null, '', `/#invite=${token}`)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
  await waitFor(() => expect(mockApi).toHaveBeenCalledWith('/invitations/accept', { token }))
  expect(window.location.hash).toBe('')
  expect(await screen.findByRole('heading', { name: 'Мой дневник' })).not.toBeNull()
})
