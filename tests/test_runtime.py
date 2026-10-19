import pytest

from harnessforge.harness import Harness, compose
from harnessforge.runtime import OraclePolicy, ResearchEnv, run_episode


def make_env(corpus, index, q, **gates):
    inst = compose(Harness.seed(), q["text"])
    g = dict(inst.gates)
    g.update(gates)
    return ResearchEnv(corpus, index, q, inst.config, g, inst.mode)


def first_number_q(corpus):
    return next(q for q in corpus.questions if q["answer_type"] == "number" and len(q["calc"]["facts"]) == 1)


def test_upsert_requires_a_registered_span(corpus, index):
    q = first_number_q(corpus)
    env = make_env(corpus, index, q)
    obs = env.step({"action": "upsert", "statements": [{"text": "x", "refs": ["S1"], "value": 1}]})
    assert "not registered" in obs and not env.bank.entries


def test_lifecycle_and_citation_rules(corpus, index):
    q = first_number_q(corpus)
    f = q["calc"]["facts"][0]
    env = make_env(corpus, index, q)
    env.step({"action": "read", "doc_id": f["doc_id"], "offset": f["line_start"]})
    env.step({"action": "upsert", "statements": [{"text": "wrong", "refs": ["S1"], "value": 1, "unit": "백만원"}]})
    env.step({"action": "revise", "target": "E1", "replacement": {"text": "right", "refs": ["S1"],
                                                                  "value": f["printed"], "unit": f["unit"]}})
    assert env.bank.entries["E1"].status == "superseded" and env.bank.entries["E1"].replaced_by == "E2"
    assert env.bank.entries["E1"].value_found is False and env.bank.entries["E2"].value_found is True
    obs = env.step({"action": "final", "answer": "1", "refs": ["E1"]})
    assert "cite_active_only" in obs and not env.done
    with pytest.raises(Exception):
        env._a_compute({"expression": "E1 + 1"})
    env.step({"action": "revise", "target": "E2"})
    assert env.bank.entries["E2"].status == "retracted"


def test_value_in_source_gate(corpus, index):
    q = first_number_q(corpus)
    f = q["calc"]["facts"][0]
    env = make_env(corpus, index, q, value_in_source=True)
    env.step({"action": "read", "doc_id": f["doc_id"], "offset": f["line_start"]})
    obs = env.step({"action": "upsert", "statements": [{"text": "made up", "refs": ["S1"], "value": 987654321}]})
    assert "value_in_source" in obs and not env.bank.entries


def test_correction_and_preliminary_gates(corpus, index):
    orig = next(d for d in corpus.docs if d.get("corrected_by"))
    q = next(q for q in corpus.questions if orig["company"] in q["companies"])
    env = make_env(corpus, index, q, correction_check=True)
    env.step({"action": "read", "doc_id": orig["doc_id"], "offset": 0})
    env.step({"action": "upsert", "statements": [{"text": "cover", "refs": ["S1"]}]})
    obs = env.step({"action": "final", "answer": "1", "refs": ["E1"]})
    assert "correction_check" in obs and orig["corrected_by"] in obs
    prelim = next(d for d in corpus.docs if d["kind"] == "prelim")
    env = make_env(corpus, index, q, preliminary_check=True)
    env.step({"action": "read", "doc_id": prelim["doc_id"], "offset": 0})
    env.step({"action": "upsert", "statements": [{"text": "cover", "refs": ["S1"]}]})
    assert "preliminary_check" in env.step({"action": "final", "answer": "1", "refs": ["E1"]})


def test_numeric_and_compute_gates(corpus, index):
    q = next(q for q in corpus.questions if q["unit"] == "%")
    env = make_env(corpus, index, q, require_compute_for_derived=True)
    assert "numeric_answer" in env.step({"action": "final", "answer": "모름", "refs": []})
    f = q["calc"]["facts"][0]
    env.step({"action": "read", "doc_id": f["doc_id"], "offset": f["line_start"]})
    env.step({"action": "upsert", "statements": [{"text": "a", "refs": ["S1"], "value": f["printed"]}]})
    assert "require_compute_for_derived" in env.step({"action": "final", "answer": "12.3", "refs": ["E1"]})


def test_notes_mode_has_no_evidence_bank(corpus, index):
    q = first_number_q(corpus)
    inst = compose(Harness.seed("notes"), q["text"])
    env = ResearchEnv(corpus, index, q, inst.config, inst.gates, inst.mode)
    assert "unknown action" in env.step({"action": "upsert", "statements": []})
    env.step({"action": "note", "text": "revenue looks like 12,345"})
    assert "final accepted" in env.step({"action": "final", "answer": "123.4"})


@pytest.mark.parametrize("all_gates", [False, True])
def test_oracle_solves_every_question_within_budget(corpus, index, all_gates):
    h = Harness.seed()
    for q in corpus.questions:
        inst = compose(h, q["text"])
        if all_gates:
            inst.gates = {k: True for k in inst.gates}
        t = run_episode(corpus, index, q, inst, OraclePolicy(q))
        assert t["summary"]["final_accepted"] and t["score"]["correct"], (q["qid"], t["score"], t["summary"]["gate_rejections"])
        assert t["summary"]["turns"] <= inst.config["max_turns"]


def test_block_repeats_gate(corpus, index):
    q = first_number_q(corpus)
    env = make_env(corpus, index, q, block_repeats=True)
    env.step({"action": "search", "query": "매출액", "company": q["companies"][0]})
    assert "block_repeats" in env.step({"action": "search", "query": "매출액", "company": q["companies"][0]})
    f = q["calc"]["facts"][0]
    env.step({"action": "read", "doc_id": f["doc_id"], "offset": f["line_start"]})
    assert "block_repeats" in env.step({"action": "read", "doc_id": f["doc_id"], "offset": f["line_start"]})
    assert len(env.registry.spans) == 1
    off = make_env(corpus, index, q)
    off.step({"action": "search", "query": "매출액"})
    assert "results" in off.step({"action": "search", "query": "매출액"}) and off.signals["repeated_search"] == 1


def test_task_block_states_the_corpus_period(corpus, index):
    from harnessforge.runtime.agent import build_prompt
    q = first_number_q(corpus)
    env = make_env(corpus, index, q)
    p = build_prompt(q, env, [], {"max_turns": 16})
    assert "published filings" in p and "2024." in p and "2026." in p
