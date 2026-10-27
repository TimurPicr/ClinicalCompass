export const CHAT_TEXT_LIMIT = 5000;
export const CHAT_FILE_LIMIT = 15 * 1024 * 1024;

// A stalled read must release the room's in-flight flag. Each operation owns
// its deadline and controller; room cleanup cancels every linked operation.
export async function withChatDeadline(operation, signal, timeoutMs = 15000) {
  const controller = new AbortController();
  const aborted = () => new DOMException("Запрос отменён", "AbortError");
  if (signal?.aborted) throw aborted();
  let rejectCancellation;
  const cancellation = new Promise((resolve, reject) => { rejectCancellation = reject; });
  const cancel = () => { controller.abort(); rejectCancellation(aborted()); };
  signal?.addEventListener("abort", cancel, { once: true });
  let timer;
  const deadline = new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new Error("Сервер отвечает слишком долго. Повторите попытку."));
    }, timeoutMs);
  });
  const request = Promise.resolve().then(() => {
    if (controller.signal.aborted) throw aborted();
    return operation(controller.signal);
  });
  try {
    return await Promise.race([request, cancellation, deadline]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

// An older history response must not remove a message already acknowledged by
// POST or received live. Room ownership is checked even for cached messages.
export function mergeChatMessages(current, incoming, patientId) {
  const roomId = Number(patientId);
  const messages = new Map();
  for (const message of [...(current || []), ...(incoming || [])]) {
    if (!message || Number(message.patient_id) !== roomId || !Number.isSafeInteger(message.id)) continue;
    messages.set(message.id, message);
  }
  return [...messages.values()].sort((a, b) => a.id - b.id);
}

export function clearSubmittedDraft(current, submitted) {
  return {
    text: current.text === submitted.text ? "" : current.text,
    file: current.file === submitted.file ? null : current.file,
  };
}

export function shouldSendOnEnter(event) {
  return event.key === "Enter" && !event.shiftKey && !event.isComposing
    && !event.nativeEvent?.isComposing && event.keyCode !== 229
    && event.nativeEvent?.keyCode !== 229;
}
