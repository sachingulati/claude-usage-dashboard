const { test } = require("node:test");
const assert = require("node:assert");
const DL = require("../dashboard.logic.js");

test("addDays crosses month and year boundaries", () => {
  assert.strictEqual(DL.addDays("2026-07-31", 1), "2026-08-01");
  assert.strictEqual(DL.addDays("2026-08-02", -6), "2026-07-27");
  assert.strictEqual(DL.addDays("2026-01-01", -1), "2025-12-31");
});

test("presetSpan anchors to today, not to the last day with data", () => {
  assert.deepStrictEqual(DL.presetSpan("1", "2026-08-02"),
    { from: "2026-08-02", to: "2026-08-02" });
  assert.deepStrictEqual(DL.presetSpan("7", "2026-08-02"),
    { from: "2026-07-27", to: "2026-08-02" });
  assert.deepStrictEqual(DL.presetSpan("30", "2026-08-02"),
    { from: "2026-07-04", to: "2026-08-02" });
});

test("the All preset is an open span, not a wide one", () => {
  assert.deepStrictEqual(DL.presetSpan("all", "2026-08-02"), { from: "", to: "" });
});

test("normSpan swaps a backwards range and leaves open bounds alone", () => {
  assert.deepStrictEqual(DL.normSpan("2026-08-02", "2026-07-01"),
    { from: "2026-07-01", to: "2026-08-02" });
  assert.deepStrictEqual(DL.normSpan("2026-07-01", "2026-08-02"),
    { from: "2026-07-01", to: "2026-08-02" });
  assert.deepStrictEqual(DL.normSpan("", "2026-07-01"),
    { from: "", to: "2026-07-01" });
  assert.deepStrictEqual(DL.normSpan("2026-07-01", ""),
    { from: "2026-07-01", to: "" });
});

test("matchPreset recognises a span that a preset would have produced", () => {
  assert.strictEqual(DL.matchPreset("", "", "2026-08-02"), "all");
  assert.strictEqual(DL.matchPreset("2026-08-02", "2026-08-02", "2026-08-02"), "1");
  assert.strictEqual(DL.matchPreset("2026-07-27", "2026-08-02", "2026-08-02"), "7");
  assert.strictEqual(DL.matchPreset("2026-07-04", "2026-08-02", "2026-08-02"), "30");
});

test("matchPreset returns null for a hand-typed span", () => {
  assert.strictEqual(DL.matchPreset("2026-07-14", "2026-07-20", "2026-08-02"), null);
  assert.strictEqual(DL.matchPreset("2026-07-27", "", "2026-08-02"), null);
});

test("matchPreset is relative to today, so yesterday's 7d no longer matches", () => {
  assert.strictEqual(DL.matchPreset("2026-07-27", "2026-08-02", "2026-08-03"), null);
});

test("inSpan is inclusive at both ends and open where a bound is empty", () => {
  assert.strictEqual(DL.inSpan("2026-07-01", "2026-07-01", "2026-07-05"), true);
  assert.strictEqual(DL.inSpan("2026-07-05", "2026-07-01", "2026-07-05"), true);
  assert.strictEqual(DL.inSpan("2026-06-30", "2026-07-01", "2026-07-05"), false);
  assert.strictEqual(DL.inSpan("2026-07-06", "2026-07-01", "2026-07-05"), false);
  assert.strictEqual(DL.inSpan("2020-01-01", "", ""), true);
  assert.strictEqual(DL.inSpan("2026-07-06", "", "2026-07-05"), false);
  assert.strictEqual(DL.inSpan("2026-07-06", "2026-07-01", ""), true);
});

const asSet = (a) => new Set(a);
const sorted = (s) => [...s].sort((a, b) => a - b);

test("toggleFocus isolates when nothing is filtered yet", () => {
  assert.deepStrictEqual(sorted(DL.toggleFocus(asSet([0, 1, 2, 3]), 2, 4)), [2]);
});

test("toggleFocus adds to an existing subset", () => {
  assert.deepStrictEqual(sorted(DL.toggleFocus(asSet([2]), 0, 4)), [0, 2]);
});

test("toggleFocus removes a member of a subset", () => {
  assert.deepStrictEqual(sorted(DL.toggleFocus(asSet([0, 2]), 2, 4)), [0]);
});

test("removing the last member falls back to everything", () => {
  assert.deepStrictEqual(sorted(DL.toggleFocus(asSet([2]), 2, 4)), [0, 1, 2, 3]);
});

test("toggleFocus does not mutate the set it is given", () => {
  const before = asSet([0, 1, 2, 3]);
  DL.toggleFocus(before, 1, 4);
  assert.deepStrictEqual(sorted(before), [0, 1, 2, 3]);
});

test("dimChips is empty when the dimension is unfiltered", () => {
  assert.deepStrictEqual(
    DL.dimChips({ kind: "models", names: ["a", "b"], total: 2, cap: 3, mode: "summary" }),
    []);
});

test("dimChips summarises past the cap", () => {
  assert.deepStrictEqual(
    DL.dimChips({ kind: "models", names: ["a", "b", "c", "d"], total: 9, cap: 3, mode: "summary" }),
    [{ id: "*", text: "4/9 models" }]);
});

test("dimChips lists each name up to the cap", () => {
  assert.deepStrictEqual(
    DL.dimChips({ kind: "models", names: ["a", "b"], total: 9, cap: 3, mode: "summary" }),
    [{ id: "a", text: "a" }, { id: "b", text: "b" }]);
});

test("list mode truncates with a +N more chip", () => {
  const names = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"];
  assert.deepStrictEqual(
    DL.dimChips({ kind: "sessions", names, total: 20, cap: 6, mode: "list" }),
    [{ id: "s1", text: "s1" }, { id: "s2", text: "s2" }, { id: "s3", text: "s3" },
     { id: "s4", text: "s4" }, { id: "s5", text: "s5" }, { id: "s6", text: "s6" },
     { id: "+", text: "+2 more" }]);
});

test("cacheSplit derives fresh input and percentages that sum to 100", () => {
  const s = DL.cacheSplit({ tok: 1000, cr: 900, cw: 50, out: 30 });
  assert.strictEqual(s.read, 900);
  assert.strictEqual(s.write, 50);
  assert.strictEqual(s.out, 30);
  assert.strictEqual(s.fresh, 20);
  assert.strictEqual(s.total, 1000);
  const sum = s.pct.read + s.pct.write + s.pct.out + s.pct.fresh;
  assert.ok(Math.abs(sum - 100) < 1e-9, `percentages summed to ${sum}`);
});

test("cacheSplit clamps a negative fresh remainder rather than showing it", () => {
  const s = DL.cacheSplit({ tok: 100, cr: 90, cw: 20, out: 10 });
  assert.strictEqual(s.fresh, 0);
});

test("cacheSplit survives an empty view without dividing by zero", () => {
  const s = DL.cacheSplit({ tok: 0, cr: 0, cw: 0, out: 0 });
  assert.strictEqual(s.total, 0);
  assert.deepStrictEqual(s.pct, { read: 0, write: 0, out: 0, fresh: 0 });
});

test("cacheVerdict names the reuse ratio and reads it back", () => {
  const strong = DL.cacheVerdict({ cr: 4000, cw: 100, readPct: 96.5 });
  assert.match(strong, /40/);
  assert.match(strong, /96\.5%/);
  const weak = DL.cacheVerdict({ cr: 200, cw: 100, readPct: 40 });
  assert.match(weak, /rebuil/i);
});

test("cacheVerdict says so plainly when there is nothing to judge", () => {
  assert.match(DL.cacheVerdict({ cr: 0, cw: 0, readPct: 0 }), /no cache/i);
});

test("parseId splits a plain MCP tool id", () => {
  assert.deepStrictEqual(DL.parseId("mcp__tavily__tavily_search"), {
    kind: "mcp", short: "tavily_search", full: "mcp__tavily__tavily_search",
    server: "tavily", plugin: "",
  });
});

test("parseId recovers the plugin behind a plugin-hosted MCP tool", () => {
  const p = DL.parseId("mcp__plugin_playwright_playwright__browser_click");
  assert.strictEqual(p.kind, "mcp");
  assert.strictEqual(p.short, "browser_click");
  assert.strictEqual(p.server, "playwright");
  assert.strictEqual(p.plugin, "playwright");
});

test("parseId splits a plugin-qualified skill", () => {
  assert.deepStrictEqual(DL.parseId("superpowers:brainstorming"), {
    kind: "skill", short: "brainstorming", full: "superpowers:brainstorming",
    server: "", plugin: "superpowers",
  });
});

test("parseId leaves a built-in alone", () => {
  assert.deepStrictEqual(DL.parseId("Bash"), {
    kind: "builtin", short: "Bash", full: "Bash", server: "", plugin: "",
  });
});

test("describe uses the written copy for a known built-in", () => {
  const d = DL.describe("Bash", "tools");
  assert.strictEqual(d.title, "Bash");
  assert.strictEqual(d.tag, "built-in tool");
  assert.match(d.body, /shell command/i);
});

test("describe warns that Agent tokens are the parent turn", () => {
  assert.match(DL.describe("Agent", "tools").body, /Delegation/);
});

test("describe derives copy for an unknown MCP tool, keeping the full id", () => {
  const d = DL.describe("mcp__tavily__tavily_search", "tools");
  assert.strictEqual(d.title, "tavily_search");
  assert.strictEqual(d.tag, "MCP tool");
  assert.match(d.body, /tavily/);
  assert.match(d.body, /mcp__tavily__tavily_search/);
});

test("describe names the plugin behind a plugin-hosted server", () => {
  assert.match(DL.describe("mcp__plugin_playwright_playwright__browser_click", "tools").body,
    /plugin/i);
});

test("describe handles a skill and an unknown name without going blank", () => {
  assert.match(DL.describe("superpowers:brainstorming", "skills").body, /superpowers/);
  const d = DL.describe("SomethingBrandNew", "tools");
  assert.strictEqual(d.title, "SomethingBrandNew");
  assert.ok(d.body.length > 0);
});

test("rangeChip describes open and closed spans", () => {
  assert.strictEqual(DL.rangeChip("", ""), null);
  assert.deepStrictEqual(DL.rangeChip("2026-07-14", "2026-07-20"),
    { id: "range", text: "2026-07-14 to 2026-07-20" });
  assert.deepStrictEqual(DL.rangeChip("2026-07-14", ""),
    { id: "range", text: "from 2026-07-14" });
  assert.deepStrictEqual(DL.rangeChip("", "2026-07-20"),
    { id: "range", text: "until 2026-07-20" });
});
