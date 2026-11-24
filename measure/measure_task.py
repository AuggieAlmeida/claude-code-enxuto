#!/usr/bin/env python3
"""Measure Claude Code consumption per task and compare before/after.

Reads the local transcripts Claude Code writes under ~/.claude/projects
(or $CLAUDE_CONFIG_DIR/projects). One session = the main transcript plus every
subagent transcript under <session>/subagents/. Usage is counted once per API
request (deduplicated by message id + request id), split into regular input,
5-minute cache writes, 1-hour cache writes, cache reads and output, and priced
per request with prices.json.

The unit that matters is cost per *completed* task: record every attempt of a
task (including the ones that failed) with `record`, then `compare` divides the
phase's total cost by the number of tasks that got done.

Commands:
    list      recent sessions of a project (default: current directory)
    measure   one session, optionally limited to a time window, with its tool trail
              (whole-file reads, partial reads, searches, subagent calls)
    record    store a session's measurement in a registry file
    compare   cost per completed task, phase against phase

Python 3.9+, standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PRICES = Path(__file__).with_name("prices.json")
DEFAULT_REGISTRY = Path("measurements.json")
TOKEN_FIELDS = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
CACHE_WRITE_MULT = {"cache_write_5m": 1.25, "cache_write_1h": 2.0}

LABELS = {
    "pt": {
        "session": "Sessão", "title": "Título", "start": "Início", "duration": "Duração",
        "requests": "Requisições", "cost": "Custo (US$)", "model": "Modelo",
        "input": "Entrada", "cache_write_5m": "Cache grav. 5 min", "cache_write_1h": "Cache grav. 1 h",
        "cache_read": "Cache lido", "output": "Saída", "total": "Total", "main": "Conversa principal",
        "subagents": "Subagentes", "cache_hit": "Leitura de cache", "max_context": "Maior contexto",
        "mean_context": "Contexto médio", "unknown": "desconhecido", "partial": "parcial",
        "phase": "Fase", "attempts": "Tentativas", "tasks": "Tarefas", "completed": "Tentativas concluídas",
        "cost_per_task": "Custo por tarefa concluída", "prompt_per_task": "Tokens de entrada por tarefa concluída",
        "output_per_task": "Tokens de saída por tarefa concluída", "requests_per_task": "Requisições por tarefa concluída",
        "mean_max_context": "Maior contexto médio", "change": "Variação",
        "only_in": "Tarefas só na fase", "missing_prices": "Sem preço (custo fica desconhecido)",
        "recorded": "Registrado", "no_sessions": "Nenhuma sessão encontrada em",
        "cost_split": "Custo por classe (só requisições com preço)",
        "first_context": "Contexto na primeira requisição",
        "attempt_cost": "Custo por tentativa (média ± desvio · mediana, mín–máx)",
        "tools_main": "Ferramentas na conversa principal", "tools_sub": "Ferramentas nos subagentes",
        "read_full": "Read inteiro", "read_partial": "Read de trecho", "grep": "Grep", "glob": "Glob",
        "subagent": "Subagente", "shell": "Shell", "edit": "Edição", "other": "Outras",
        "read_full_files": "Lidos inteiros", "read_full_per_task": "Leituras inteiras por tarefa concluída",
    },
    "en": {
        "session": "Session", "title": "Title", "start": "Start", "duration": "Duration",
        "requests": "Requests", "cost": "Cost (USD)", "model": "Model",
        "input": "Input", "cache_write_5m": "Cache write 5 min", "cache_write_1h": "Cache write 1 h",
        "cache_read": "Cache read", "output": "Output", "total": "Total", "main": "Main thread",
        "subagents": "Subagents", "cache_hit": "Cache read share", "max_context": "Largest context",
        "mean_context": "Mean context", "unknown": "unknown", "partial": "partial",
        "phase": "Phase", "attempts": "Attempts", "tasks": "Tasks", "completed": "Completed attempts",
        "cost_per_task": "Cost per completed task", "prompt_per_task": "Input tokens per completed task",
        "output_per_task": "Output tokens per completed task", "requests_per_task": "Requests per completed task",
        "mean_max_context": "Mean largest context", "change": "Change",
        "only_in": "Tasks only in phase", "missing_prices": "No price (cost stays unknown)",
        "recorded": "Recorded", "no_sessions": "No sessions found in",
        "cost_split": "Cost by token class (priced requests only)",
        "first_context": "Context on the first request",
        "attempt_cost": "Cost per attempt (mean ± sd · median, min–max)",
        "tools_main": "Tools in the main thread", "tools_sub": "Tools in subagents",
        "read_full": "Whole-file Read", "read_partial": "Partial Read", "grep": "Grep", "glob": "Glob",
        "subagent": "Subagent", "shell": "Shell", "edit": "Edit", "other": "Other",
        "read_full_files": "Read whole", "read_full_per_task": "Whole-file reads per completed task",
    },
}


# ── Data ─────────────────────────────────────────────────────────────────────


@dataclass
class Usage:
    requests: int = 0
    input: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0
    output: int = 0
    cost: float = 0.0
    cost_known: bool = True
    class_cost: dict[str, float] = field(default_factory=dict)

    def add(self, other: "Usage") -> None:
        self.requests += other.requests
        for name in TOKEN_FIELDS:
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.cost += other.cost
        self.cost_known = self.cost_known and other.cost_known
        for name, value in other.class_cost.items():
            self.class_cost[name] = self.class_cost.get(name, 0.0) + value

    @property
    def prompt_tokens(self) -> int:
        return self.input + self.cache_write_5m + self.cache_write_1h + self.cache_read

    @property
    def cache_hit(self) -> float | None:
        return self.cache_read / self.prompt_tokens if self.prompt_tokens else None


@dataclass
class Request:
    thread: str  # "main" or the subagent id
    model: str
    timestamp: datetime
    usage: Usage


@dataclass
class Measurement:
    session: str
    title: str
    start: str | None
    end: str | None
    total: Usage
    main: Usage
    subagents: Usage
    by_model: dict[str, Usage] = field(default_factory=dict)
    first_context: int = 0
    max_context: int = 0
    mean_context: float = 0.0
    missing_prices: list[str] = field(default_factory=list)
    tools: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = asdict(self)
        out["total"]["cache_hit"] = self.total.cache_hit
        return out


# ── Locating transcripts ─────────────────────────────────────────────────────


def projects_root() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


def project_slug(path: Path) -> str:
    """Claude Code names a project folder after its path, non-alphanumerics as '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path.resolve()))


def find_session(session: str, root: Path) -> Path:
    matches = sorted(p for p in root.glob(f"*/{session}*.jsonl") if p.is_file())
    exact = [p for p in matches if p.stem == session]
    if exact:
        return exact[0]
    if not matches:
        raise SystemExit(f"session not found: {session} (looked in {root})")
    if len(matches) > 1:
        names = ", ".join(p.stem for p in matches[:5])
        raise SystemExit(f"ambiguous session prefix {session}: {names}")
    return matches[0]


def session_files(main_file: Path) -> list[tuple[str, Path]]:
    files = [("main", main_file)]
    sub_dir = main_file.with_suffix("") / "subagents"
    for sub in sorted(sub_dir.glob("*.jsonl")):
        files.append((sub.stem.removeprefix("agent-"), sub))
    return files


# ── Prices ───────────────────────────────────────────────────────────────────


def load_prices(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("models", {})


def request_rates(model_prices: dict, prompt_tokens: int) -> dict[str, float | None]:
    tier = {k: v for k, v in model_prices.items() if not k.startswith("_")}
    long_ctx = tier.pop("long_context", None)
    if long_ctx and prompt_tokens > long_ctx.get("above_prompt_tokens", float("inf")):
        # The long-context tier replaces the base rates; explicit cache-write
        # prices of the base tier no longer apply.
        tier.pop("cache_write_5m", None)
        tier.pop("cache_write_1h", None)
        tier.pop("cache_read", None)
        tier.update({k: v for k, v in long_ctx.items() if k != "above_prompt_tokens"})
    rates: dict[str, float | None] = {
        "input": tier.get("input"),
        "output": tier.get("output"),
        "cache_read": tier.get("cache_read"),
    }
    for name, mult in CACHE_WRITE_MULT.items():
        if name in tier:
            rates[name] = tier[name]
        else:
            rates[name] = tier["input"] * mult if tier.get("input") is not None else None
    return rates


def price_classes(model: str, usage: Usage, prices: dict) -> dict[str, float] | None:
    """Cost in USD per token class, or None when a token class used has no price."""
    if model not in prices:
        return None if any(getattr(usage, f) for f in TOKEN_FIELDS) else {}
    rates = request_rates(prices[model], usage.prompt_tokens)
    costs: dict[str, float] = {}
    for name in TOKEN_FIELDS:
        tokens = getattr(usage, name)
        if not tokens:
            continue
        rate = rates.get(name)
        if rate is None:
            return None
        costs[name] = tokens * rate / 1_000_000
    return costs


def price_request(model: str, usage: Usage, prices: dict) -> tuple[float, bool]:
    """(cost in USD, known). Unknown when a token class used has no price."""
    costs = price_classes(model, usage, prices)
    return (0.0, False) if costs is None else (sum(costs.values()), True)


# ── Parsing ──────────────────────────────────────────────────────────────────


def parse_time(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if moment.tzinfo is None:
        moment = moment.astimezone()  # naive input = local time
    return moment


def usage_from(raw: dict) -> Usage:
    split = raw.get("cache_creation") or {}
    if split:
        write_5m = split.get("ephemeral_5m_input_tokens", 0) or 0
        write_1h = split.get("ephemeral_1h_input_tokens", 0) or 0
    else:  # older transcripts: no split, priced as 5-minute writes
        write_5m = raw.get("cache_creation_input_tokens", 0) or 0
        write_1h = 0
    return Usage(
        requests=1,
        input=raw.get("input_tokens", 0) or 0,
        cache_write_5m=write_5m,
        cache_write_1h=write_1h,
        cache_read=raw.get("cache_read_input_tokens", 0) or 0,
        output=raw.get("output_tokens", 0) or 0,
    )


def read_lines(path: Path):
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def first_user_text(entry: dict) -> str | None:
    if entry.get("isMeta"):
        return None
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        content = " ".join(texts)
    if not isinstance(content, str):
        return None
    content = content.strip()
    if not content or content.startswith("<"):
        return None
    return content


def collect(main_file: Path, since: datetime | None = None, until: datetime | None = None,
            prices: dict | None = None) -> tuple[list[Request], str]:
    prices = prices or {}
    seen: set[tuple] = set()
    requests: list[Request] = []
    custom_title = last_prompt = first_prompt = None
    for thread, path in session_files(main_file):
        for entry in read_lines(path):
            kind = entry.get("type")
            if thread == "main":
                if kind == "custom-title" and entry.get("customTitle"):
                    custom_title = entry["customTitle"]
                elif kind == "last-prompt" and entry.get("lastPrompt"):
                    last_prompt = entry["lastPrompt"]
                elif kind == "user" and first_prompt is None:
                    first_prompt = first_user_text(entry)
            if kind != "assistant":
                continue
            message = entry.get("message") or {}
            raw = message.get("usage")
            if not raw:
                continue
            key = (message.get("id"), entry.get("requestId"))
            if key in seen:
                continue
            seen.add(key)
            moment = parse_time(entry.get("timestamp", ""))
            if moment is None:
                continue
            if (since and moment < since) or (until and moment > until):
                continue
            usage = usage_from(raw)
            if not any(getattr(usage, f) for f in TOKEN_FIELDS):
                continue  # synthetic or empty entries
            model = message.get("model") or "unknown"
            costs = price_classes(model, usage, prices)
            usage.cost_known = costs is not None
            usage.class_cost = costs or {}
            usage.cost = sum(usage.class_cost.values())
            requests.append(Request(thread, model, moment, usage))
    title = custom_title or last_prompt or first_prompt or ""
    return requests, title


TOOL_KINDS = ("read_full", "read_partial", "grep", "glob", "subagent", "shell", "edit", "other")
SUBAGENT_TOOLS = {"Agent", "Task"}
SHELL_TOOLS = {"Bash", "PowerShell"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def classify_tool(name: str, args: dict) -> str:
    """Kind of a tool call. A Read without offset, limit or pages reads the whole file."""
    if name == "Read":
        partial = any(args.get(k) not in (None, "") for k in ("offset", "limit", "pages"))
        return "read_partial" if partial else "read_full"
    if name in ("Grep", "Glob"):
        return name.lower()
    if name in SUBAGENT_TOOLS:
        return "subagent"
    if name in SHELL_TOOLS:
        return "shell"
    if name in EDIT_TOOLS:
        return "edit"
    return "other"


def collect_tools(main_file: Path, since: datetime | None = None, until: datetime | None = None) -> dict:
    """Tool calls of a session, main thread and subagents counted apart.

    Claude Code writes each content block of an answer on its own line, repeating the
    message id, so calls are deduplicated by their own id, not by the request.
    """
    trail = {"main": dict.fromkeys(TOOL_KINDS, 0), "subagents": dict.fromkeys(TOOL_KINDS, 0),
             "other_names": {}, "read_full_files": {}}
    seen: set[str] = set()
    for thread, path in session_files(main_file):
        side = "main" if thread == "main" else "subagents"
        for entry in read_lines(path):
            if entry.get("type") != "assistant":
                continue
            content = (entry.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            moment = parse_time(entry.get("timestamp", ""))
            if moment is None or (since and moment < since) or (until and moment > until):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                call_id = block.get("id") or f"{thread}:{json.dumps(block, sort_keys=True)}"
                if call_id in seen:
                    continue
                seen.add(call_id)
                name = block.get("name") or "?"
                args = block.get("input") if isinstance(block.get("input"), dict) else {}
                kind = classify_tool(name, args)
                trail[side][kind] += 1
                if kind == "other":
                    trail["other_names"][name] = trail["other_names"].get(name, 0) + 1
                if kind == "read_full" and args.get("file_path"):
                    file_path = str(args["file_path"])
                    trail["read_full_files"][file_path] = trail["read_full_files"].get(file_path, 0) + 1
    return trail


def measure(main_file: Path, prices: dict, since=None, until=None) -> Measurement:
    requests, title = collect(main_file, since, until, prices)
    total, main, subagents = Usage(), Usage(), Usage()
    by_model: dict[str, Usage] = {}
    missing: set[str] = set()
    main_contexts: list[int] = []
    for req in requests:
        total.add(req.usage)
        (main if req.thread == "main" else subagents).add(req.usage)
        by_model.setdefault(req.model, Usage()).add(req.usage)
        if not req.usage.cost_known:
            missing.add(req.model)
        if req.thread == "main":
            main_contexts.append(req.usage.prompt_tokens)
    times = sorted(r.timestamp for r in requests)
    return Measurement(
        session=main_file.stem,
        title=title,
        start=times[0].isoformat() if times else None,
        end=times[-1].isoformat() if times else None,
        total=total,
        main=main,
        subagents=subagents,
        by_model=dict(sorted(by_model.items())),
        first_context=main_contexts[0] if main_contexts else 0,
        max_context=max(main_contexts, default=0),
        mean_context=sum(main_contexts) / len(main_contexts) if main_contexts else 0.0,
        missing_prices=sorted(missing),
        tools=collect_tools(main_file, since, until),
    )


# ── Registry and comparison ──────────────────────────────────────────────────


def load_registry(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"version": 1, "attempts": []}


def save_registry(path: Path, registry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def snapshot(m: Measurement) -> dict:
    t = m.total
    return {
        "requests": t.requests,
        "input": t.input,
        "cache_write_5m": t.cache_write_5m,
        "cache_write_1h": t.cache_write_1h,
        "cache_read": t.cache_read,
        "output": t.output,
        "cost": round(t.cost, 6),
        "cost_known": t.cost_known,
        "class_cost": {k: round(v, 6) for k, v in t.class_cost.items()},
        "first_context": m.first_context,
        "max_context": m.max_context,
        "start": m.start,
        "end": m.end,
        # counts only: file paths stay out of the registry
        "tools": {side: dict(m.tools.get(side, {})) for side in ("main", "subagents")},
    }


def phase_summary(attempts: list[dict]) -> dict:
    """Cost per completed task = cost of every attempt / attempts that completed.

    Failed attempts add cost and no completion, so retries are charged to the
    task that eventually got done; independent repeats each count once.
    """
    tasks = {a["task"] for a in attempts}
    completed_tasks = {a["task"] for a in attempts if a["completed"]}
    completed_attempts = sum(1 for a in attempts if a["completed"])
    total = Usage()
    for a in attempts:
        s = a["measurement"]
        total.add(Usage(
            requests=s["requests"], input=s["input"], cache_write_5m=s["cache_write_5m"],
            cache_write_1h=s["cache_write_1h"], cache_read=s["cache_read"], output=s["output"],
            cost=s["cost"], cost_known=s["cost_known"],
        ))
    n = completed_attempts
    trails = [a["measurement"].get("tools") for a in attempts]
    read_full = (sum(t.get(side, {}).get("read_full", 0) for t in trails for side in ("main", "subagents"))
                 if trails and all(trails) else None)
    contexts = [a["measurement"]["max_context"] for a in attempts]
    costs = sorted(a["measurement"]["cost"] for a in attempts)
    spread = None
    if len(costs) > 1:
        mean = sum(costs) / len(costs)
        sd = (sum((c - mean) ** 2 for c in costs) / (len(costs) - 1)) ** 0.5
        mid = len(costs) // 2
        median = costs[mid] if len(costs) % 2 else (costs[mid - 1] + costs[mid]) / 2
        spread = {"mean": mean, "sd": sd, "median": median, "min": costs[0], "max": costs[-1]}
    return {
        "attempt_cost": spread,
        "attempts": len(attempts),
        "tasks": sorted(tasks),
        "completed": completed_attempts,
        "completed_tasks": sorted(completed_tasks),
        "cost": total.cost,
        "cost_known": total.cost_known,
        "cost_per_task": total.cost / n if n else None,
        "prompt_per_task": total.prompt_tokens / n if n else None,
        "output_per_task": total.output / n if n else None,
        "requests_per_task": total.requests / n if n else None,
        "cache_hit": total.cache_hit,
        "mean_max_context": sum(contexts) / len(contexts) if contexts else None,
        "read_full_per_task": read_full / n if n and read_full is not None else None,
    }


def compare(registry: dict, before: str | None, after: str | None) -> dict:
    phases: dict[str, list[dict]] = {}
    for a in registry.get("attempts", []):
        phases.setdefault(a["phase"], []).append(a)
    order = list(phases)
    before = before or (order[0] if order else None)
    after = after or (order[1] if len(order) > 1 else None)
    result = {"phases": {name: phase_summary(items) for name, items in phases.items()},
              "before": before, "after": after, "change": {}, "only_in": {}}
    if before in phases and after in phases:
        b, a = result["phases"][before], result["phases"][after]
        for metric in ("cost_per_task", "prompt_per_task", "output_per_task", "requests_per_task",
                       "cache_hit", "mean_max_context", "read_full_per_task"):
            if b[metric] and a[metric] is not None:
                result["change"][metric] = (a[metric] - b[metric]) / b[metric]
        result["only_in"] = {
            before: sorted(set(b["tasks"]) - set(a["tasks"])),
            after: sorted(set(a["tasks"]) - set(b["tasks"])),
        }
    return result


# ── Formatting ───────────────────────────────────────────────────────────────


def fmt_int(n) -> str:
    return "—" if n is None else f"{round(n):,}"


def fmt_cost(value: float, known: bool, L: dict) -> str:
    if known:
        return f"{value:.4f}"
    return f"{value:.4f} ({L['partial']})" if value else L["unknown"]


def fmt_pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def fmt_duration(start: str | None, end: str | None) -> str:
    if not (start and end):
        return "—"
    seconds = int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    hours, rest = divmod(seconds, 3600)
    return f"{hours}h{rest // 60:02d}" if hours else f"{rest // 60} min"


def table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def render_measurement(m: Measurement, L: dict) -> str:
    def row(name: str, u: Usage) -> list[str]:
        return [name, fmt_int(u.requests)] + [fmt_int(getattr(u, f)) for f in TOKEN_FIELDS] + \
               [fmt_cost(u.cost, u.cost_known, L)]

    headers = [L["model"], L["requests"]] + [L[f] for f in TOKEN_FIELDS] + [L["cost"]]
    rows = [row(model, u) for model, u in m.by_model.items()]
    rows.append(row(f"**{L['total']}**", m.total))
    split = [row(L["main"], m.main), row(L["subagents"], m.subagents)]
    parts = [
        f"## {L['session']} {m.session}",
        f"{L['title']}: {m.title or '—'}  ",
        f"{L['start']}: {m.start or '—'} · {L['duration']}: {fmt_duration(m.start, m.end)}",
        "",
        table(headers, rows),
        "",
        table(headers, split),
        "",
        f"- {L['cost_split']}: " + (" · ".join(
            f"{L[name]} {fmt_pct(m.total.class_cost.get(name, 0.0) / m.total.cost)}"
            for name in TOKEN_FIELDS) if m.total.cost else "—"),
        f"- {L['cache_hit']}: {fmt_pct(m.total.cache_hit)}",
        f"- {L['first_context']}: {fmt_int(m.first_context)} · {L['max_context']}: {fmt_int(m.max_context)}"
        f" · {L['mean_context']}: {fmt_int(m.mean_context)}",
    ]
    if m.missing_prices:
        parts.append(f"- {L['missing_prices']}: {', '.join(m.missing_prices)}")
    parts += render_tools(m.tools, L)
    return "\n".join(parts)


def render_tools(trail: dict, L: dict) -> list[str]:
    if not trail:
        return []

    def counts(side: str) -> str:
        items = [f"{L[k]} {v}" for k, v in trail.get(side, {}).items() if v]
        return " · ".join(items) or "—"

    lines = [f"- {L['tools_main']}: {counts('main')}"]
    if any(trail.get("subagents", {}).values()):
        lines.append(f"- {L['tools_sub']}: {counts('subagents')}")
    if trail.get("other_names"):
        lines.append(f"- {L['other']}: " + ", ".join(f"{k} {v}" for k, v in sorted(trail["other_names"].items())))
    files = sorted(trail.get("read_full_files", {}).items(), key=lambda kv: (-kv[1], kv[0]))
    if files:
        shown = ", ".join(f"{Path(f).name} ×{n}" for f, n in files[:5])
        more = f" (+{len(files) - 5})" if len(files) > 5 else ""
        lines.append(f"- {L['read_full_files']}: {shown}{more}")
    return lines


def render_comparison(result: dict, L: dict) -> str:
    names = list(result["phases"])
    metrics = [
        ("attempts", fmt_int), ("tasks", lambda v: str(len(v))), ("completed", fmt_int),
        ("cost_per_task", lambda v: "—" if v is None else f"{v:.4f}"),
        ("prompt_per_task", fmt_int), ("output_per_task", fmt_int), ("requests_per_task", fmt_int),
        ("cache_hit", fmt_pct), ("mean_max_context", fmt_int),
        ("read_full_per_task", lambda v: "—" if v is None else f"{v:.1f}"),
    ]
    show_change = bool(result["change"])
    headers = ["", *names] + ([L["change"]] if show_change else [])
    rows = []
    for metric, fmt in metrics:
        row = [L[metric]] + [fmt(result["phases"][n][metric]) for n in names]
        if show_change:
            row.append(fmt_pct(result["change"].get(metric)) if metric in result["change"] else "")
        rows.append(row)
    cost_row = [L["cost"]] + [fmt_cost(result["phases"][n]["cost"], result["phases"][n]["cost_known"], L)
                              for n in names] + ([""] if show_change else [])
    rows.insert(3, cost_row)

    def fmt_spread(s):
        return "—" if not s else (f"{s['mean']:.4f} ± {s['sd']:.4f} · {s['median']:.4f} "
                                  f"({s['min']:.4f}–{s['max']:.4f})")

    spread_row = [L["attempt_cost"]] + [fmt_spread(result["phases"][n]["attempt_cost"]) for n in names] + \
                 ([""] if show_change else [])
    rows.insert(5, spread_row)
    parts = [table(headers, rows)]
    for phase, tasks in result.get("only_in", {}).items():
        if tasks:
            parts.append(f"- {L['only_in']} {phase}: {', '.join(tasks)}")
    return "\n".join(parts)


# ── CLI ──────────────────────────────────────────────────────────────────────


def cmd_list(args, prices, L) -> int:
    root = projects_root()
    if args.all:
        files = list(root.glob("*/*.jsonl"))
    else:
        folder = root / project_slug(Path(args.project or os.getcwd()))
        files = list(folder.glob("*.jsonl"))
        if not files:
            print(f"{L['no_sessions']} {folder}")
            return 1
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    rows, payload = [], []
    for path in files[: args.limit]:
        m = measure(path, prices)
        payload.append({"session": m.session, "title": m.title, "start": m.start, "end": m.end,
                        "requests": m.total.requests, "cost": m.total.cost, "cost_known": m.total.cost_known})
        rows.append([m.session[:8], (m.start or "—")[:16].replace("T", " "), fmt_duration(m.start, m.end),
                     fmt_int(m.total.requests), fmt_cost(m.total.cost, m.total.cost_known, L),
                     (m.title or "—")[:60].replace("|", "/")])
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(table([L["session"], L["start"], L["duration"], L["requests"], L["cost"], L["title"]], rows))
    return 0


def cmd_measure(args, prices, L) -> int:
    m = measure(find_session(args.session, projects_root()), prices,
                parse_time(args.since) if args.since else None,
                parse_time(args.until) if args.until else None)
    print(json.dumps(m.to_dict(), indent=2, ensure_ascii=False) if args.json else render_measurement(m, L))
    return 0


def cmd_record(args, prices, L) -> int:
    m = measure(find_session(args.session, projects_root()), prices,
                parse_time(args.since) if args.since else None,
                parse_time(args.until) if args.until else None)
    registry = load_registry(args.registry)
    registry["attempts"].append({
        "session": m.session,
        "task": args.task,
        "phase": args.phase,
        "completed": args.completed == "yes",
        "note": args.note or "",
        "since": args.since,
        "until": args.until,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "measurement": snapshot(m),
    })
    save_registry(args.registry, registry)
    print(f"{L['recorded']}: {args.task} / {args.phase} / {m.session[:8]} / "
          f"{fmt_cost(m.total.cost, m.total.cost_known, L)} → {args.registry}")
    return 0


def cmd_compare(args, prices, L) -> int:
    result = compare(load_registry(args.registry), args.before, args.after)
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render_comparison(result, L))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure Claude Code consumption per task.")
    parser.add_argument("--prices", type=Path, default=DEFAULT_PRICES, help="price table (JSON)")
    parser.add_argument("--lang", choices=sorted(LABELS), default="pt", help="output language")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="recent sessions of a project")
    p.add_argument("--project", help="project directory (default: current directory)")
    p.add_argument("--all", action="store_true", help="every project")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    def window(p):
        p.add_argument("session", help="session id or unique prefix")
        p.add_argument("--since", help="ISO timestamp; naive means local time")
        p.add_argument("--until", help="ISO timestamp; naive means local time")

    p = sub.add_parser("measure", help="measure one session")
    window(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_measure)

    p = sub.add_parser("record", help="store a session's measurement in the registry")
    window(p)
    p.add_argument("--task", required=True, help="task name; attempts of the same task share it")
    p.add_argument("--phase", required=True, help="e.g. before / after")
    p.add_argument("--completed", choices=("yes", "no"), required=True)
    p.add_argument("--note")
    p.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("compare", help="cost per completed task, phase against phase")
    p.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    p.add_argument("--before")
    p.add_argument("--after")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_compare)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    return args.func(args, load_prices(args.prices), LABELS[args.lang])


if __name__ == "__main__":
    sys.exit(main())
