import pytest

from harnessforge.corpus.questions_v2 import ABSTAIN_CLAUSE, ABSTAIN_GOLD
from harnessforge.corpus.render import NOTICE
from harnessforge.corpus.v2 import build_corpus_v2
from harnessforge.harness import Harness, compose
from harnessforge.retrieval import Index
from harnessforge.runtime import OraclePolicy, ResearchEnv, run_episode
from harnessforge.scoring import is_abstain, score


@pytest.fixture(scope="module")
def v2():
    return build_corpus_v2(21)


@pytest.fixture(scope="module")
def v2_index(v2):
    return Index(v2.docs)


def test_v2_is_deterministic_and_v1_is_unchanged(v2, corpus):
    assert v2.meta["sha256_16"] == "2fb66f1bd2fb5823"
    assert corpus.meta["sha256_16"] == "908aba588c8cc5cc"  # v2 work must not move the published v1 numbers
    again = build_corpus_v2(21)
    assert again.meta["sha256_16"] == v2.meta["sha256_16"]
    assert [q["qid"] for q in again.questions] == [q["qid"] for q in v2.questions]


def test_three_splits_are_disjoint_by_company(v2):
    real = {c["name"] for c in v2.companies} | {c.get("old_name") for c in v2.companies if c.get("old_name")}
    names = {s: {n for q in v2.split(s) for n in q["companies"] if n in real} for s in ("search", "validation", "test")}
    assert all(names.values())
    assert not (names["search"] & names["validation"]) and not (names["search"] & names["test"])
    assert not (names["validation"] & names["test"])
    assert [len(v2.split(s)) for s in ("search", "validation", "test")] == [46, 35, 92]


def test_every_question_carries_the_abstention_clause(v2):
    assert all(q["text"].endswith(ABSTAIN_CLAUSE) for q in v2.questions)
    abstain = {s: sum(q["answer_type"] == "abstain" for q in v2.split(s)) for s in ("search", "validation", "test")}
    assert abstain == {"search": 4, "validation": 3, "test": 8}
    assert all(q["gold"] == ABSTAIN_GOLD for q in v2.questions if q["answer_type"] == "abstain")


def test_new_filing_kinds_question_types_and_traps(v2):
    kinds = {d["kind"] for d in v2.docs}
    assert {"annual", "annual_correction", "audit", "q1", "half", "q3", "prelim", "prelim_correction", "rename"} <= kinds
    qtypes = {q["qtype"] for q in v2.questions}
    assert {"cagr_rev", "q3_3m_rev", "q4_op_derived", "roe", "dps_change", "old_dps", "rank2_margin"} <= qtypes
    traps = {t for q in v2.questions for t in q["traps"]}
    assert {"before_restatement", "corrected_preliminary", "wrong_year", "separate_basis"} <= traps
    assert all(NOTICE in d["text"] for d in v2.docs)


def test_preliminary_and_rename_filings_are_never_valid_sources(v2):
    for d in v2.docs:
        if d["kind"] in ("prelim", "prelim_correction", "rename"):
            assert not v2.is_valid_source(d)


@pytest.mark.parametrize("all_gates", [False, True])
def test_oracle_solves_every_v2_question(v2, v2_index, all_gates):
    h = Harness.seed()
    for q in v2.questions:
        inst = compose(h, q["text"])
        if all_gates:
            inst.gates = {k: True for k in inst.gates}
        t = run_episode(v2, v2_index, q, inst, OraclePolicy(q))
        assert t["summary"]["final_accepted"] and t["score"]["correct"], (q["qid"], t["score"], t["summary"]["gate_rejections"])
        assert t["summary"]["turns"] <= inst.config["max_turns"]


def test_abstention_scoring(v2):
    unans = next(q for q in v2.questions if q["answer_type"] == "abstain")
    num = next(q for q in v2.questions if q["answer_type"] == "number")
    assert score(unans, "알 수 없음")["correct"]
    assert score(unans, "공시에서 확인할 수 없습니다")["correct"]
    wrong = score(unans, "1,234.5")
    assert not wrong["correct"] and wrong["trap"] == "answered_unanswerable"
    abst = score(num, "알 수 없음")
    assert not abst["correct"] and abst["status"] == "abstained"
    assert not is_abstain("123.4") and not is_abstain(12.0)


def test_abstaining_final_needs_no_evidence_only_when_the_question_allows_it(v2, v2_index, corpus, index):
    q = next(q for q in v2.questions if q["answer_type"] == "abstain")
    inst = compose(Harness.seed(), q["text"])
    env = ResearchEnv(v2, v2_index, q, inst.config, {k: True for k in inst.gates}, inst.mode)
    assert env.allows_abstain
    assert "final accepted" in env.step({"action": "final", "answer": "알 수 없음", "refs": []})
    v1q = next(q for q in corpus.questions if q["answer_type"] == "number")  # v1 questions have no abstention clause
    inst = compose(Harness.seed(), v1q["text"])
    env = ResearchEnv(corpus, index, v1q, inst.config, inst.gates, inst.mode)
    assert not env.allows_abstain
    assert "final accepted" not in env.step({"action": "final", "answer": "알 수 없음", "refs": []})
