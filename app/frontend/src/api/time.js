export function date(value, timezone = "Europe/Moscow", time = true) {
  if (!value) return "Нет данных";
  const calendarDate =
    typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    ...(time ? { hour: "2-digit", minute: "2-digit" } : { year: "numeric" }),
    timeZone: calendarDate ? "UTC" : timezone,
  }).format(parsed);
}

// datetime-local has no time zone. Convert explicit profile-zone input to UTC.
export function localInput(value = new Date(), timezone = "Europe/Moscow") {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  const p = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}
export function zonedIso(value, timezone = "Europe/Moscow") {
  const [day, clock = "00:00"] = value.split("T");
  const [y, m, d] = day.split("-").map(Number);
  const [h, n] = clock.split(":").map(Number);
  const desired = Date.UTC(y, m - 1, d, h, n);
  let guess = desired;
  for (let i = 0; i < 3; i++) {
    const observed = localInput(new Date(guess), timezone);
    const [od, ot] = observed.split("T");
    const [oy, om, odate] = od.split("-").map(Number);
    const [oh, on] = ot.split(":").map(Number);
    guess += desired - Date.UTC(oy, om - 1, odate, oh, on);
  }
  if (localInput(new Date(guess), timezone) !== value.slice(0, 16))
    throw new Error(
      "Такое местное время отсутствует из-за перевода часов. Выберите другое время.",
    );
  return new Date(guess).toISOString();
}
