"""Build reports/results.md and docs/figures/*.png from every experiment run directory.

    python scripts/make_report.py

Two executors (qwen3:4b local, Claude Haiku 5.5 API) and up to three evolution runs:
qwen3:4b executor with a qwen3:4b or a Claude Opus 5.5 editor, and Haiku 5.5 executor with an
Opus 5.5 editor. Every saved answer is re-scored with the current scoring code.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harnessforge.claude import PRICES  # noqa: E402
from harnessforge.corpus import build_corpus  # noqa: E402
from harnessforge.report import load_runs as _load_runs  # noqa: E402
from harnessforge.scoring import score  # noqa: E402

RUNS = ROOT / "runs"
OUT = ROOT / "reports"
FIG = ROOT / "docs" / "figures"
QUESTIONS = {q["qid"]: q for q in build_corpus(7).questions}

# Reference palette (dataviz skill): light surface, ink tokens, categorical slots 1-3.
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
SLOT = ["#2a78d6", "#eb6834", "#1baf7a"]

EXECUTORS = [
    {"key": "qwen", "label": "qwen3:4b (local GPU)",
     "e1": [("e1_direct", "Direct RAG"), ("e1_notes", "Tools + notes"), ("e1_longharness", "LongHarness seed H0")],
     "evolve": [("qwen3:4b editor", "e2_harmony", "e3_harness2"),
                ("Claude Opus 5.5 editor", "e2c_harmony_claude", "e3c_harness2_claude")]},
    {"key": "haiku", "label": "Claude Haiku 5.5 (API)",
     "e1": [("h1_direct", "Direct RAG"), ("h1_notes", "Tools + notes"), ("h1_longharness", "LongHarness seed H0"),
            ("h1_longharness_rerun", "LongHarness seed H0, second run")],
     "evolve": [("Claude Opus 5.5 editor", "h2_harmony", "h3_harness2")],
     "controls": [("h4_hdagger_rerun", "Harmony pick H†, second run without edits (control)")]},
]


def price_of(model: str | None, prompt: int, output: int) -> float:
    m = (model or "").split(":")[-1]
    if m not in PRICES:
        return 0.0
    p_in, p_out, _ = PRICES[m]
    return (prompt * p_in + output * p_out) / 1e6


def load_runs(path: Path) -> list[dict]:
    trajs = _load_runs(path)
    for t in trajs:
        t["score"] = score(QUESTIONS[t["qid"]], t["summary"]["answer"])
    return trajs


def row_from_trajs(label: str, trajs: list[dict]) -> dict | None:
    if not trajs:
        return None
    n = len(trajs)
    usd = sum(price_of(t.get("model"), t["usage"].get("prompt_tokens", 0), t["usage"].get("output_tokens", 0)) for t in trajs)
    return {"label": label, "n": n, "correct": sum(t["score"]["correct"] for t in trajs),
            "accepted": sum(bool(t["summary"]["final_accepted"]) for t in trajs) / n,
            "turns": sum(t["summary"]["turns"] for t in trajs) / n,
            "tokens": sum(t["usage"]["total_tokens"] for t in trajs) / n, "usd": usd / n,
            "traps": Counter(t["score"]["trap"] for t in trajs if t["score"].get("trap")),
            "no_answer": sum(t["score"]["status"] in ("no_answer", "unparsable") for t in trajs),
            "qtypes": _qtypes([(t["qtype"], t["score"]["correct"]) for t in trajs])}


def _qtypes(pairs) -> dict:
    d: dict[str, list] = defaultdict(list)
    for q, ok in pairs:
        d[q].append(bool(ok))
    return d


def harness2_rows(editor: str, out: str) -> tuple[list[dict], list[dict]]:
    path = RUNS / out / "records.jsonl"
    if not path.exists():
        return [], []
    recs = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not recs:
        return [], []
    runs = load_runs(RUNS / out)
    exec_usd = defaultdict(float)
    for t in runs:
        exec_usd[t["qid"]] += price_of(t.get("model"), t["usage"].get("prompt_tokens", 0), t["usage"].get("output_tokens", 0))
    ref_by_qid = {t["qid"]: t for t in runs if t["harness"] == recs[0]["h0"]}
    rows = []
    for which in ("reference", "deliverable"):
        sc, sig, usd, tok = [], [], [], []
        for r in recs:
            q = QUESTIONS[r["qid"]]
            if which == "reference":
                s = r["references"][0]["signals"]
                ref = ref_by_qid.get(r["qid"])
                usd.append(price_of(ref.get("model"), ref["usage"]["prompt_tokens"], ref["usage"]["output_tokens"]) if ref else 0.0)
                tok.append(s["tokens"])
            else:
                s = r["deliverable"]["signals"]
                usd.append(exec_usd[r["qid"]] + r["cost"].get("editor_usd", 0.0))
                tok.append(r["cost"]["executor_tokens"] + r["cost"]["editor_tokens"])
            sc.append(score(q, s["answer"]))
            sig.append(s)
        n = len(recs)
        short = "Opus editor" if "Opus" in editor else "qwen editor"
        label = (f"Harmony pick H†, {short}" if which == "reference" else f"H† + Harness² step, {short}")
        rows.append({"label": label, "n": n, "correct": sum(x["correct"] for x in sc),
                     "accepted": sum(bool(s["final_accepted"]) for s in sig) / n,
                     "turns": sum(s["turns"] for s in sig) / n, "tokens": sum(tok) / n, "usd": sum(usd) / n,
                     "traps": Counter(x["trap"] for x in sc if x.get("trap")),
                     "no_answer": sum(x["status"] in ("no_answer", "unparsable") for x in sc),
                     "qtypes": _qtypes([(r["qid"].split("_", 1)[1], x["correct"]) for r, x in zip(recs, sc)])})
    for r in recs:
        q = QUESTIONS[r["qid"]]
        r["score_reference"] = score(q, r["references"][0]["signals"]["answer"])
        r["score_deliverable"] = score(q, r["deliverable"]["answer"])
    return rows, recs


def table_systems(rows: list[dict], with_usd: bool) -> str:
    head = "| System | Correct | Accepted final | Turns | Tokens / question |" + (" $ / question |" if with_usd else "")
    out = [head, "|---|---|---|---|---|" + ("---|" if with_usd else "")]
    for r in rows:
        acc = "no gates" if r["label"].startswith("Direct") else f"{r['accepted']:.0%}"
        line = (f"| {r['label']} | {r['correct']}/{r['n']} ({r['correct'] / r['n']:.1%}) | {acc} | "
                f"{r['turns']:.1f} | {r['tokens']:,.0f} |")
        if with_usd:
            line += f" {r['usd']:.4f} |"
        out.append(line)
    return "\n".join(out)


def table_traps(rows: list[dict]) -> str:
    names = sorted({k for r in rows for k in r["traps"]})
    out = ["| System | Wrong or missing | No answer | " + " | ".join(names) + " | Other wrong |",
           "|---|---|---|" + "---|" * (len(names) + 1)]
    for r in rows:
        wrong = r["n"] - r["correct"]
        other = wrong - sum(r["traps"].values()) - r["no_answer"]
        out.append(f"| {r.get('executor', '')} · {r['label']} | {wrong} | {r['no_answer']} | " + " | ".join(str(r["traps"].get(k, 0)) for k in names)
                   + f" | {max(other, 0)} |")
    return "\n".join(out)


def table_qtypes(rows: list[dict]) -> str:
    qt = sorted({q for r in rows for q in r["qtypes"]})
    out = ["| System | " + " | ".join(qt) + " |", "|---|" + "---|" * len(qt)]
    for r in rows:
        out.append(f"| {r.get('executor', '')} · {r['label']} | " + " | ".join(
            f"{sum(r['qtypes'][q])}/{len(r['qtypes'][q])}" if r["qtypes"].get(q) else "–" for q in qt) + " |")
    return "\n".join(out)


def harmony(path: str) -> dict | None:
    p = RUNS / path / "harmony.json"
    if not p.exists():
        return None
    h = json.loads(p.read_text(encoding="utf-8"))
    cfg = RUNS / path / "run_config.json"
    if not (h.get("editor") or {}).get("name") and cfg.exists():
        h["editor"] = {"name": json.loads(cfg.read_text(encoding="utf-8")).get("editor_model", "?")}
    return h


def table_harmony(h: dict) -> str:
    out = ["| Harness | Gen | λ (acc, eff) | Edit | Search-split accuracy | Tokens / question | Pareto front |",
           "|---|---|---|---|---|---|---|"]
    for m in h["archive"]:
        sub = m["sub"]
        lam = f"({h['weights'][sub][0]:.2f}, {h['weights'][sub][1]:.2f})" if sub is not None else "seed"
        d = m.get("diagnosis") or {}
        edit = (f"{d.get('component', '')}/{d.get('scope', '')}: " if d else "") + ("; ".join(m.get("applied") or []) or "–")
        out.append(f"| `{m['hash']}`{' **H†**' if m['hash'] == h['best'] else ''} | {m['gen']} | {lam} | {edit[:110]} | "
                   f"{m['f_acc']:.1%} | {m['metrics']['mean_tokens']:,.0f} | {'yes' if m['hash'] in h['front'] else ''} |")
    rejected = [x for x in h["history"] if x.get("error")]
    ed = h.get("editor") or {}
    out.append("")
    out.append(f"Editor `{ed.get('name', '?')}`: {h.get('editor_calls', 0)} calls"
               + (f", ${ed['usd']:.2f}" if ed.get("usd") else "") + f". Edits rejected before evaluation: {len(rejected)} of "
               f"{len(h['history'])}" + (f" ({'; '.join(sorted({x['error'][:70] for x in rejected})[:3])})" if rejected else "") + ".")
    return "\n".join(out)


def summary_harness2(recs: list[dict]) -> str:
    dec = Counter(c["decision"] for r in recs for c in r["compose"])
    better = [r["qid"] for r in recs if r["score_deliverable"]["correct"] and not r["score_reference"]["correct"]]
    worse = [r["qid"] for r in recs if r["score_reference"]["correct"] and not r["score_deliverable"]["correct"]]
    changed = sum(str(r["deliverable"]["answer"]) != str(r["references"][0]["signals"]["answer"]) for r in recs)
    valid = Counter((c["kind"], c["valid"]) for r in recs for c in r["candidates"])
    lib = [r["library_entry"] for r in recs if r.get("library_entry")]
    ed_usd = sum(r["cost"].get("editor_usd", 0.0) for r in recs)
    return "\n".join([
        "* Compose decisions: " + ", ".join(f"{k} {v}" for k, v in dec.most_common()) + ".",
        f"* Valid proposals: invariant {valid.get(('invariant', True), 0)}/{len(recs)}, domain {valid.get(('domain', True), 0)}/{len(recs)}.",
        f"* The deliverable differs from the reference answer on {changed} of {len(recs)} tasks: newly correct {len(better)}"
        f" ({', '.join(better) or 'none'}), newly wrong {len(worse)} ({', '.join(worse) or 'none'}).",
        f"* Library entries written: {len(lib)}." + (f" Editor cost ${ed_usd:.2f}." if ed_usd else ""),
    ])


def figure_systems(groups: list[tuple[str, list[dict]]], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans"]
    seen = []
    for _, rows in groups:
        for r in rows:
            if r["label"] not in seen:
                seen.append(r["label"])
    order = ["Direct RAG", "Tools + notes", "LongHarness seed H0", "LongHarness seed H0, second run",
             "Harmony pick H†", "Harmony pick H†, second run", "H† + Harness² step"]
    rank = lambda lab: next((i for i, o in enumerate(order) if lab.startswith(o) and not (o == "Harmony pick H†" and "second run" in lab)), len(order))  # noqa: E731
    labels = sorted(seen, key=lambda lab: (rank(lab), seen.index(lab)))
    fig, ax = plt.subplots(figsize=(8.2, 0.62 * len(labels) + 1.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    h = 0.36 if len(groups) > 1 else 0.5
    for gi, (gname, rows) in enumerate(groups):
        by = {r["label"]: r for r in rows}
        ys, vals, texts = [], [], []
        for i, lab in enumerate(labels[::-1]):
            if lab in by:
                r = by[lab]
                ys.append(i + (gi - (len(groups) - 1) / 2) * h * -1.05)
                vals.append(100 * r["correct"] / r["n"])
                texts.append(f"{vals[-1]:.0f}%  ({r['correct']}/{r['n']})")
        ax.barh(ys, vals, height=h, color=SLOT[gi], edgecolor=SURFACE, linewidth=2, label=gname)
        for y, v, t in zip(ys, vals, texts):
            ax.text(v + 1.0, y, t, va="center", ha="left", fontsize=8, color=INK)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels[::-1])
    ax.set_xlim(0, 100)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="y", length=0, labelsize=9, colors=INK)
    ax.tick_params(axis="x", labelsize=8, colors=INK2)
    ax.set_xlabel("Correct answers on the 35 held-out test questions (%)", fontsize=8.5, color=INK2)
    ax.set_title("Accuracy by system and executor model", fontsize=10.5, color=INK, loc="left", pad=26)
    leg = ax.legend(frameon=False, fontsize=8, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=len(groups),
                    handlelength=1.2, borderaxespad=0.2)
    for t in leg.get_texts():
        t.set_color(INK2)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def figure_harmony(runs: list[tuple[str, dict]], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans"]
    fig, axes = plt.subplots(1, len(runs), figsize=(4.2 * len(runs), 3.9), dpi=200, sharey=True, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for ax, (title, h) in zip(axes[0], runs):
        ax.set_facecolor(SURFACE)
        pts = [(m["metrics"]["mean_tokens"] / 1000, m["f_acc"] * 100, m) for m in h["archive"]]
        front = sorted([p for p in pts if p[2]["hash"] in h["front"]], key=lambda p: p[0])
        if len(front) > 1:
            ax.plot([p[0] for p in front], [p[1] for p in front], color=MUTED, linewidth=1.5, linestyle="--", zorder=1,
                    label="Pareto front")
        ev = [p for p in pts if p[2]["gen"] > 0]
        ax.scatter([p[0] for p in ev], [p[1] for p in ev], s=60, color=SLOT[0], edgecolor=SURFACE, linewidth=2, zorder=3,
                   label="evolved harness")
        sd = [p for p in pts if p[2]["gen"] == 0]
        ax.scatter([p[0] for p in sd], [p[1] for p in sd], s=70, color=SLOT[1], edgecolor=SURFACE, linewidth=2, zorder=4,
                   marker="D", label="seed H0")
        for x, y, m in pts:
            if m["hash"] == h["best"] and m["gen"] > 0:
                ax.annotate("H† (picked)", (x, y), xytext=(6, 6), textcoords="offset points", fontsize=8, color=INK)
        ax.set_ylim(-4, 108)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(GRID)
        ax.tick_params(labelsize=8, colors=INK2)
        ax.set_xlabel("Tokens per question (thousands)", fontsize=8, color=INK2)
        ax.set_title(title, fontsize=9, color=INK, loc="left", pad=8)
    axes[0][0].set_ylabel("Search-split accuracy (%)", fontsize=8.5, color=INK2)
    leg = axes[0][-1].legend(frameon=False, fontsize=7.5, loc="best")
    for t in leg.get_texts():
        t.set_color(INK2)
    fig.suptitle("Harmony search archives: every evaluated harness", fontsize=10.5, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def main() -> int:
    parts = ["# Results", "",
             "Test split: 35 questions about 11 companies that the search never saw. One sampling seed (7). "
             "The qwen3:4b executor runs locally through Ollama on a laptop RTX 2060 (6 GB). Claude models run through the "
             "Anthropic API (executor effort low, editor effort medium). Dollar figures are API list prices; local runs cost $0.", ""]
    groups, all_rows, harmony_runs = [], [], []
    for ex in EXECUTORS:
        rows = [r for r in (row_from_trajs(lab, load_runs(RUNS / d)) for d, lab in ex["e1"]) if r]
        h2_parts = []
        for editor, e2, e3 in ex["evolve"]:
            h = harmony(e2)
            if h:
                harmony_runs.append((f"{ex['label'].split(' (')[0]} executor, {editor}", h))
                h2_parts += [f"### Harmony search, {editor} (search split, 16 questions)", "", table_harmony(h), ""]
            hrows, recs = harness2_rows(editor, e3)
            if hrows and ex.get("controls"):
                ctrl = [r for r in (row_from_trajs(lab, load_runs(RUNS / d)) for d, lab in ex["controls"]) if r]
                hrows = hrows[:1] + ctrl + hrows[1:]
            rows += hrows
            if recs:
                h2_parts += [f"### Harness² test-time step, {editor} (no answer key in the loop)", "", summary_harness2(recs), ""]
        if not rows:
            continue
        for r in rows:
            r["executor"] = ex["label"].split(" (")[0]
        groups.append((ex["label"], rows))
        all_rows += rows
        parts += [f"## Executor: {ex['label']}", "", table_systems(rows, with_usd=ex["key"] == "haiku" or any(r["usd"] for r in rows)), ""]
        parts += h2_parts
    if all_rows:
        parts += ["## Where the wrong answers went (all systems)", "", table_traps(all_rows), "",
                  "## Correct answers by question type", "", table_qtypes(all_rows), ""]
    OUT.mkdir(exist_ok=True)
    (OUT / "results.md").write_text("\n".join(parts), encoding="utf-8")
    if groups:
        figure_systems(groups, FIG / "accuracy_by_system.png")
    if harmony_runs:
        figure_harmony(harmony_runs, FIG / "harmony_archive.png")
    print("\n".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
