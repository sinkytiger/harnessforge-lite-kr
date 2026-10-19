"""Command line: build, validate, run, evolve (Harmony), refine (Harness^2), report."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .corpus import Corpus, build_corpus
from .harness import Harness, compose
from .llm import make_client
from .retrieval import Index
from .runtime import OraclePolicy, run_direct, run_episode


def _corpus(args) -> Corpus:
    if getattr(args, "corpus", None) and Path(args.corpus).exists():
        return Corpus.load(args.corpus)
    return build_corpus(getattr(args, "seed", 7))


def _harness(spec: str) -> Harness:
    if spec.startswith("seed-"):
        return Harness.seed(spec[len("seed-"):])
    return Harness.load(spec)


def _questions(corpus: Corpus, args) -> list[dict]:
    qs = corpus.split(args.split) if args.split != "all" else list(corpus.questions)
    if getattr(args, "only", None):
        qs = [q for q in qs if any(q["qid"].startswith(o) for o in args.only)]
    if getattr(args, "limit", None):
        qs = qs[: args.limit]
    return qs


def _out(path: str, config: dict) -> Path:
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    cfg = out / "run_config.json"
    prev = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
    cfg.write_text(json.dumps(prev | config, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def cmd_build(args) -> int:
    c = build_corpus(args.seed)
    out = c.save(args.out)
    print(f"corpus seed={args.seed}: {c.meta['n_docs']} filings, {c.meta['n_chars']:,} chars, "
          f"{len(c.questions)} questions ({len(c.split('search'))} search / {len(c.split('test'))} test) -> {out}")
    return 0


def cmd_validate(args) -> int:
    c = _corpus(args)
    idx = Index(c.docs)
    h = Harness.seed("longharness")
    bad = 0
    for all_gates in (False, True):
        ok = 0
        for q in c.questions:
            inst = compose(h, q["text"])
            if all_gates:
                inst.gates = {k: True for k in inst.gates}
            t = run_episode(c, idx, q, inst, OraclePolicy(q))
            good = t["score"]["correct"] and t["summary"]["final_accepted"]
            ok += good
            if not good:
                bad += 1
                print(f"  FAIL {q['qid']}: {t['score']} {t['summary']['gate_rejections']}")
        print(f"oracle with {'all gates on' if all_gates else 'seed gates'}: {ok}/{len(c.questions)} solved")
    print(f"corpus {c.meta['n_docs']} filings, {c.meta['n_chars']:,} chars, sha {c.meta['sha256_16']}")
    return 1 if bad else 0


def cmd_run(args) -> int:
    c = _corpus(args)
    idx = Index(c.docs)
    qs = _questions(c, args)
    scopes = tuple(args.scopes)
    out = _out(args.out, {"label": args.label or Path(args.out).name, "harness": args.harness, "model": args.model,
                          "seeds": args.seeds, "split": args.split, "scopes": list(scopes)})
    runs = out / "runs"
    runs.mkdir(exist_ok=True)
    h = None if args.harness == "direct" else _harness(args.harness)
    if h is not None:
        h.save(out / "harness")
    t0 = time.time()
    n_ok = n = 0
    for seed in args.seeds:
        client = make_client(args.model, seed=seed, temperature=args.temperature, think=args.think, effort=args.effort)
        for q in qs:
            tag = "direct" if h is None else h.hash
            path = runs / f"{q['qid']}__{tag}__s{seed}{'' if scopes == ('general', 'domain') else '__' + '-'.join(scopes)}.json"
            if path.exists():
                t = json.loads(path.read_text(encoding="utf-8"))
                if t.get("model") not in (None, args.model):
                    print(f"{path} holds a run of {t.get('model')}, not {args.model}; use another --out")
                    return 2
            else:
                try:
                    if h is None:
                        t = run_direct(c, idx, q, client, k=args.direct_k)
                    else:
                        t = run_episode(c, idx, q, compose(h, q["text"], scopes=scopes), _policy(client))
                except Exception as exc:  # noqa: BLE001
                    if getattr(exc, "quota", False):
                        print(f"quota exhausted: {exc}; stopping (completed episodes are kept)")
                        return 2
                    raise
                t["seed"], t["model"] = seed, args.model
                path.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
            n += 1
            n_ok += t["score"]["correct"]
            print(f"[{n}] {q['qid']} s{seed}: {'OK' if t['score']['correct'] else 'x '} ans={t['summary']['answer']!r} "
                  f"gold={q['gold'] if q['answer_type'] == 'entity' else round(q['gold'], 2)} "
                  f"turns={t['summary']['turns']} tok={t['usage']['total_tokens']} {t['seconds']:.0f}s", flush=True)
    print(f"accuracy {n_ok}/{n} = {n_ok / max(n, 1):.1%} in {time.time() - t0:.0f}s")
    return 0


def _policy(client):
    from .runtime import LLMPolicy
    return LLMPolicy(client)


def cmd_evolve(args) -> int:
    from .evolve import HarmonySearch
    c = _corpus(args)
    idx = Index(c.docs)
    qs = _questions(c, args)
    if any(q["split"] != "search" for q in qs) and not args.allow_test_split:
        print("evolve shows gold answers to the editor; it runs on the search split only "
              "(pass --allow-test-split to override)")
        return 2
    editor = make_client(args.editor_model or args.model, seed=args.editor_seed, temperature=args.editor_temperature,
                         num_ctx=args.editor_ctx, think=args.think, effort=args.editor_effort)
    out = _out(args.out, {"label": "harmony", "model": args.model, "editor_model": args.editor_model or args.model,
                          "n_sub": args.n_sub, "generations": args.generations, "seeds": args.seeds,
                          "questions": [q["qid"] for q in qs]})
    hs = HarmonySearch(c, idx, qs, lambda s: make_client(args.model, seed=s, temperature=args.temperature, think=args.think, effort=args.effort), editor, out,
                       n_sub=args.n_sub, neighbours=args.neighbours, n_replace=args.n_replace,
                       generations=args.generations, seeds=args.seeds, token_cap=args.token_cap,
                       weights=[(1.0, 0.0)] if args.accuracy_only else None)
    hs.run(_harness(args.harness))
    return 0


def cmd_refine(args) -> int:
    from .evolve import Harness2
    c = _corpus(args)
    idx = Index(c.docs)
    qs = _questions(c, args)
    editor = make_client(args.editor_model or args.model, seed=args.editor_seed, temperature=args.editor_temperature,
                         num_ctx=args.editor_ctx, think=args.think, effort=args.editor_effort)
    out = _out(args.out, {"label": "harness2", "model": args.model, "editor_model": args.editor_model or args.model,
                          "k": args.k, "library": not args.no_library, "harness": args.harness})
    h2 = Harness2(c, idx, lambda s: make_client(args.model, seed=s, temperature=args.temperature, think=args.think, effort=args.effort), editor, out,
                  k=args.k, use_library=not args.no_library, seed=args.seeds[0])
    h2.stream(qs, _harness(args.harness))
    return 0


def cmd_check_model(args) -> int:
    """One tiny request to confirm the model is reachable (and, for Claude, that a key is found)."""
    if args.model.startswith(("claude-", "anthropic:")):
        from .claude import check
        try:
            print(check(args.model.split(":", 1)[-1] if args.model.startswith("anthropic:") else args.model))
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED: {exc}")
            return 1
        return 0
    client = make_client(args.model)
    try:
        out, u = client.json_call("Reply in JSON.", "Return ok=true.", {"type": "object", "properties": {"ok": {"type": "boolean"}},
                                                                     "required": ["ok"]}, max_tokens=50)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {exc}")
        return 1
    print(f"{args.model}: ok={out.get('ok')} tokens={u.total_tokens}")
    return 0


def cmd_report(args) -> int:
    from .report import episodes_table, harness2_table
    parts = [f"# {args.title}", ""]
    if args.runs:
        parts += [episodes_table(args.runs), ""]
    if args.records:
        parts += ["## Harness^2 test-time refinement", "", harness2_table(args.records), ""]
    text = "\n".join(parts)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harnessforge", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, model=True):
        sp.add_argument("--corpus", help="saved corpus directory (default: build from --seed in memory)")
        sp.add_argument("--seed", type=int, default=7, help="corpus seed")
        sp.add_argument("--split", default="test", choices=["search", "test", "all"])
        sp.add_argument("--only", nargs="*", help="question id prefixes")
        sp.add_argument("--limit", type=int)
        if model:
            sp.add_argument("--model", default="qwen3:4b", help="executor model (Ollama name)")
            sp.add_argument("--seeds", type=int, nargs="+", default=[7])
            sp.add_argument("--temperature", type=float, default=0.2)
            sp.add_argument("--think", default="auto", choices=["auto", "on", "off"])
            sp.add_argument("--effort", default="low", choices=["low", "medium", "high", "xhigh", "max"],
                            help="reasoning effort when the executor is a Claude model")

    sp = sub.add_parser("build", help="generate the synthetic corpus")
    sp.add_argument("--seed", type=int, default=7)
    sp.add_argument("--out", default="data/corpus")
    sp.set_defaults(fn=cmd_build)

    sp = sub.add_parser("validate", help="replay the gold computation of every question through the tools")
    common(sp, model=False)
    sp.set_defaults(fn=cmd_validate)

    sp = sub.add_parser("run", help="run episodes with a harness (or the direct baseline)")
    common(sp)
    sp.add_argument("--harness", default="seed-longharness", help="seed-longharness | seed-notes | direct | <dir>")
    sp.add_argument("--scopes", nargs="+", default=["general", "domain"])
    sp.add_argument("--direct-k", type=int, default=6)
    sp.add_argument("--label")
    sp.add_argument("--out", required=True)
    sp.set_defaults(fn=cmd_run)

    for name, fn, helptext in (("evolve", cmd_evolve, "offline Harmony search on the search split"),
                               ("refine", cmd_refine, "verifier-free Harness^2 refinement on a task stream")):
        sp = sub.add_parser(name, help=helptext)
        common(sp)
        sp.add_argument("--harness", default="seed-longharness")
        sp.add_argument("--editor-model")
        sp.add_argument("--editor-seed", type=int, default=11)
        sp.add_argument("--editor-temperature", type=float, default=0.3)
        sp.add_argument("--editor-ctx", type=int, default=8192, help="keep equal to the executor context to avoid model reloads")
        sp.add_argument("--editor-effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"],
                        help="reasoning effort when the editor is a Claude model")
        sp.add_argument("--out", required=True)
        if name == "evolve":
            sp.set_defaults(split="search")
            sp.add_argument("--n-sub", type=int, default=4)
            sp.add_argument("--neighbours", type=int, default=2)
            sp.add_argument("--n-replace", type=int, default=2)
            sp.add_argument("--generations", type=int, default=3)
            sp.add_argument("--token-cap", type=int, default=80_000)
            sp.add_argument("--accuracy-only", action="store_true", help="single-objective baseline")
            sp.add_argument("--allow-test-split", action="store_true")
        else:
            sp.add_argument("--k", type=int, default=1)
            sp.add_argument("--no-library", action="store_true")
        sp.set_defaults(fn=fn)

    sp = sub.add_parser("check-model", help="one tiny request to confirm a model works")
    sp.add_argument("--model", required=True)
    sp.set_defaults(fn=cmd_check_model)

    sp = sub.add_parser("report", help="markdown tables from run directories")
    sp.add_argument("--runs", nargs="*", default=[])
    sp.add_argument("--records", nargs="*", default=[])
    sp.add_argument("--title", default="Results")
    sp.add_argument("--out")
    sp.set_defaults(fn=cmd_report)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
