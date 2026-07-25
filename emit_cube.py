import json, glob, os, re, datetime, bisect, collections

# Configurable via environment (build.py sets these from config.toml):
#   CLAUDE_USAGE_TZ_OFFSET  hours from UTC for day/hour bucketing (default 5.5)
#   CLAUDE_USAGE_TZ_LABEL   label shown in the dashboard header
#   CLAUDE_USAGE_ROOT       single transcripts dir (default ~/.claude/projects)
#   CLAUDE_USAGE_ROOTS      JSON [[account-label, dir], ...]; wins over ROOT.
#                           A blank label means "this root is shared by every
#                           account", i.e. usage here cannot be attributed.
#   CLAUDE_USAGE_OUT        where to write cube.json (default alongside this file)
_TZ_OFFSET = float(os.environ.get("CLAUDE_USAGE_TZ_OFFSET", "5.5"))
_TZ_LABEL = os.environ.get("CLAUDE_USAGE_TZ_LABEL", "Asia/Kolkata (UTC+5:30)")
IST = datetime.timezone(datetime.timedelta(hours=_TZ_OFFSET))
UTC = datetime.timezone.utc
ROOT = os.environ.get("CLAUDE_USAGE_ROOT") or os.path.join(
    os.path.expanduser("~"), ".claude", "projects")
try:
    ROOTS = [(str(l), str(p)) for l, p in json.loads(os.environ["CLAUDE_USAGE_ROOTS"])]
except Exception:
    ROOTS = [("", ROOT)]
ROOTS = [(l, p) for l, p in ROOTS if os.path.isdir(p)] or [("", ROOT)]
# Attribution is only honest when every root carries its own label; one shared
# root (the single-config layout) cannot be split, whatever the config says.
ACCOUNTS = [l for l, _ in ROOTS if l]
SPLIT_BY_ACCOUNT = len(ROOTS) > 1 and len(ACCOUNTS) == len(ROOTS)
if not SPLIT_BY_ACCOUNT:
    ACCOUNTS = []
OUT = os.environ.get("CLAUDE_USAGE_OUT") or os.path.join(
    os.path.dirname(__file__), "cube.json")


def is_claude(m):
    return m.startswith("claude-")


best, limits_raw = {}, []
output_caps = 0                          # responses that blew the output-token cap
_files = [(ai, root, f)
          for ai, (_lbl, root) in enumerate(ROOTS)
          for f in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)]
for acct_i, _root, f in _files:
    acct_i = acct_i if SPLIT_BY_ACCOUNT else 0
    d0 = os.path.relpath(f, _root).split(os.sep)[0]
    for line in open(f, encoding="utf-8", errors="replace"):
        if '"usage"' not in line and "isApiErrorMessage" not in line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = d.get("timestamp")
        if not t:
            continue
        ts = datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
        m = d.get("message") or {}
        u = m.get("usage") if isinstance(m, dict) else None
        if isinstance(u, dict) and is_claude(m.get("model", "")):
            mid = m.get("id") or d.get("uuid")
            inp = u.get("input_tokens", 0); out = u.get("output_tokens", 0)
            cw = u.get("cache_creation_input_tokens", 0); cr = u.get("cache_read_input_tokens", 0)
            total = inp + out + cw + cr
            if total == 0:
                continue
            content = m.get("content")
            tool_names = [b.get("name") for b in content
                          if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name")] \
                if isinstance(content, list) else []
            rec = dict(ts=ts, model=m["model"], dir=d0, acct_i=acct_i,
                       eff=d.get("effort", "") or "unset",
                       tok=total, cr=cr, cw=cw, out=out, side=bool(d.get("isSidechain")),
                       skill=d.get("attributionSkill"), srv=d.get("attributionMcpServer"),
                       mtool=d.get("attributionMcpTool"), plugin=d.get("attributionPlugin"),
                       session=d.get("sessionId"), stop=m.get("stop_reason"), tools=tool_names)
            if mid not in best or total > best[mid][0]:
                if mid in best:
                    rec["ts"] = min(ts, best[mid][1]["ts"])
                best[mid] = (total, rec)
        if d.get("isApiErrorMessage"):
            c = m.get("content")
            txt = c if isinstance(c, str) else " ".join(
                x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else ""
            tl = txt.lower()
            if "session limit" in tl or "weekly limit" in tl:
                limits_raw.append((ts, "weekly" if "weekly" in tl else "session",
                                   txt, d0, acct_i, d.get("sessionId") or ""))
            elif "output token" in tl:
                output_caps += 1

recs = sorted((r for _, r in best.values()), key=lambda r: r["ts"])
calls_ts = [r["ts"] for r in recs]

# --- account switch reconstruction (same rule as before) ---
limits_raw.sort()
episodes = []
for ts, kind, txt, d0, acct_i, sess in limits_raw:
    reset = re.search(r"resets[^)]*", txt)
    key = (kind, reset.group(0) if reset else txt[:30])
    if episodes and episodes[-1][3] == key and (ts - episodes[-1][0]).total_seconds() < 3600:
        continue
    episodes.append((ts, kind, txt, key, d0, acct_i, sess))


def parse_reset(ts_utc, txt):
    ev = ts_utc.astimezone(IST)
    md = re.search(r"resets (?:(\w{3}) (\d+), )?(\d{1,2})(?::(\d\d))?\s*([ap]m)", txt, re.I)
    if not md:
        return None
    mon, day, hr, mn, ap = md.groups()
    hr, mn = int(hr), int(mn or 0)
    if ap.lower() == "pm" and hr != 12:
        hr += 12
    if ap.lower() == "am" and hr == 12:
        hr = 0
    if mon:
        MON = dict(jan=1, feb=2, mar=3, apr=4, may=5, jun=6, jul=7,
                   aug=8, sep=9, oct=10, nov=11, dec=12)
        r = datetime.datetime(ev.year, MON[mon.lower()[:3]], int(day), hr, mn, tzinfo=IST)
    else:
        r = ev.replace(hour=hr, minute=mn, second=0, microsecond=0)
        if r <= ev:
            r += datetime.timedelta(days=1)
    return r.astimezone(UTC)


# Early resume before a limit's stated reset is evidence of *something* -
# but not always a manual account switch. Two confounds:
#   1. Anthropic-side resets (promo / release bonus). These target the
#      WEEKLY ceiling, not the rolling 5-hour window (the only in-window
#      promo here was the May 13-Jul 19 weekly +50%; the 5h doubling was
#      May 6, before this data). So a weekly early-resume is genuinely
#      ambiguous between a switch and an Anthropic reset.
#   2. Natural rolling-window recovery. A 5-hour limit frees capacity
#      continuously, so resuming slightly early on the SAME account is
#      possible. Strong for small gaps, negligible for large ones.
# Only a session-limit resume with a comfortable gap is called a confident
# switch and allowed to reassign the account; everything else is surfaced
# but does not move the A/B attribution (so the split stays a floor).
SESSION_MIN_GAP = 60  # minutes; below this, rolling recovery is plausible
PROMO_WINDOWS = [("2026-05-13", "2026-07-19")]  # weekly +50%, from research


def in_promo(day):
    return any(a <= day <= b for a, b in PROMO_WINDOWS)


switches = []
for ts, kind, txt, key, d0, acct_i, sess in episodes:
    reset = parse_reset(ts, txt)
    i = bisect.bisect_right(calls_ts, ts)
    nxt = calls_ts[i] if i < len(calls_ts) else None
    early = nxt is not None and reset is not None and nxt < reset - datetime.timedelta(minutes=2)
    gap = round((reset - nxt).total_seconds() / 60) if early else None
    day = ts.astimezone(IST).date().isoformat()
    if not early:
        conf = "waited"
    elif kind == "weekly":
        conf = "ambiguous"  # could be an Anthropic reset/promo, not a switch
    elif gap >= SESSION_MIN_GAP:
        conf = "switch"     # confident manual account switch
    else:
        conf = "soft"       # small gap - natural rolling recovery possible
    switches.append(dict(ts=ts.isoformat(), ist=ts.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
                         day=day, kind=kind, switch=(conf == "switch"), conf=conf, dir=d0,
                         session=sess,
                         acct=(ACCOUNTS[acct_i] if SPLIT_BY_ACCOUNT else None),
                         gap_min=gap, in_promo=in_promo(day)))

if SPLIT_BY_ACCOUNT:
    # Real attribution: the config directory a transcript came from *is* the
    # account. No inference involved.
    for r in recs:
        r["acct"] = ACCOUNTS[r["acct_i"]]
else:
    # Fallback for the shared-config layout, where nothing marks the account:
    # flip on each confidently-inferred switch after a limit hit. A guess, and
    # labelled as one in the page -- never presented as measured.
    switch_ts = [datetime.datetime.fromisoformat(e["ts"]) for e in switches if e["conf"] == "switch"]
    acct, si = "A", 0
    for r in recs:
        while si < len(switch_ts) and r["ts"] >= switch_ts[si]:
            acct = "B" if acct == "A" else "A"
            si += 1
        r["acct"] = acct

# --- dimension tables ---
days = sorted({r["ts"].astimezone(IST).date().isoformat() for r in recs})
projects = sorted({r["dir"] for r in recs})
# Derive the model list from the data so a newly released model can't break the
# build. Known models keep a nice order; anything unrecognised is appended.
PREFERRED = ["claude-opus-5", "claude-opus-4-8", "claude-sonnet-5",
             "claude-fable-5", "claude-haiku-4-5-20251001"]
present_models = {r["model"] for r in recs}
models = [m for m in PREFERRED if m in present_models]
models += sorted(present_models - set(models))
efforts = ["unset", "high", "xhigh", "max"]
sessions = sorted({r["session"] for r in recs if r["session"]})
di = {d: i for i, d in enumerate(days)}
pi = {p: i for i, p in enumerate(projects)}
mi = {m: i for i, m in enumerate(models)}
ei = {e: i for i, e in enumerate(efforts)}
xi = {s: i for i, s in enumerate(sessions)}

# --- fact table: collapse by (day, hour, proj, model, effort, acctBit, session) ---
# Adding the session costs ~6% more rows on real data and is what lets the page
# filter every panel to one or more sessions. Output tokens ride along as a
# measure -- measures never multiply the table, and without this one the token
# split cannot be shown at all (output is the expensive part, and was invisible).
agg = {}
for r in recs:
    ist = r["ts"].astimezone(IST)
    key = (di[ist.date().isoformat()], ist.hour, pi[r["dir"]],
           mi[r["model"]], ei.get(r["eff"], 0),
           (r["acct_i"] if SPLIT_BY_ACCOUNT else (0 if r["acct"] == "A" else 1)),
           xi.get(r["session"], -1))
    a = agg.get(key)
    if a is None:
        agg[key] = [r["tok"], r["cr"], r["cw"], r["out"], 1]
    else:
        a[0] += r["tok"]; a[1] += r["cr"]; a[2] += r["cw"]; a[3] += r["out"]; a[4] += 1

facts = [list(k) + v for k, v in agg.items()]

# --- extras: attribution & context ---
# Each entry is [name, total_tokens, total_calls, tail], where a tail row is
# [dayIdx, projIdx, sessIdx, tokens, cacheRead, cacheWrite, calls]. The tail lets
# the page re-total these under the date, workspace and session filters; without
# it the tooling panels were stuck on all-time figures while every other panel
# followed them. The cache pair costs no extra rows and is what gives each row a
# reuse ratio. Sparse -- only keys that actually occur.
total_tok = sum(r["tok"] for r in recs)


def _rows(tk, ca, per_key, keys):
    """per_key[name][(day, dir, session)] = [tokens, cacheRead, cacheWrite, calls]."""
    out = []
    for k in keys:
        rows = [[di[d], pi[p], xi.get(s, -1), *v]
                for (d, p, s), v in sorted(per_key[k].items())
                if d in di and p in pi]
        out.append([k, tk[k], ca[k], rows])
    return out


def _bucket(r):
    return (r["ts"].astimezone(IST).date().isoformat(), r["dir"], r["session"])


def _cell(store, name, r):
    """Accumulate one record into a (name, day, dir, session) cell."""
    c = store[name][_bucket(r)]
    c[0] += r["tok"]; c[1] += r["cr"]; c[2] += r["cw"]; c[3] += 1


def _store():
    return collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0, 0]))


def attr(field):
    tk = collections.Counter(); ca = collections.Counter()
    per_key = _store()
    for r in recs:
        v = r.get(field)
        if v:
            tk[v] += r["tok"]; ca[v] += 1
            _cell(per_key, v, r)
    return _rows(tk, ca, per_key, [k for k, _ in tk.most_common()])


# tokens by tool: each message invokes at most one tool_use (verified), so
# crediting the message's tokens to that tool is exact, not a split.
tool_tok = collections.Counter(); tool_ca = collections.Counter()
tool_key = _store()
for r in recs:
    for n in r.get("tools") or []:
        tool_tok[n] += r["tok"]; tool_ca[n] += 1
        _cell(tool_key, n, r)
tools_out = _rows(tool_tok, tool_ca, tool_key, [k for k, _ in tool_tok.most_common(24)])

# delegation, per (day, project, session) so the panel can follow every filter.
# Call counts used to be apportioned by token share under a filter; carrying
# them here makes the filtered figures exact.
deleg = collections.defaultdict(lambda: [0, 0, 0, 0])   # mainTok, subTok, mainCa, subCa
main_tok = sub_tok = main_ca = sub_ca = 0
for r in recs:
    cell = deleg[_bucket(r)]
    if r["side"]:
        cell[1] += r["tok"]; cell[3] += 1; sub_tok += r["tok"]; sub_ca += 1
    else:
        cell[0] += r["tok"]; cell[2] += 1; main_tok += r["tok"]; main_ca += 1
deleg_rows = [[di[d], pi[p], xi.get(s, -1), *v]
              for (d, p, s), v in sorted(deleg.items()) if d in di and p in pi]

# truncations
max_tok_trunc = sum(1 for r in recs if r.get("stop") == "max_tokens")

# sessions
sess = collections.defaultdict(lambda: {"tok": 0, "calls": 0, "last_ts": None,
                                        "dirs": collections.Counter(), "sub": 0, "acct": None})
for r in recs:
    s = sess[r["session"]]
    s["tok"] += r["tok"]; s["calls"] += 1; s["dirs"][r["dir"]] += 1
    if SPLIT_BY_ACCOUNT:
        s["acct"] = r["acct"]
    if r["side"]:
        s["sub"] += 1
    if s["last_ts"] is None or r["ts"] > s["last_ts"]:
        s["last_ts"] = r["ts"]
# Full session id so the front end can offer a copy-to-resume; sorted most
# recent first as a sensible default, though the page re-sorts on demand.
# Columns: [id, tokens, calls, last-used (ISO minutes), directory, account]
sess_list = [[sid, v["tok"], v["calls"],
              v["last_ts"].astimezone(IST).strftime("%Y-%m-%dT%H:%M"),
              (v["dirs"].most_common(1)[0][0] if v["dirs"] else ""),
              v["acct"] or ""]
             for sid, v in sorted(sess.items(),
                                  key=lambda kv: kv[1]["last_ts"] or datetime.datetime.min.replace(tzinfo=UTC),
                                  reverse=True)
             if sid]
sess_toks = sorted(v["tok"] for v in sess.values())
sess_summary = dict(count=len(sess),
                    median_tok=sess_toks[len(sess_toks) // 2] if sess_toks else 0,
                    max_tok=sess_toks[-1] if sess_toks else 0)

extras = dict(
    total_tok=total_tok,
    tools=tools_out,
    mcp=attr("srv"),
    mcp_tools=attr("mtool")[:16],
    skills=attr("skill"),
    plugins=attr("plugin"),
    delegation=dict(main_tok=main_tok, sub_tok=sub_tok, main_calls=main_ca,
                    sub_calls=sub_ca, rows=deleg_rows),
    truncations=dict(max_tokens=max_tok_trunc, output_cap=output_caps),
    sessions=dict(summary=sess_summary, all=sess_list),
)

out = dict(
    generated=datetime.datetime.now(UTC).isoformat(),
    tz=_TZ_LABEL,
    span=[days[0], days[-1]],
    days=days, projects=projects, models=models, efforts=efforts, sessions=sessions,
    # Present only when each account has its own transcripts directory, so the
    # split is measured rather than inferred. Empty means "combined".
    accounts=ACCOUNTS,
    # fact columns: [dayIdx, hour, projIdx, modelIdx, effortIdx, acctBit, sessIdx,
    #                tokens, cacheRead, cacheWrite, outTokens, calls]
    facts=facts,
    switches=switches,
    extras=extras,
)
json.dump(out, open(OUT, "w"), separators=(",", ":"))
sz = os.path.getsize(OUT)
print("records:", len(recs), " fact rows:", len(facts), " switches:", len(switches))
print("dims: days", len(days), "projects", len(projects), "models", len(models))
print("cube.json size: %.0f KB" % (sz / 1024))
