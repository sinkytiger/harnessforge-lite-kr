"""Markdown tables from run directories (episodes) and Harness^2 record files."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def load_runs(run_dir: str | Path) -> list[dict]:
    d = Path(run_dir) / "runs"
    out = []
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def _label(run_dir: Path) -> str:
    cfg = run_dir / "run_config.json"
    if cfg.exists():
        c = json.loads(cfg.read_text(encoding="utf-8"))
        return c.get("label") or run_dir.name
    return run_dir.name


def summarize(trajs: list[dict]) -> dict:
    by_seed = defaultdict(list)
    for t in trajs:
        by_seed[t.get("seed", 0)].append(t)
    accs = [sum(t["score"]["correct"] for t in ts) / len(ts) for ts in by_seed.values() if ts]
    n = len(trajs)
    return {
        "episodes": n,
        "seeds": len(by_seed),
        "accuracy": sum(t["score"]["correct"] for t in trajs) / n if n else 0.0,
        "acc_min": min(accs) if accs else 0.0,
        "acc_max": max(accs) if accs else 0.0,
        "acc_sd": statistics.pstdev(accs) if len(accs) > 1 else 0.0,
        "accepted": sum(bool(t["summary"]["final_accepted"]) for t in trajs) / n if n else 0.0,
        "turns": sum(t["summary"]["turns"] for t in trajs) / n if n else 0.0,
        "tokens": sum(t["usage"]["total_tokens"] for t in trajs) / n if n else 0.0,
        "seconds": sum(t.get("seconds", 0) for t in trajs) / n if n else 0.0,
        "traps": Counter(t["score"]["trap"] for t in trajs if t["score"].get("trap")),
        "statuses": Counter(t["score"]["status"] for t in trajs),
    }


def episodes_table(run_dirs: list[str]) -> str:
    rows = ["| System | Episodes | Seeds | Accuracy | Range over seeds | Accepted final | Turns | Tokens / episode |",
            "|---|---|---|---|---|---|---|---|"]
    trap_rows = []
    qtype_acc: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for rd in run_dirs:
        p = Path(rd)
        trajs = load_runs(p)
        if not trajs:
            continue
        s = summarize(trajs)
        label = _label(p)
        rows.append(f"| {label} | {s['episodes']} | {s['seeds']} | {s['accuracy']:.1%} | "
                    f"{s['acc_min']:.1%}–{s['acc_max']:.1%} | {s['accepted']:.1%} | {s['turns']:.1f} | {s['tokens']:,.0f} |")
        wrong = s["episodes"] - round(s["accuracy"] * s["episodes"])
        trap_rows.append((label, wrong, s["traps"], s["statuses"]))
        for t in trajs:
            qtype_acc[label][t["qtype"]].append(t["score"]["correct"])
    out = ["\n".join(rows), ""]
    if trap_rows:
        out.append("Wrong answers matched to a planted trap (answers that match no trap are counted as other):\n")
        names = sorted({k for _, _, tr, _ in trap_rows for k in tr})
        out.append("| System | Wrong or missing | " + " | ".join(names) + " | no answer |")
        out.append("|---|---|" + "---|" * (len(names) + 1))
        for label, wrong, tr, st in trap_rows:
            out.append(f"| {label} | {wrong} | " + " | ".join(str(tr.get(n, 0)) for n in names) +
                       f" | {st.get('no_answer', 0)} |")
        out.append("")
    if qtype_acc:
        qtypes = sorted({q for d in qtype_acc.values() for q in d})
        out.append("Accuracy by question type:\n")
        out.append("| System | " + " | ".join(qtypes) + " |")
        out.append("|---|" + "---|" * len(qtypes))
        for label, d in qtype_acc.items():
            out.append(f"| {label} | " + " | ".join(
                f"{sum(d[q]) / len(d[q]):.0%} ({len(d[q])})" if d.get(q) else "–" for q in qtypes) + " |")
    return "\n".join(out)


def harness2_table(record_files: list[str]) -> str:
    rows = ["| Run | Tasks | Reference accuracy | Deliverable accuracy | Changed answers (better / worse) | Decisions | Library entries |",
            "|---|---|---|---|---|---|---|"]
    for f in record_files:
        p = Path(f)
        recs = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not recs:
            continue
        n = len(recs)
        ref = sum(r["score_reference"]["correct"] for r in recs)
        dlv = sum(r["score_deliverable"]["correct"] for r in recs)
        better = sum(r["score_deliverable"]["correct"] and not r["score_reference"]["correct"] for r in recs)
        worse = sum(r["score_reference"]["correct"] and not r["score_deliverable"]["correct"] for r in recs)
        dec = Counter(c["decision"] for r in recs for c in r["compose"])
        lib = sum(1 for r in recs if r.get("library_entry"))
        label = p.parent.name
        rows.append(f"| {label} | {n} | {ref / n:.1%} | {dlv / n:.1%} | {better} / {worse} | "
                    + ", ".join(f"{k} {v}" for k, v in dec.most_common()) + f" | {lib} |")
    return "\n".join(rows)
