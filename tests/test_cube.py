"""Tests for emit_cube.py.

Drives the real script as a subprocess over a synthetic transcripts tree, so
what is tested is exactly what build.py runs. Stdlib only -- no pytest.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EMIT = ROOT / "emit_cube.py"


def rec(ts, session="s1", model="claude-opus-5", tokens=(10, 5, 2, 100),
        tools=(), **extra):
    """One transcript line. tokens = (input, output, cache_write, cache_read)."""
    inp, out, cw, cr = tokens
    msg = {
        "id": extra.pop("mid", None) or f"m-{ts}-{session}",
        "model": model,
        "usage": {"input_tokens": inp, "output_tokens": out,
                  "cache_creation_input_tokens": cw,
                  "cache_read_input_tokens": cr},
    }
    if tools:
        msg["content"] = [{"type": "tool_use", "name": n} for n in tools]
    line = {"timestamp": ts, "sessionId": session, "uuid": f"u-{ts}-{session}",
            "message": msg}
    line.update(extra)
    return json.dumps(line)


def build_cube(lines_by_dir, **env):
    """Run emit_cube.py over a temp transcripts tree; return the parsed cube.

    lines_by_dir: {"proj-a": [line, ...]} -- keys become project directories.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for d, lines in lines_by_dir.items():
            (root / d).mkdir(parents=True, exist_ok=True)
            (root / d / "t.jsonl").write_text("\n".join(lines), encoding="utf-8")
        out = root / "cube.json"
        e = dict(os.environ,
                 CLAUDE_USAGE_ROOT=str(root),
                 CLAUDE_USAGE_OUT=str(out),
                 CLAUDE_USAGE_TZ_OFFSET="0")
        e.pop("CLAUDE_USAGE_ROOTS", None)
        e.update({k: str(v) for k, v in env.items()})
        proc = subprocess.run([sys.executable, str(EMIT)], env=e,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(f"emit_cube failed:\n{proc.stdout}\n{proc.stderr}")
        return json.loads(out.read_text(encoding="utf-8"))


# Fact columns, mirroring the constants in dashboard.template.html.
D_DAY, D_HOUR, D_PROJ, D_MODEL, D_EFF, D_ACCT, D_SESS = range(7)
T_TOK, T_CR, T_CW, T_OUT, T_CALLS = 7, 8, 9, 10, 11


class TestSessionDimension(unittest.TestCase):
    def test_sessions_dimension_lists_every_session(self):
        cube = build_cube({"proj-a": [
            rec("2026-07-01T10:00:00Z", session="alpha"),
            rec("2026-07-01T11:00:00Z", session="beta"),
        ]})
        self.assertEqual(cube["sessions"], ["alpha", "beta"])

    def test_fact_rows_carry_a_session_index(self):
        cube = build_cube({"proj-a": [
            rec("2026-07-01T10:00:00Z", session="alpha"),
            rec("2026-07-01T11:00:00Z", session="beta"),
        ]})
        self.assertTrue(all(len(f) == 12 for f in cube["facts"]))
        got = sorted((f[D_HOUR], cube["sessions"][f[D_SESS]]) for f in cube["facts"])
        self.assertEqual(got, [(10, "alpha"), (11, "beta")])

    def test_fact_rows_carry_output_tokens_and_the_split_adds_up(self):
        # tokens = (input, output, cache_write, cache_read)
        cube = build_cube({"proj-a": [
            rec("2026-07-01T10:00:00Z", tokens=(7, 5, 3, 100))]})
        f = cube["facts"][0]
        self.assertEqual(f[T_TOK], 115)
        self.assertEqual(f[T_OUT], 5)
        self.assertEqual(f[T_CW], 3)
        self.assertEqual(f[T_CR], 100)
        fresh_input = f[T_TOK] - f[T_CR] - f[T_CW] - f[T_OUT]
        self.assertEqual(fresh_input, 7)

    def test_output_tokens_sum_across_collapsed_records(self):
        cube = build_cube({"proj-a": [
            rec("2026-07-01T10:00:00Z", mid="a", tokens=(1, 5, 0, 10)),
            rec("2026-07-01T10:30:00Z", mid="b", tokens=(1, 9, 0, 10)),
        ]})
        self.assertEqual(len(cube["facts"]), 1)
        self.assertEqual(cube["facts"][0][T_OUT], 14)
        self.assertEqual(cube["facts"][0][T_CALLS], 2)

    def test_two_sessions_in_one_hour_do_not_collapse(self):
        """Same day/hour/project/model/effort -- only the session differs."""
        cube = build_cube({"proj-a": [
            rec("2026-07-01T10:00:00Z", session="alpha"),
            rec("2026-07-01T10:30:00Z", session="beta"),
        ]})
        self.assertEqual(len(cube["facts"]), 2)

    def test_record_without_a_session_gets_minus_one(self):
        line = json.loads(rec("2026-07-01T10:00:00Z"))
        del line["sessionId"]
        cube = build_cube({"proj-a": [json.dumps(line)]})
        self.assertEqual(cube["sessions"], [])
        self.assertEqual(cube["facts"][0][D_SESS], -1)


# Attribution tail columns.
A_DAY, A_PROJ, A_SESS, A_TOK, A_CR, A_CW, A_CALLS = range(7)


class TestAttributionTails(unittest.TestCase):
    def _cube(self):
        return build_cube({
            "proj-a": [rec("2026-07-01T10:00:00Z", session="alpha", tools=["Bash"])],
            "proj-b": [rec("2026-07-02T10:00:00Z", session="beta", tools=["Bash"])],
        })

    def test_tool_tail_rows_have_seven_columns(self):
        cube = self._cube()
        bash = next(x for x in cube["extras"]["tools"] if x[0] == "Bash")
        self.assertTrue(all(len(row) == 7 for row in bash[3]))

    def test_tool_tail_carries_cache_read_and_write(self):
        cube = build_cube({"proj-a": [
            rec("2026-07-01T10:00:00Z", tools=["Bash"], tokens=(1, 2, 30, 400))]})
        bash = next(x for x in cube["extras"]["tools"] if x[0] == "Bash")
        self.assertEqual(bash[3][0][A_CR], 400)
        self.assertEqual(bash[3][0][A_CW], 30)

    def test_tool_tail_carries_project_and_session(self):
        cube = self._cube()
        bash = next(x for x in cube["extras"]["tools"] if x[0] == "Bash")
        got = sorted((cube["days"][r[A_DAY]],
                      cube["projects"][r[A_PROJ]],
                      cube["sessions"][r[A_SESS]]) for r in bash[3])
        self.assertEqual(got, [("2026-07-01", "proj-a", "alpha"),
                               ("2026-07-02", "proj-b", "beta")])

    def test_skill_tail_carries_project_and_session(self):
        cube = build_cube({"proj-a": [
            rec("2026-07-01T10:00:00Z", session="alpha",
                attributionSkill="dataviz"),
        ]})
        skill = cube["extras"]["skills"][0]
        self.assertEqual(skill[0], "dataviz")
        self.assertEqual(len(skill[3][0]), 7)
        self.assertEqual(cube["sessions"][skill[3][0][A_SESS]], "alpha")

    def test_tail_totals_still_match_the_headline(self):
        cube = self._cube()
        bash = next(x for x in cube["extras"]["tools"] if x[0] == "Bash")
        self.assertEqual(sum(r[A_TOK] for r in bash[3]), bash[1])
        self.assertEqual(sum(r[A_CALLS] for r in bash[3]), bash[2])


# Delegation row columns.
G_DAY, G_PROJ, G_SESS, G_MAIN_TOK, G_SUB_TOK, G_MAIN_CA, G_SUB_CA = range(7)


class TestDelegationRows(unittest.TestCase):
    def test_rows_split_main_and_subagent_by_session(self):
        cube = build_cube({"proj-a": [
            rec("2026-07-01T10:00:00Z", session="alpha", tokens=(1, 1, 0, 100)),
            rec("2026-07-01T10:05:00Z", session="alpha", tokens=(1, 1, 0, 200),
                isSidechain=True),
        ]})
        rows = cube["extras"]["delegation"]["rows"]
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(cube["sessions"][r[G_SESS]], "alpha")
        self.assertEqual(r[G_MAIN_TOK], 102)
        self.assertEqual(r[G_SUB_TOK], 202)
        self.assertEqual(r[G_MAIN_CA], 1)
        self.assertEqual(r[G_SUB_CA], 1)

    def test_row_totals_match_the_scalars(self):
        cube = build_cube({
            "proj-a": [rec("2026-07-01T10:00:00Z", session="alpha")],
            "proj-b": [rec("2026-07-02T10:00:00Z", session="beta",
                           isSidechain=True)],
        })
        d = cube["extras"]["delegation"]
        self.assertEqual(sum(r[G_MAIN_TOK] for r in d["rows"]), d["main_tok"])
        self.assertEqual(sum(r[G_SUB_TOK] for r in d["rows"]), d["sub_tok"])
        self.assertEqual(sum(r[G_SUB_CA] for r in d["rows"]), d["sub_calls"])

    def test_daily_key_is_gone(self):
        cube = build_cube({"proj-a": [rec("2026-07-01T10:00:00Z")]})
        self.assertNotIn("daily", cube["extras"]["delegation"])


class TestLimitEpisodeSession(unittest.TestCase):
    def test_limit_episode_carries_its_session(self):
        err = json.dumps({
            "timestamp": "2026-07-01T12:00:00Z", "sessionId": "alpha",
            "uuid": "e1", "isApiErrorMessage": True,
            "message": {"content": "5-hour session limit reached, resets 4pm"},
        })
        cube = build_cube({"proj-a": [
            rec("2026-07-01T10:00:00Z", session="alpha"), err]})
        self.assertEqual(len(cube["switches"]), 1)
        self.assertEqual(cube["switches"][0]["session"], "alpha")
        self.assertEqual(cube["switches"][0]["kind"], "session")


def slug(path):
    """Claude Code's transcript-folder name for a cwd."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


class TestProjectPaths(unittest.TestCase):
    """project_paths[i] is the real path behind projects[i], or "" when unknown."""

    def test_cwd_matching_the_folder_gives_its_real_path(self):
        cwd = r"C:\Users\Ada\projects\claude-tools\note-keeping"
        cube = build_cube({slug(cwd): [rec("2026-07-01T10:00:00Z", cwd=cwd)]})
        self.assertEqual(cube["project_paths"],
                         ["C:/Users/Ada/projects/claude-tools/note-keeping"])

    def test_a_cd_into_a_subfolder_does_not_rename_the_project(self):
        root = r"C:\Users\Ada\my-app"
        cube = build_cube({slug(root): [
            rec("2026-07-01T10:00:00Z", cwd=root + r"\src\web-ui"),
            rec("2026-07-01T10:05:00Z", cwd=root + r"\src\web-ui"),
            rec("2026-07-01T10:10:00Z", cwd=root)]})
        self.assertEqual(cube["project_paths"], ["C:/Users/Ada/my-app"])

    def test_a_moved_folder_resolves_against_the_disk(self):
        # The transcripts were recorded under an old path, then the folder (and
        # its transcript folder) moved: no cwd encodes to the folder name.
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp).resolve() / "claude-tools" / "my-repo"
            real.mkdir(parents=True)
            cube = build_cube({slug(real): [
                rec("2026-07-01T10:00:00Z", cwd=r"C:\old\ai\my-repo")]})
        self.assertEqual(cube["project_paths"], [real.as_posix()])

    def test_a_vanished_tail_keeps_the_part_that_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp).resolve() / "claude-tools"
            real.mkdir()
            cube = build_cube({slug(real) + "-gone-dir": [
                rec("2026-07-01T10:00:00Z")]})
        self.assertEqual(cube["project_paths"], [real.as_posix() + "/gone/dir"])

    def test_a_folder_that_is_not_a_path_gets_an_empty_path(self):
        cube = build_cube({"proj-a": [rec("2026-07-01T10:00:00Z")]})
        self.assertEqual(cube["project_paths"], [""])


def title_line(session, kind, text):
    key = "aiTitle" if kind == "ai-title" else "customTitle"
    return json.dumps({"type": kind, key: text, "sessionId": session})


def prompt_line(session, content, **extra):
    line = {"type": "user", "sessionId": session, "timestamp": "2026-07-01T09:59:00Z",
            "message": {"role": "user", "content": content}}
    line.update(extra)
    return json.dumps(line)


class TestSessionTitles(unittest.TestCase):
    """extras.sessions.all rows carry [.., title, isFallback]."""

    def _row(self, lines, session="s1"):
        cube = build_cube({"proj-a": [rec("2026-07-01T10:00:00Z", session=session)] + lines})
        return next(r for r in cube["extras"]["sessions"]["all"] if r[0] == session)

    def test_latest_ai_title_wins(self):
        row = self._row([title_line("s1", "ai-title", "Draft idea"),
                         title_line("s1", "ai-title", "WSL2 setup")])
        self.assertEqual(row[6:8], ["WSL2 setup", 0])

    def test_custom_title_beats_ai_title(self):
        row = self._row([title_line("s1", "custom-title", "Alpaca tokens"),
                         title_line("s1", "ai-title", "WSL2 setup")])
        self.assertEqual(row[6:8], ["Alpaca tokens", 0])

    def test_untitled_session_falls_back_to_its_first_real_prompt(self):
        row = self._row([
            prompt_line("s1", "Caveat: local command output follows", isMeta=True),
            prompt_line("s1", [{"type": "tool_result", "content": "x"}]),
            prompt_line("s1", "Which port does it use?"),
            prompt_line("s1", "a later prompt")])
        self.assertEqual(row[6:8], ["Which port does it use?", 1])

    def test_slash_command_prompt_reads_as_the_command(self):
        row = self._row([prompt_line(
            "s1", "<command-message>nk:load</command-message>\n"
                  "<command-name>/nk:load</command-name>\n<command-args>0021</command-args>")])
        self.assertEqual(row[6:8], ["/nk:load 0021", 1])

    def test_long_prompt_is_cut_to_a_few_words(self):
        row = self._row([prompt_line("s1", "please check the sessions list in this app for me")])
        self.assertEqual(row[6], "please check the sessions list in\u2026")

    def test_untitled_session_without_prompts_has_an_empty_title(self):
        self.assertEqual(self._row([])[6:8], ["", 0])

    def test_a_title_cannot_close_the_page_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "p").mkdir()
            (root / "p" / "t.jsonl").write_text("\n".join([
                rec("2026-07-01T10:00:00Z"),
                title_line("s1", "ai-title", "fix </script> tag")]), encoding="utf-8")
            out = root / "cube.json"
            subprocess.run([sys.executable, str(EMIT)], check=True, capture_output=True,
                           env=dict(os.environ, CLAUDE_USAGE_ROOT=str(root),
                                    CLAUDE_USAGE_OUT=str(out), CLAUDE_USAGE_TZ_OFFSET="0"))
            raw = out.read_text(encoding="utf-8")
        self.assertNotIn("</script>", raw)
        self.assertIn("fix </script> tag", json.dumps(json.loads(raw)))


if __name__ == "__main__":
    unittest.main()
