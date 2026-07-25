/* Pure logic for the dashboard: dates, filter sets, chips, tooltip copy.
   DOM-free by design, so node --test can exercise it (tests/logic.test.js).
   build.py inlines this file into dashboard.template.html at the __LOGIC__
   placeholder, so the generated page stays a single self-contained file.
   Must stay pure ASCII -- the built page declares no charset. */
const DL = {
  /* ---- dates ----
     Calendar days in the user's timezone, never instants. Formatted from local
     fields; toISOString() would convert to UTC and roll the date back a day
     anywhere east of Greenwich. */
  ymd(d){
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
  },
  addDays(day, n){
    const d = new Date(day + "T00:00:00");
    d.setDate(d.getDate() + n);
    return DL.ymd(d);
  },
  // Presets anchor to today, not to the last day with data: the boxes then say
  // exactly what you would expect, and a gap in usage shows as fewer active
  // days rather than being silently back-filled.
  presetSpan(preset, today){
    if (preset === "all") return { from: "", to: "" };
    const n = Number(preset);
    if (!n || n < 1) return { from: "", to: "" };
    return { from: DL.addDays(today, -(n - 1)), to: today };
  },
  // Which preset, if any, would produce this exact span today. Used to
  // re-highlight a button after restoring saved filters; a saved "7d" from
  // yesterday is deliberately no longer a match, because it no longer means 7d.
  matchPreset(from, to, today){
    for (const p of ["all", "1", "7", "30"]) {
      const s = DL.presetSpan(p, today);
      if (s.from === (from || "") && s.to === (to || "")) return p;
    }
    return null;
  },
  normSpan(from, to){
    from = from || ""; to = to || "";
    if (from && to && from > to) return { from: to, to: from };
    return { from, to };
  },
  inSpan(day, from, to){
    if (from && day < from) return false;
    if (to && day > to) return false;
    return true;
  },

  /* ---- filter sets ----
     The table rule, distinct from the bar-panel rule (isolate one, click the
     sole survivor to restore all). Returns a new Set rather than mutating, so
     callers cannot half-apply a change. "Everything selected" is how a
     dimension says "not filtered", so emptying it means clearing the filter. */
  toggleFocus(selected, i, total){
    const out = new Set(selected);
    if (out.size >= total) return new Set([i]);        // nothing filtered -> isolate
    if (out.has(i)) out.delete(i); else out.add(i);
    if (!out.size) { for (let j = 0; j < total; j++) out.add(j); }
    return out;
  },

  /* ---- rail chips ----
     One chip per active filter. Dimensions that partition the data collapse to
     "n/N kind" past the cap; sessions and workspaces list individually, because
     a focus is always deliberate and you need to see which ones. */
  dimChips({ kind, names, total, cap, mode }){
    names = names || [];
    if (!names.length || names.length >= total) return [];   // not filtered
    if (names.length <= cap) return names.map(n => ({ id: n, text: n }));
    if (mode === "list") {
      const head = names.slice(0, cap).map(n => ({ id: n, text: n }));
      head.push({ id: "+", text: `+${names.length - cap} more` });
      return head;
    }
    return [{ id: "*", text: `${names.length}/${total} ${kind}` }];
  },
  rangeChip(from, to){
    from = from || ""; to = to || "";
    if (!from && !to) return null;
    if (from && to) return { id: "range", text: `${from} to ${to}` };
    return { id: "range", text: from ? `from ${from}` : `until ${to}` };
  },

  /* ---- cache ----
     tok is input + output + cacheWrite + cacheRead, so fresh input is what is
     left once the three measured parts are removed. Clamped at zero: a
     malformed record should shrink a band, never invert one. */
  cacheSplit({ tok, cr, cw, out }){
    tok = tok || 0; cr = cr || 0; cw = cw || 0; out = out || 0;
    const fresh = Math.max(0, tok - cr - cw - out);
    const total = tok;
    const p = v => total ? v / total * 100 : 0;
    return { read: cr, write: cw, out, fresh, total,
             pct: { read: p(cr), write: p(cw), out: p(out), fresh: p(fresh) } };
  },
  // One sentence stating the conclusion, rather than leaving it to be derived
  // from the bars -- the same job the quota verdict does.
  cacheVerdict({ cr, cw, readPct }){
    if (!cw) return "No cache writes in view, so there is no reuse ratio to report.";
    const ratio = cr / cw;
    const r = ratio >= 10 ? Math.round(ratio) : ratio.toFixed(1);
    const share = (readPct || 0).toFixed(1);
    if (ratio >= 20) {
      return `Each written token was read back ${r} times, and ${share}% of everything ` +
        `in view is cache reads -- billed at a fraction of a fresh token. This is why ` +
        `heavy use fits a flat plan.`;
    }
    if (ratio >= 5) {
      return `Each written token was read back ${r} times; ${share}% of tokens in view ` +
        `are cache reads. Solid, though longer sessions would reuse more.`;
    }
    return `Each written token was read back only ${r} times, with ${share}% of tokens ` +
      `in view coming from cache reads -- context is being rebuilt about as often as ` +
      `it is re-read. Short or frequently-restarted sessions do this.`;
  },

  /* ---- identity ----
     The page shows a shortened name; the card must be able to say exactly what
     the row was. Plugin-hosted MCP servers arrive as
     mcp__plugin_<plugin>_<server>__<tool>. */
  parseId(name){
    const s = String(name);
    const out = { kind: "builtin", short: s, full: s, server: "", plugin: "" };
    if (s.startsWith("mcp__")) {
      const parts = s.slice(5).split("__");
      out.kind = "mcp";
      out.short = parts[parts.length - 1] || s;
      let server = parts[0] || "";
      if (server.startsWith("plugin_")) {
        const bits = server.slice(7).split("_");
        out.plugin = bits[0] || "";
        server = bits.slice(1).join("_") || out.plugin;
      }
      out.server = server;
      return out;
    }
    if (s.startsWith("plugin:")) {
      const bits = s.split(":");
      out.kind = "mcp";
      out.plugin = bits[1] || "";
      out.server = bits[bits.length - 1] || "";
      out.short = out.server;
      return out;
    }
    if (s.includes(":")) {
      const bits = s.split(":");
      out.kind = "skill"; out.plugin = bits[0]; out.short = bits.slice(1).join(":");
      return out;
    }
    return out;
  },

  // Written copy for the Claude Code built-ins -- the largest rows, and the
  // only names whose meaning is stable enough to state. Everything else is
  // described from its id, so a new name is never blank.
  TOOL_DOCS: {
    Bash: "Runs a shell command and returns its output.",
    PowerShell: "Runs a PowerShell command -- Windows-native work such as services, the registry or environment variables.",
    Read: "Reads a file from disk. Large files and images enter the context whole, so a few Reads can dominate a turn.",
    Edit: "Replaces an exact string in a file. The file must have been read first in the same session.",
    Write: "Writes a file, replacing anything already there.",
    Glob: "Finds files by name pattern, returning paths only.",
    Grep: "Searches file contents with ripgrep.",
    Agent: "Spawns a subagent to work in its own context. These tokens are the parent turn that dispatched it -- what the subagent itself consumed is counted separately, in Delegation below.",
    Skill: "Loads a skill's instructions into the current turn.",
    ToolSearch: "Loads the schemas for deferred tools so they can be called.",
    WebFetch: "Fetches a URL and converts the page to text.",
    WebSearch: "Runs a web search and returns result summaries.",
    Monitor: "Watches a file or command until a condition is met, without blocking the turn.",
    Artifact: "Publishes an HTML or Markdown file as a hosted page.",
    SendMessage: "Sends a message to an agent that is already running, keeping its context.",
    SendUserFile: "Sends a file to the user.",
    NotebookEdit: "Edits a single cell in a Jupyter notebook.",
    AskUserQuestion: "Asks the user a multiple-choice question mid-task.",
    TodoWrite: "Records the running task list.",
    ReportFindings: "Reports code-review findings as structured data.",
    TaskCreate: "Starts a background task. Its tokens are the parent turn, not the task's own work -- see Delegation below.",
    TaskUpdate: "Updates a background task's state.",
    TaskOutput: "Reads output from a background task.",
    TaskStop: "Stops a background task.",
    TaskGet: "Reads one background task's status.",
    TaskList: "Lists the background tasks.",
  },

  describe(name, cat){
    const p = DL.parseId(name);
    if (p.kind === "builtin" && cat !== "skills" && cat !== "plugins") {
      return { title: p.short, tag: "built-in tool",
               body: DL.TOOL_DOCS[p.short] ||
                 "A Claude Code tool. No description recorded for this name yet -- it may be new." };
    }
    if (cat === "plugins") {
      return { title: p.short, tag: "plugin",
               body: `A Claude Code plugin. Tokens are those spent while one of its skills or MCP servers was active. Full id: ${p.full}` };
    }
    if (p.kind === "skill" || cat === "skills") {
      const from = p.plugin ? `, from plugin ${p.plugin}` : "";
      return { title: p.short, tag: "skill",
               body: `A skill${from}. Tokens are those spent while its instructions were loaded, so this covers a slice of a turn rather than a tool call. Full id: ${p.full}` };
    }
    if (cat === "mcp") {
      const from = p.plugin ? ` (from plugin ${p.plugin})` : "";
      return { title: p.short || p.server, tag: "MCP server",
               body: `An MCP server${from}. Tokens are those spent while a call to it was in flight. Full id: ${p.full}` };
    }
    const from = p.plugin ? ` (from plugin ${p.plugin})` : "";
    return { title: p.short, tag: "MCP tool",
             body: `An MCP tool, served by ${p.server || "an unnamed server"}${from}. Full id: ${p.full}` };
  },
};

if (typeof module !== "undefined" && module.exports) module.exports = DL;
