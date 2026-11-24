import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "measure"))
import measure_task as mt  # noqa: E402

PRICES = mt.load_prices(Path(__file__).resolve().parents[1] / "measure" / "prices.json")
SESSION = "11111111-2222-3333-4444-555555555555"


def assistant(msg_id, req_id, model, ts, usage):
    return {"type": "assistant", "requestId": req_id, "timestamp": ts,
            "message": {"id": msg_id, "model": model, "usage": usage}}


def write_jsonl(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


class TranscriptCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_env = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name
        self.addCleanup(self.restore_env)
        project = Path(self.tmp.name) / "projects" / "C--work-demo"
        req1 = assistant("m1", "r1", "claude-opus-5-5", "2026-11-24T10:00:00Z", {
            "input_tokens": 10, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 0,
            "output_tokens": 100,
            "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 1000}})
        write_jsonl(project / f"{SESSION}.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
            {"type": "user", "message": {"role": "user", "content": "fix the login bug"}},
            req1,
            req1,  # same request written twice: must count once
            assistant("m2", "r2", "claude-opus-5-5", "2026-11-24T10:05:00Z", {
                "input_tokens": 5, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 1000,
                "output_tokens": 50,
                "cache_creation": {"ephemeral_5m_input_tokens": 200, "ephemeral_1h_input_tokens": 0}}),
            assistant("m9", "r9", "<synthetic>", "2026-11-24T10:06:00Z", {
                "input_tokens": 0, "output_tokens": 0}),
            {"type": "custom-title", "customTitle": "Login bug"},
        ])
        write_jsonl(project / SESSION / "subagents" / "agent-abc.jsonl", [
            assistant("m3", "r3", "claude-sonnet-5-5", "2026-11-24T10:02:00Z", {
                "input_tokens": 20, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 500,
                "output_tokens": 30}),  # no split: priced as 5-minute write
        ])
        self.main_file = project / f"{SESSION}.jsonl"

    def restore_env(self):
        if self.old_env is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old_env

    def test_counts_each_request_once_and_includes_subagents(self):
        m = mt.measure(self.main_file, PRICES)
        self.assertEqual(m.total.requests, 3)
        self.assertEqual(m.main.requests, 2)
        self.assertEqual(m.subagents.requests, 1)
        self.assertEqual(m.total.input, 35)
        self.assertEqual(m.total.cache_write_1h, 1000)
        self.assertEqual(m.total.cache_write_5m, 300)
        self.assertEqual(m.total.cache_read, 1500)
        self.assertEqual(m.total.output, 180)
        self.assertEqual(m.title, "Login bug")

    def test_cost_uses_per_model_cache_read_and_write_multipliers(self):
        m = mt.measure(self.main_file, PRICES)
        # opus: 15*4 + 150*20 + 1000*8 (1h = 2x) + 200*5 (5m = 1.25x) + 1000*0.20 = 12260
        self.assertAlmostEqual(m.by_model["claude-opus-5-5"].cost, 12260 / 1e6)
        # sonnet: 20*2 + 30*10 + 500*0.10 + 100*2.5 = 640
        self.assertAlmostEqual(m.by_model["claude-sonnet-5-5"].cost, 640 / 1e6)
        self.assertAlmostEqual(m.total.cost, 12900 / 1e6)
        self.assertTrue(m.total.cost_known)
        # output: 150*20 + 30*10 = 3300; 1h writes: 1000*8 = 8000
        self.assertAlmostEqual(m.total.class_cost["output"], 3300 / 1e6)
        self.assertAlmostEqual(m.total.class_cost["cache_write_1h"], 8000 / 1e6)
        self.assertAlmostEqual(sum(m.total.class_cost.values()), m.total.cost)

    def test_context_and_cache_share(self):
        m = mt.measure(self.main_file, PRICES)
        self.assertEqual(m.first_context, 1010)
        self.assertEqual(m.max_context, 1205)
        self.assertAlmostEqual(m.mean_context, (1010 + 1205) / 2)
        self.assertAlmostEqual(m.total.cache_hit, 1500 / 2835)

    def test_time_window(self):
        since = mt.parse_time("2026-11-24T10:01:00Z")
        m = mt.measure(self.main_file, PRICES, since=since)
        self.assertEqual(m.total.requests, 2)

    def test_find_session_by_prefix(self):
        found = mt.find_session("11111111", mt.projects_root())
        self.assertEqual(found, self.main_file)

    def test_first_prompt_skips_command_markup(self):
        entries = [{"type": "user", "message": {"content": "<command-name>/clear</command-name>"}},
                   {"type": "user", "message": {"content": [{"type": "text", "text": "real ask"}]}}]
        texts = [mt.first_user_text(e) for e in entries]
        self.assertEqual(texts, [None, "real ask"])


class PricingCase(unittest.TestCase):
    def test_long_context_tier(self):
        usage = mt.Usage(requests=1, input=150_000, output=10)
        cost, known = mt.price_request("claude-haiku-5-5", usage, PRICES)
        self.assertTrue(known)
        self.assertAlmostEqual(cost, (150_000 * 0.50 + 10 * 2.50) / 1e6)

    def test_missing_cache_read_price_is_unknown_not_guessed(self):
        usage = mt.Usage(requests=1, input=10, cache_read=500, output=10)
        cost, known = mt.price_request("claude-haiku-5-5", usage, PRICES)
        self.assertFalse(known)

    def test_unknown_model(self):
        cost, known = mt.price_request("some-model", mt.Usage(requests=1, input=1), PRICES)
        self.assertFalse(known)


class CompareCase(unittest.TestCase):
    @staticmethod
    def attempt(task, phase, completed, cost, output=100):
        return {"task": task, "phase": phase, "completed": completed, "measurement": {
            "requests": 10, "input": 0, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 1000,
            "output": output, "cost": cost, "cost_known": True, "max_context": 5000}}

    def test_cost_per_completed_task_counts_failed_attempts(self):
        registry = {"attempts": [
            self.attempt("A", "before", False, 1.0),
            self.attempt("A", "before", True, 1.0),
            self.attempt("B", "before", True, 2.0),
            self.attempt("A", "after", True, 0.5),
            self.attempt("B", "after", True, 1.0),
        ]}
        result = mt.compare(registry, None, None)
        self.assertAlmostEqual(result["phases"]["before"]["cost_per_task"], 2.0)
        self.assertAlmostEqual(result["phases"]["after"]["cost_per_task"], 0.75)
        self.assertAlmostEqual(result["change"]["cost_per_task"], -0.625)
        self.assertEqual(result["only_in"], {"before": [], "after": []})
        spread = result["phases"]["before"]["attempt_cost"]
        self.assertAlmostEqual(spread["mean"], 4 / 3)
        self.assertAlmostEqual(spread["sd"], (1 / 3) ** 0.5)  # sample sd of 1, 1, 2
        self.assertEqual((spread["median"], spread["min"], spread["max"]), (1.0, 1.0, 2.0))

    def test_independent_repeats_each_count_as_a_completed_task(self):
        registry = {"attempts": [self.attempt("A", "base", True, 1.0), self.attempt("A", "base", True, 3.0)]}
        summary = mt.compare(registry, None, None)["phases"]["base"]
        self.assertEqual(summary["completed"], 2)
        self.assertAlmostEqual(summary["cost_per_task"], 2.0)
        self.assertAlmostEqual(summary["attempt_cost"]["median"], 2.0)

    def test_flags_tasks_present_in_one_phase_only(self):
        registry = {"attempts": [self.attempt("A", "before", True, 1.0),
                                 self.attempt("B", "after", True, 1.0)]}
        result = mt.compare(registry, "before", "after")
        self.assertEqual(result["only_in"], {"before": ["A"], "after": ["B"]})

    def test_record_then_compare_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "m.json"
            mt.save_registry(registry, {"version": 1, "attempts": [
                self.attempt("A", "before", True, 1.0), self.attempt("A", "after", True, 0.25)]})
            out = io.StringIO()
            with redirect_stdout(out):
                mt.main(["--lang", "en", "compare", "--registry", str(registry)])
            text = out.getvalue()
            self.assertIn("Cost per completed task", text)
            self.assertIn("-75.0%", text)


def tool_line(msg_id, req_id, ts, blocks):
    usage = {"input_tokens": 1, "cache_read_input_tokens": 100, "output_tokens": 10}
    return {"type": "assistant", "requestId": req_id, "timestamp": ts,
            "message": {"id": msg_id, "model": "claude-opus-5-5", "usage": usage, "content": blocks}}


def call(call_id, name, **args):
    return {"type": "tool_use", "id": call_id, "name": name, "input": args}


class ToolTrailCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        project = Path(self.tmp.name) / "projects" / "C--work-demo"
        first = tool_line("m1", "r1", "2026-11-24T10:00:00Z",
                          [{"type": "text", "text": "vou ler"}, call("t1", "Read", file_path="/p/schema.yaml")])
        write_jsonl(project / f"{SESSION}.jsonl", [
            first,
            first,  # the same line twice: the call counts once
            # the same answer goes on: another block of message m1 on its own line
            tool_line("m1", "r1", "2026-11-24T10:00:00Z", [call("t2", "Grep", pattern="projeto")]),
            tool_line("m2", "r2", "2026-11-24T10:01:00Z", [
                call("t3", "Read", file_path="/p/notas.md", offset=10, limit=40),
                call("t4", "Agent", subagent_type="Explore", prompt="leia"),
                call("t5", "Bash", command="ls"),
                call("t6", "WebFetch", url="https://example.com"),
            ]),
            tool_line("m3", "r3", "2026-11-24T10:10:00Z", [call("t9", "Read", file_path="/p/tarde.md")]),
        ])
        write_jsonl(project / SESSION / "subagents" / "agent-x.jsonl", [
            tool_line("s1", "q1", "2026-11-24T10:02:00Z", [call("t7", "Read", file_path="/p/schema.yaml"),
                                                           call("t8", "Glob", pattern="*.md")]),
        ])
        self.main_file = project / f"{SESSION}.jsonl"

    def test_counts_kinds_per_side_once_each(self):
        until = mt.parse_time("2026-11-24T10:05:00Z")
        trail = mt.collect_tools(self.main_file, until=until)
        main, sub = trail["main"], trail["subagents"]
        self.assertEqual((main["read_full"], main["read_partial"], main["grep"]), (1, 1, 1))
        self.assertEqual((main["subagent"], main["shell"], main["other"]), (1, 1, 1))
        self.assertEqual(trail["other_names"], {"WebFetch": 1})
        self.assertEqual((sub["read_full"], sub["glob"]), (1, 1))
        self.assertEqual(trail["read_full_files"], {"/p/schema.yaml": 2})

    def test_time_window_applies_to_tools(self):
        trail = mt.collect_tools(self.main_file)
        self.assertEqual(trail["main"]["read_full"], 2)
        self.assertIn("/p/tarde.md", trail["read_full_files"])

    def test_snapshot_keeps_counts_without_paths(self):
        m = mt.measure(self.main_file, PRICES, until=mt.parse_time("2026-11-24T10:05:00Z"))
        snap = mt.snapshot(m)
        self.assertEqual(snap["tools"]["main"]["read_full"], 1)
        self.assertEqual(snap["tools"]["subagents"]["glob"], 1)
        self.assertNotIn("schema.yaml", json.dumps(snap))

    def test_rendered_trail_and_phase_metric(self):
        m = mt.measure(self.main_file, PRICES, until=mt.parse_time("2026-11-24T10:05:00Z"))
        text = mt.render_measurement(m, mt.LABELS["pt"])
        self.assertIn("Ferramentas na conversa principal: Read inteiro 1 · Read de trecho 1 · Grep 1", text)
        self.assertIn("Ferramentas nos subagentes: Read inteiro 1 · Glob 1", text)
        self.assertIn("Lidos inteiros: schema.yaml ×2", text)
        attempt = {"task": "a", "completed": True, "measurement": mt.snapshot(m)}
        self.assertEqual(mt.phase_summary([attempt, dict(attempt)])["read_full_per_task"], 2.0)

    def test_old_records_without_trail_give_no_read_metric(self):
        m = mt.measure(self.main_file, PRICES)
        old = mt.snapshot(m)
        old.pop("tools")
        self.assertIsNone(mt.phase_summary([{"task": "a", "completed": True, "measurement": old}])
                          ["read_full_per_task"])


if __name__ == "__main__":
    unittest.main()
