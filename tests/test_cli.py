"""CLI wiring with fake models (no network)."""

import argparse
import json

import pytest

from harnessforge import cli
from harnessforge.llm import FakeLLM


def fake_factory(monkeypatch):
    def make(spec, seed=None, temperature=0.2, num_ctx=8192, think="auto", effort="medium"):
        def reply(messages):
            sys = messages[0]["content"]
            if "improve the harness" in sys:  # editor
                user = messages[-1]["content"]
                if "Diagnose the main cause" in user:
                    return {"diagnosis": "d", "hypothesis": "h", "component": "tools", "scope": "general"}
                if "Decide: keep" in user:
                    return {"rationale": "r", "decision": "adopt_invariant"}
                if "reusable lesson" in user:
                    return {"situation": "s", "lesson": "l"}
                return {"rationale": "r", "ops": [{"op": "set_config", "scope": "general" if "scope 'general'" in user or "scope general" in user else "domain",
                                                   "key": "search_k", "value": "6"}]}
            return {"thought": "t", "action": "final", "answer": "1.0"}
        return FakeLLM([reply] * 10_000, name=f"fake:{spec}")
    monkeypatch.setattr(cli, "make_client", make)


def test_run_evolve_refine_report(monkeypatch, tmp_path, capsys):
    fake_factory(monkeypatch)
    out = tmp_path / "run"
    assert cli.main(["run", "--harness", "seed-longharness", "--split", "test", "--limit", "2", "--out", str(out)]) == 0
    assert len(list((out / "runs").glob("*.json"))) == 2
    assert cli.main(["run", "--harness", "direct", "--split", "test", "--limit", "2", "--out", str(tmp_path / "d")]) == 0
    ev = tmp_path / "evolve"
    assert cli.main(["evolve", "--limit", "2", "--n-sub", "2", "--generations", "1", "--out", str(ev)]) == 0
    res = json.loads((ev / "harmony.json").read_text(encoding="utf-8"))
    assert res["best"] and (ev / "best").exists()
    rf = tmp_path / "refine"
    assert cli.main(["refine", "--harness", str(ev / "best"), "--split", "test", "--limit", "2", "--out", str(rf)]) == 0
    recs = [json.loads(x) for x in (rf / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 2 and all("cost" in r for r in recs)
    assert cli.main(["report", "--runs", str(out), "--records", str(rf / "records.jsonl")]) == 0
    assert "Accuracy" in capsys.readouterr().out


def test_bench_option_selects_the_question_set(tmp_path, capsys):
    assert cli.main(["build", "--bench", "v2", "--out", str(tmp_path / "v2")]) == 0
    assert "46 search / 35 validation / 92 test" in capsys.readouterr().out
    assert json.loads((tmp_path / "v2" / "meta.json").read_text(encoding="utf-8"))["sha256_16"] == "2fb66f1bd2fb5823"
    assert cli._split(argparse.Namespace(bench="real", split=None)) == "real"
    with pytest.raises(SystemExit, match="build-real"):
        cli.main(["validate", "--bench", "real", "--corpus", str(tmp_path / "missing")])
