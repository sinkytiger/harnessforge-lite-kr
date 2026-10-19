"""Both evolution loops end to end, with scripted fake models (no network)."""

import json

import pytest

from harnessforge.evolve import Harness2, HarmonySearch, contrast, pareto_front, tchebycheff, weight_vectors
from harnessforge.evolve.common import tags
from harnessforge.evolve.harmony import Member, neighbourhoods
from harnessforge.harness import Harness
from harnessforge.llm import FakeLLM


def test_weights_tchebycheff_neighbourhoods():
    w = weight_vectors(4)
    assert len(w) == 4 and all(abs(a + b - 1) < 1e-9 for a, b in w)
    assert tchebycheff((0.5, 0.5), (0.5, 0.5), (0.5, 0.5)) == 0
    assert tchebycheff((0.2, 0.9), (0.8, 0.2), (0.6, 0.9)) == pytest.approx(0.32)
    nb = neighbourhoods(w, 2)
    assert nb[0] == [0, 1] and nb[3] == [3, 2]


def test_pareto_front():
    h = Harness.seed()
    ms = [Member(h.copy(label=str(i)), f, {}, 0, None, None) for i, f in enumerate([(0.5, 0.5), (0.6, 0.4), (0.4, 0.4)])]
    ms[1].harness.files["x.md"] = "a"
    ms[2].harness.files["x.md"] = "b"
    assert {m.f for m in pareto_front(ms)} == {(0.5, 0.5), (0.6, 0.4)}


def executor_factory():
    """Answers immediately; cites nothing unless the harness turned require_refs off (then the final is accepted)."""
    def reply(messages):
        return {"thought": "answer now", "action": "final", "answer": "1.0"}
    return lambda seed: FakeLLM([reply] * 10_000, name="fake-exec")


def test_harmony_loop_runs_and_records(corpus, index, tmp_path):
    qs = corpus.split("search")[:2]
    diag = {"diagnosis": "no accepted finals", "hypothesis": "allow finals without refs", "component": "logic", "scope": "general"}
    op = {"rationale": "relax", "ops": [{"op": "set_gate", "scope": "general", "key": "require_refs", "value": "false"}]}
    op2 = {"rationale": "shorter", "ops": [{"op": "set_config", "scope": "general", "key": "max_turns", "value": "8"}]}
    editor = FakeLLM([diag, op, diag, op2])
    hs = HarmonySearch(corpus, index, qs, executor_factory(), editor, tmp_path, n_sub=2, generations=1, log=lambda *_: None)
    res = hs.run(Harness.seed())
    assert len(res["archive"]) == 3
    assert res["best"] in [m["hash"] for m in res["archive"]]
    assert (tmp_path / "harmony.json").exists() and (tmp_path / "best" / "general" / "system.md").exists()
    # the child that shortened the budget used fewer tokens, so it is at least as efficient
    effs = {m["hash"]: m["f_eff"] for m in res["archive"]}
    assert max(effs.values()) > min(effs.values())


def test_harmony_rejects_leaky_edits(corpus, index, tmp_path):
    qs = corpus.split("search")[:1]
    name = corpus.companies[0]["name"]
    diag = {"diagnosis": "d", "hypothesis": "h", "component": "skills", "scope": "domain"}
    leak = {"rationale": "cheat", "ops": [{"op": "write_skill", "scope": "domain", "name": "x", "content": f"{name} answer"}]}
    editor = FakeLLM([diag, leak, leak])
    hs = HarmonySearch(corpus, index, qs, executor_factory(), editor, tmp_path, n_sub=1, generations=1, log=lambda *_: None)
    res = hs.run(Harness.seed())
    assert len(res["archive"]) == 1 and res["history"][0]["error"]


def test_contrast_rules():
    def traj(accepted, answer="1", tokens=1000, rejections=None, invalid=0):
        return {"summary": {"final_accepted": accepted, "answer": answer, "turns": 3, "gate_rejections": rejections or {},
                            "signals": {"invalid_action": invalid}, "computes": 0, "unresolved_at_end": 0,
                            "cited_doc_kinds": []}, "usage": {"total_tokens": tokens}}
    assert contrast(traj(False), traj(True))[0]
    assert not contrast(traj(True), traj(False))[0]
    assert contrast(traj(True, invalid=4), traj(True))[0]
    assert contrast(traj(True, tokens=10_000), traj(True, tokens=5_000))[0]
    assert not contrast(traj(True), traj(True))[0]


def test_harness2_step_adopts_supported_edit_and_writes_library(corpus, index, tmp_path):
    q = corpus.split("test")[0]
    inv = {"rationale": "finals are rejected for lack of refs", "ops": [
        {"op": "set_gate", "scope": "general", "key": "require_refs", "value": "false"}]}
    dom = {"rationale": "nothing domain-specific", "ops": [
        {"op": "append_text", "scope": "domain", "file": "domain.md", "content": "Prefer the newest filing."}]}
    compose_dec = {"rationale": "invariant fixes the missing final", "decision": "adopt_invariant"}
    lesson = {"situation": "finals rejected by the refs gate", "lesson": "relaxing the gate lets the agent finish"}
    editor = FakeLLM([inv, dom, compose_dec, lesson])
    h2 = Harness2(corpus, index, executor_factory(), editor, tmp_path, k=1, log=lambda *_: None)
    out = h2.stream([q], Harness.seed())
    rec = out["records"][0]
    assert rec["compose"][0]["decision"] == "adopt_invariant"
    assert rec["deliverable"]["signals"]["final_accepted"] and not rec["references"][0]["signals"]["final_accepted"]
    assert rec["library_entry"] == "X001"
    exp = (tmp_path / "library" / "X001" / "EXPERIENCE.md").read_text(encoding="utf-8")
    assert "relaxing the gate" in exp
    assert "score_deliverable" in rec  # attached after the fact
    assert rec["cost"]["editor_calls"] == 3 and rec["cost"]["executor_tokens"] > rec["cost"]["reference_tokens"] > 0
    # the loop itself never saw gold: no prompt sent to the editor contains the gold answer
    gold = f"{q['gold']:.2f}" if q["answer_type"] == "number" else q["gold"]
    assert not any(gold in m["content"] for msgs in editor.prompts for m in msgs)
    # resuming skips finished tasks
    again = Harness2(corpus, index, executor_factory(), FakeLLM([]), tmp_path, k=1, log=lambda *_: None).stream([q], Harness.seed())
    assert len(again["records"]) == 1


def test_harness2_keep_when_editor_says_keep(corpus, index, tmp_path):
    q = corpus.split("test")[1]
    inv = {"rationale": "x", "ops": [{"op": "set_config", "scope": "general", "key": "search_k", "value": "6"}]}
    dom = {"rationale": "y", "ops": [{"op": "set_gate", "scope": "domain", "key": "unit_declared", "value": "true"}]}
    editor = FakeLLM([inv, dom, {"rationale": "no contrast", "decision": "keep"}])
    out = Harness2(corpus, index, executor_factory(), editor, tmp_path, k=1, log=lambda *_: None).stream([q], Harness.seed())
    assert out["records"][0]["compose"][0]["decision"] == "keep" and out["records"][0]["library_entry"] is None


def test_tags():
    assert "ratio_or_growth" in tags("영업이익률은 몇 %인가")
    assert "quarter_3m" in tags("2분기(4~6월, 3개월)")
    assert json.dumps(tags("별도 기준"), ensure_ascii=False) == '["separate_basis"]'


def test_harmony_survives_unusable_editor_replies(corpus, index, tmp_path):
    qs = corpus.split("search")[:1]
    editor = FakeLLM(["not json at all", "still not json"])
    hs = HarmonySearch(corpus, index, qs, executor_factory(), editor, tmp_path, n_sub=1, generations=1, log=lambda *_: None)
    res = hs.run(Harness.seed())
    assert len(res["archive"]) == 1 and "diagnose failed" in res["history"][0]["error"]


def test_policy_turns_a_failing_model_call_into_an_invalid_action(corpus, index):
    from harnessforge.harness import compose
    from harnessforge.runtime import LLMPolicy, run_episode
    q = corpus.split("test")[0]
    inst = compose(Harness.seed(), q["text"])
    t = run_episode(corpus, index, q, inst, LLMPolicy(FakeLLM([])), max_turns=2)
    assert t["summary"]["signals"].get("invalid_action") == 2 and not t["summary"]["final_accepted"]


def test_model_outage_stops_the_loop_instead_of_recording_keep(corpus, index, tmp_path):
    from harnessforge.evolve.common import ModelUnavailable
    from harnessforge.llm import LLMError

    class Down(FakeLLM):
        def json_call(self, *a, **k):
            raise LLMError("usage limit", status=429, quota=True)

    q = corpus.split("test")[0]
    h2 = Harness2(corpus, index, executor_factory(), Down(), tmp_path, k=1, log=lambda *_: None)
    with pytest.raises(ModelUnavailable):
        h2.stream([q], Harness.seed())
    assert not (tmp_path / "records.jsonl").exists()


def test_harness2_parallel_k2_maps_candidates_per_seed(corpus, index, tmp_path):
    q = corpus.split("test")[2]
    def ed(messages):
        user = messages[-1]["content"]
        if "Decide: keep" in user:
            return {"rationale": "r", "decision": "adopt_domain"}
        if "Several anonymous runs" in user:
            return {"rationale": "r", "choice": 1}
        scope = "general" if "scope 'general' only" in user else "domain"
        if scope == "general":
            return {"rationale": "r", "ops": [{"op": "set_config", "scope": "general", "key": "search_k", "value": "5"}]}
        return {"rationale": "r", "ops": [{"op": "set_gate", "scope": "domain", "key": "unit_declared", "value": "true"}]}
    out = Harness2(corpus, index, executor_factory(), FakeLLM([ed] * 50), tmp_path, k=2, log=lambda *_: None).stream([q], Harness.seed())
    rec = out["records"][0]
    assert len(rec["references"]) == 2 and len(rec["candidates"]) == 4 and len(rec["compose"]) == 2
    assert rec["selected"] == 1 and all(c["decision"] == "adopt_domain" for c in rec["compose"])


def test_op_schema_variants_require_their_fields():
    from harnessforge.evolve import editor as E
    s = E.op_schema(E.OPS_BY_COMPONENT["any"], "domain")
    variants = {v["properties"]["op"]["enum"][0]: v for v in s["properties"]["ops"]["items"]["anyOf"]}
    assert set(variants["write_skill"]["required"]) >= {"name", "when", "summary", "content"}
    assert variants["set_gate"]["properties"]["key"]["enum"] == sorted(["correction_check", "preliminary_check", "unit_declared"])
    t = E.op_schema(E.OPS_BY_COMPONENT["tools"], "general", "tools")
    v = {x["properties"]["op"]["enum"][0]: x for x in t["properties"]["ops"]["items"]["anyOf"]}
    assert set(v["set_config"]["properties"]["key"]["enum"]) == {"read_chars", "search_k", "snippet_chars"}
    one = E.op_schema(E.OPS_BY_COMPONENT["generalize"], None, "generalize")
    assert one["properties"]["ops"]["items"]["properties"]["op"]["enum"] == ["move_skill"]


def test_harmony_resumes_from_checkpoint(corpus, index, tmp_path):
    qs = corpus.split("search")[:2]
    diag = {"diagnosis": "d", "hypothesis": "h", "component": "tools", "scope": "general"}
    op = lambda k, v: {"rationale": "r", "ops": [{"op": "set_config", "scope": "general", "key": k, "value": v}]}  # noqa: E731
    first = HarmonySearch(corpus, index, qs, executor_factory(), FakeLLM([diag, op("search_k", "6"), diag, op("read_chars", "1800")]),
                          tmp_path, n_sub=2, generations=1, log=lambda *_: None).run(Harness.seed())
    assert len(first["archive"]) == 3
    # pretend generation 2 was interrupted before it started: drop the final pick and rerun with 2 generations
    state = json.loads((tmp_path / "harmony.json").read_text(encoding="utf-8"))
    state["best"] = None
    (tmp_path / "harmony.json").write_text(json.dumps(state), encoding="utf-8")
    editor = FakeLLM([diag, op("snippet_chars", "200"), diag, op("search_k", "3")])
    res = HarmonySearch(corpus, index, qs, executor_factory(), editor, tmp_path, n_sub=2, generations=2,
                        log=lambda *_: None).run(Harness.seed())
    assert len(res["archive"]) == 5 and [e["gen"] for e in res["history"]] == [1, 1, 2, 2]
    assert len(editor.prompts) == 4  # only generation 2 asked the editor
