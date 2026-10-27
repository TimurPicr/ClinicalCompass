import test from "node:test";
import assert from "node:assert/strict";
import { date, localInput, zonedIso } from "../src/api/time.js";

test("Moscow wall time is saved in UTC", () => {
  assert.equal(
    zonedIso("2026-10-23T09:00", "Europe/Moscow"),
    "2026-10-23T06:00:00.000Z",
  );
  assert.equal(
    localInput("2026-10-23T23:30:00Z", "Europe/Moscow"),
    "2026-10-24T02:30",
  );
});

test("New York conversion uses the offset for the entered date", () => {
  assert.equal(
    zonedIso("2026-01-15T09:00", "America/New_York"),
    "2026-01-15T14:00:00.000Z",
  );
  assert.equal(
    zonedIso("2026-07-15T09:00", "America/New_York"),
    "2026-07-15T13:00:00.000Z",
  );
});

test("Nonexistent daylight saving wall times are rejected", () => {
  assert.throws(
    () => zonedIso("2026-03-08T02:30", "America/New_York"),
    /перевода часов/,
  );
  assert.throws(
    () => zonedIso("2026-03-29T02:30", "Europe/Berlin"),
    /перевода часов/,
  );
});

test("Ambiguous autumn wall time selects a deterministic occurrence", () => {
  // The first occurrence, 01:30 EDT, is chosen consistently.
  assert.equal(
    zonedIso("2026-11-01T01:30", "America/New_York"),
    "2026-11-01T05:30:00.000Z",
  );
});

test("Calendar dates are independent of the account time zone", () => {
  assert.equal(
    date("2026-10-23", "America/Los_Angeles", false),
    date("2026-10-23", "Asia/Tokyo", false),
  );
  assert.match(date("2026-10-23", "America/Los_Angeles", false), /^23 /);
});
