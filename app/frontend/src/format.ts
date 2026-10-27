export const text = (data: FormData, key: string) => String(data.get(key) ?? '').trim()
export const dateTime = (value: string) => new Date(value).toLocaleString('ru-RU')
export const today = () => {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  const part = (type: string) => parts.find(part => part.type === type)!.value
  return `${part('year')}-${part('month')}-${part('day')}`
}
