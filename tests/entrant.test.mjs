// Offline tests for workers/entrant.mjs on local HTML forms (node --test tests/entrant.test.mjs). Fake details only.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { classify, run } from "../workers/entrant.mjs";

const FORMS = path.join(path.dirname(new URL(import.meta.url).pathname), "fixtures", "forms");
const url = (f) => "file://" + path.join(FORMS, f);
Object.assign(process.env, {
  ENTRANT_FIRST_NAME: "Test", ENTRANT_LAST_NAME: "Person", ENTRANT_EMAIL: "test.person@example.com",
  ENTRANT_PHONE: "0400000000", ENTRANT_POSTCODE: "3000", ENTRANT_STATE: "VIC", ENTRANT_DOB: "1980-01-02",
});

function tmpLog() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "entrant-")), "log.jsonl");
}

test("field classification", () => {
  assert.equal(classify("first_name fn First name", "text"), "first");
  assert.equal(classify("email Email", "email"), "email");
  assert.equal(classify("confirm_email Confirm your email", "text"), "email");
  assert.equal(classify("Your name", "text"), "full");
  assert.equal(classify("mobile", "tel"), "phone");
  assert.equal(classify("Postcode", "text"), "postcode");
  assert.equal(classify("store_location Favourite store location", "text"), null);
});

test("dry run fills a plain form, ticks consent, leaves marketing, never submits", async () => {
  const logPath = tmpLog();
  const [r] = await run({ queue: [{ id: 1, entry_url: url("simple.html") }], live: false, logPath });
  assert.equal(r.result, "dry_ok");
  assert.deepEqual([...r.fields].sort(), ["consent", "email", "first", "last", "phone", "postcode", "state"]);
  const log = fs.readFileSync(logPath, "utf8");
  assert.ok(!log.includes("example.com") && !log.includes("0400000000") && !log.includes("Person"));
});

test("live run submits and sees the confirmation", async () => {
  const [r] = await run({ queue: [{ id: 2, entry_url: url("simple.html") }], live: true, logPath: tmpLog() });
  assert.equal(r.result, "entered");
});

test("captcha and unknown required fields are skipped with a reason", async () => {
  const out = await run({ queue: [{ id: 3, entry_url: url("captcha.html") }, { id: 4, entry_url: url("unknown_required.html") }],
                          live: true, logPath: tmpLog() });
  assert.deepEqual(out.map((r) => [r.result, r.reason]), [["skipped", "captcha"], ["skipped", "unfillable"]]);
});

test("skill form needs an approved answer, and uses it when given", async () => {
  const [a] = await run({ queue: [{ id: 5, entry_url: url("skill.html") }], live: true, logPath: tmpLog() });
  assert.deepEqual([a.result, a.reason], ["skipped", "needs_answer"]);
  const [b] = await run({ queue: [{ id: 5, entry_url: url("skill.html"), answer: "Approved words." }], live: true, logPath: tmpLog() });
  assert.equal(b.result, "entered");
  assert.ok(b.fields.includes("answer"));
});
