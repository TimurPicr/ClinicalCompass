import assert from "node:assert/strict";
import test from "node:test";
import { CHAT_TEXT_LIMIT, withChatDeadline, mergeChatMessages, clearSubmittedDraft, shouldSendOnEnter } from "../src/api/chat.js";

const message = (id, patient_id = 17, text = `Сообщение ${id}`) => ({ id, patient_id, sender_id: 1, text });

test("late history cannot erase an acknowledged outgoing message", () => {
  const sent = message(104);
  const withAck = mergeChatMessages([message(102)], [sent], 17);
  assert.deepEqual(mergeChatMessages(withAck, [message(101), message(102), message(103)], 17).map((row) => row.id), [101, 102, 103, 104]);
});

test("HTTP acknowledgement and live broadcast appear only once", () => {
  const sent = message(104);
  const live = mergeChatMessages([message(103)], [sent], 17);
  assert.deepEqual(mergeChatMessages(live, [sent], 17), [message(103), sent]);
});

test("a switched room rejects stale history and cached messages belonging to another patient", () => {
  const nextRoom = mergeChatMessages([message(102, 17)], [message(103, 17), message(104, 18)], "18");
  assert.deepEqual(nextRoom, [message(104, 18)]);
  assert.deepEqual(mergeChatMessages(nextRoom, [message(105, 17)], 18), nextRoom);
});

test("malformed live events do not become messages or replace history", () => {
  assert.deepEqual(mergeChatMessages([message(102)], [{ type: "pong" }, { id: null, patient_id: 17 }, { id: 103, patient_id: 18 }], 17), [message(102)]);
});

test("a late send acknowledgement preserves a new text and file draft", () => {
  const firstFile = { name: "first.pdf" };
  const nextFile = { name: "next.pdf" };
  assert.deepEqual(clearSubmittedDraft({ text: "Новый черновик", file: nextFile }, { text: "Отправленное сообщение", file: firstFile }), { text: "Новый черновик", file: nextFile });
  assert.deepEqual(clearSubmittedDraft({ text: "Сообщение", file: firstFile }, { text: "Сообщение", file: firstFile }), { text: "", file: null });
  assert.deepEqual(clearSubmittedDraft({ text: "Новое сообщение", file: firstFile }, { text: "Сообщение", file: firstFile }), { text: "Новое сообщение", file: null });
});

test("Enter sends, but Shift+Enter and unfinished IME composition do not", () => {
  assert.equal(shouldSendOnEnter({ key: "Enter" }), true);
  for (const event of [{ key: "Enter", shiftKey: true }, { key: "Enter", isComposing: true }, { key: "Enter", nativeEvent: { isComposing: true } }, { key: "Enter", keyCode: 229 }, { key: "Enter", nativeEvent: { keyCode: 229 } }, { key: "a" }]) assert.equal(shouldSendOnEnter(event), false);
  assert.equal(CHAT_TEXT_LIMIT, 5000);
});

test("a hung read times out and aborts transport even if transport never settles", async () => {
  let transportSignal;
  await assert.rejects(withChatDeadline((signal) => {
    transportSignal = signal;
    return new Promise(() => {});
  }, undefined, 5), /Сервер отвечает слишком долго/);
  assert.equal(transportSignal.aborted, true);
  assert.equal(await withChatDeadline(() => Promise.resolve("fresh history")), "fresh history");
});

test("room cleanup cancels its pending read without aborting another request", async () => {
  const room = new AbortController();
  let firstSignal, secondSignal, resolveSecond;
  const first = withChatDeadline((signal) => {
    firstSignal = signal;
    return new Promise(() => {});
  }, room.signal);
  const second = withChatDeadline((signal) => {
    secondSignal = signal;
    return new Promise((resolve) => { resolveSecond = resolve; });
  });
  await Promise.resolve();
  room.abort();
  await assert.rejects(first, { name: "AbortError" });
  assert.equal(firstSignal.aborted, true);
  assert.equal(secondSignal.aborted, false);
  resolveSecond("another room");
  assert.equal(await second, "another room");
});

test("an already retired room cannot start a new transport read", async () => {
  const room = new AbortController();
  room.abort();
  let called = false;
  await assert.rejects(withChatDeadline(() => { called = true; }, room.signal), { name: "AbortError" });
  assert.equal(called, false);
});
