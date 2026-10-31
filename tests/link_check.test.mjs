// Offline tests for the browser link check's verdicts (node --test tests/link_check.test.mjs). No network.
import { test } from "node:test";
import assert from "node:assert/strict";
import { keys, verdict } from "../workers/link_check.mjs";

const item = { title: "Win a Coolman 78 Recreational Series Fridge/Freezer", brand: "Tentworld" };
const page = (o) => ({ status: 200, startUrl: "https://shop.example/win", finalUrl: "https://shop.example/win", title: "", text: "", form: false, ...o });

test("listing keys are the brand and the prize nouns", () => {
  const k = keys(item);
  assert.deepEqual(k.brand, ["tentworld"]);
  assert.ok(k.prize.includes("coolman") && k.prize.includes("fridge/freezer".split("/")[0]) && !k.prize.includes("win"));
});

test("verdicts", () => {
  assert.equal(verdict(page({ status: 404 }), item).kind, "dead");
  assert.equal(verdict(page({ text: "Enter now for your chance to win a Coolman fridge. Tentworld giveaway. Entries close soon.", form: true }), item).kind, "ok");
  assert.equal(verdict(page({ finalUrl: "https://shop.example/camping", text: "Tentworld camping gear sale. Shop tents and chairs. " + "x".repeat(700) }), item).kind, "wrong");
  assert.equal(verdict(page({ finalUrl: "https://shop.example/", text: "New season. Free shipping. " + "x".repeat(700) }), item).kind, "home");
  assert.equal(verdict(page({ title: "Just a moment...", text: "Checking your browser" }), item).kind, "blocked");
  assert.equal(verdict(page({ text: "Log in to continue" }), item).kind, "login");
});
