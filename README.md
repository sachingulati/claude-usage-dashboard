# Claude Usage Dashboard

A self-updating dashboard of your Claude Code usage, built from the local
transcripts under `~/.claude/projects`. Tokens, cache reuse, per-day figures,
model / tool / MCP / skill attribution, a weekly heatmap, sessions and limit
hits — all from data already on your machine. Nothing is sent anywhere; the
server binds to `127.0.0.1` only.

## What it does

- **Regenerates hourly** (configurable) from your transcripts.
- **Serves a live page** on `localhost` that reloads itself on the same
  interval and keeps your filters across reloads.
- **Starts at logon** (optional, Windows Task Scheduler).

### Using the page

- **Filter** by granularity (day / week / month) and date range. The
  Today / 7d / 30d / All presets fill the **From** and **To** boxes, which are
  what actually filter &mdash; type into either, or click one for a calendar, to
  get an arbitrary range. Click any project, model, effort bar or legend chip to
  **isolate** it.
- **Focus sessions and workspaces.** Under *Tooling &rarr; Token cost by*, the
  **Sessions** and **Workspaces** tables list every session and every directory,
  sortable by any column, with a focus button per row. Focus as many as you like;
  every panel follows, including the Tooling ones.
- **Every active filter is a chip** in the rail, and each chip clears only itself.
  *Reset filters* clears everything.
- Panels cross-filter: each facet is computed with every filter *except its own*,
  so you can always see what else exists.
- **Cache economics** (in *Usage*) breaks the tokens in view into cache reads,
  cache writes, output and fresh input, with a reuse trend. Sessions, workspaces
  and Tooling rows each carry their own **Reuse** figure.
- **Hover anything in Tooling** for what it is, its full id and its numbers.
- **Collapse any panel** by clicking its heading, or *Collapse all*.
- Sessions carry a **copy** button for the id &mdash; resume with
  `claude --resume <id>`.
- Filters and collapsed panels are **remembered**, so the periodic auto-reload
  never disturbs your view.
- Light and dark themes; the toggle overrides your OS preference.

## Requirements

Python 3.11+ (uses stdlib `tomllib`). **No third-party packages.**

## Quick start

```bash
python serve.py
```

Builds the dashboard, serves it at `http://127.0.0.1:8787/`, and opens your
browser. Leave it running; it refreshes on the configured interval. `Ctrl+C`
to stop.

To build the static file once without serving:

```bash
python build.py        # writes output/dashboard.html (self-contained)
```

`output/dashboard.html` is a standalone file you can open directly or publish.

## Auto-start at logon (Windows)

```powershell
pwsh -File install.ps1     # register + start; runs hidden at every logon
pwsh -File uninstall.ps1   # stop the server and remove the auto-start
```

`uninstall.ps1` only disables the auto-start (and stops the running server);
it leaves your files, config, and generated output alone. `install.ps1
-Uninstall` does the same thing.

It starts immediately and at every logon, running `pythonw serve.py
--no-browser` (no console, no browser popup). Bookmark
`http://127.0.0.1:8787/` and open it whenever you like — the data is always
current. Don't also run `python serve.py` by hand while it's up; they'd fight
over the port.

**Admin vs non-admin.** `install.ps1` tries a Windows **Scheduled Task** first
(which also **restarts the server within a minute if it crashes**). Registering
a task needs elevation, so if you're not in an elevated shell it prints
`Access is denied` and **falls back automatically to a per-user logon Run key**
— no admin, still auto-starts at logon, but without the crash-restart. For the
crash-restart too, run `install.ps1` from an **elevated** PowerShell.
`uninstall.ps1` cleans up whichever was used.

## Development

```bash
python -m unittest discover -s tests -v   # cube tests (stdlib only)
node --test tests/logic.test.js           # logic tests (node:test, no deps)
```

`dashboard.logic.js` holds the page's pure logic — dates, filter sets, chips,
cache maths, tooltip copy — so it can be tested without a browser. `build.py`
inlines it into the page, which stays a single self-contained file.

The generated page is **pure ASCII** (it declares no charset), and `build.py`
fails the build naming the offending character. In the template use HTML
entities in markup and `\uXXXX` escapes inside JavaScript strings.

## Configuration — `config.toml`

| Key | Default | Meaning |
| --- | --- | --- |
| `refresh_minutes` | `60` | How often to regenerate stats and reload the page. |
| `port` | `8787` | Local server port (127.0.0.1 only). |
| `open_browser` | `true` | Open the browser on manual `serve.py` start. |
| `tz_offset_hours` | `5.5` | Your UTC offset, for day/hour bucketing. |
| `tz_label` | `Asia/Kolkata (UTC+5:30)` | Shown in the header. |
| `transcripts_dir` | `""` | Override `~/.claude/projects` if you moved it. |
| `accounts` | `[]` | Logins for the quota panel. Empty auto-detects `~/.claude`. |

Machine-specific settings go in **`config.local.toml`** (gitignored), merged over
`config.toml`, so the repo stays portable.

`refresh_minutes` is re-read every cycle, so changing it takes effect on the
next refresh without a restart. Changing `port` needs a restart.

## Files

| File | Role |
| --- | --- |
| `config.toml` | Your settings. |
| `serve.py` | Long-running server + refresh loop (this is what auto-starts). |
| `build.py` | One-shot regenerate of `output/dashboard.html`. |
| `emit_cube.py` | Reads transcripts, writes the compact data cube. Standalone-runnable. |
| `dashboard.template.html` | The page, with `__DATA__`, `__REFRESH__`, `__HOME__` and `__LOGIC__` placeholders. |
| `dashboard.logic.js` | Pure logic (dates, filters, chips, tooltip copy), inlined into the page at build time and unit-tested under `node --test`. |
| `dashboard_config.py` | Config loader shared by `build.py` / `serve.py`. |
| `limits.py` | Fetches live 5h / weekly quota for the configured accounts. |
| `install.ps1` | Register + start the logon auto-start task. |
| `uninstall.ps1` | Stop the server and remove the auto-start task. |
| `output/` | Generated `dashboard.html`, `cube.json`, `serve.log` (gitignored). |

## Notes

- Two Claude accounts sharing one config write to the same transcript folder,
  so figures are **combined across accounts** — there's no per-account marker
  to split them.
- Dollar figures are **API-equivalent value**, not a bill (a subscription
  doesn't charge per token).
- ~98% of tokens are cache reads billed at a fraction — the dashboard leans on
  that "cache reuse" ratio to explain why heavy use fits a flat plan.
- Everything is a lower bound: only Claude Code CLI writes here, not
  claude.ai / Desktop / Cowork.
