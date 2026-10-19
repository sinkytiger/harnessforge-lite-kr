from harnessforge.corpus import build_corpus
from harnessforge.corpus.render import NOTICE
from harnessforge.scoring import within


def test_deterministic(corpus):
    again = build_corpus(7)
    assert again.meta["sha256_16"] == corpus.meta["sha256_16"]
    assert [q["qid"] for q in again.questions] == [q["qid"] for q in corpus.questions]
    assert build_corpus(8).meta["sha256_16"] != corpus.meta["sha256_16"]


def test_every_document_carries_the_synthetic_notice(corpus):
    assert all(NOTICE in d["text"] for d in corpus.docs)


def test_corpus_is_far_larger_than_a_small_context(corpus):
    assert corpus.n_chars > 400_000
    assert len(corpus.docs) > 80


def test_splits_are_disjoint_by_company(corpus):
    search = {c for q in corpus.split("search") for c in q["companies"]}
    test = {c for q in corpus.split("test") for c in q["companies"]}
    assert search and test and not (search & test)


def test_printed_values_sit_at_recorded_offsets(corpus):
    for f in corpus.facts[:400]:
        text = corpus.by_id[f["doc_id"]]["text"]
        printed = f"{abs(f['printed']):,}"
        assert text[f["offset"]:f["offset"] + len(printed)] == printed


def test_canonical_fact_prefers_the_correction_and_skips_preliminary(corpus):
    corrected = [c for c in corpus.companies if c["correction"]]
    assert corrected
    for c in corrected:
        f = corpus.canonical_fact((c["key"], "연결", "영업이익", "FY2025"))
        doc = corpus.by_id[f["doc_id"]]
        assert doc["kind"] == "annual_correction"
        originals = [o for o in corpus.occurrences((c["key"], "연결", "영업이익", "FY2025"))
                     if corpus.by_id[o["doc_id"]].get("corrected_by")]
        assert originals and all(o["printed"] != f["printed"] for o in originals)
    for c in [c for c in corpus.companies if c["preliminary"]]:
        f = corpus.canonical_fact((c["key"], "연결", "매출액", "FY2025"))
        assert corpus.by_id[f["doc_id"]]["kind"] != "prelim"


def test_traps_are_distinguishable_from_gold(corpus):
    for q in corpus.questions:
        if q["answer_type"] != "number":
            continue
        for name, v in q["traps"].items():
            assert not within(v, q["gold"], q["tol_abs"], q["tol_rel"]), (q["qid"], name)


def test_question_mix_covers_every_trap_family(corpus):
    names = {t for q in corpus.split("test") for t in q["traps"]}
    for needed in ("before_correction", "preliminary", "separate_basis", "cumulative_column", "unit_slip"):
        assert needed in names


def test_save_and_load_roundtrip(corpus, tmp_path):
    from harnessforge.corpus import Corpus
    corpus.save(tmp_path / "c")
    back = Corpus.load(tmp_path / "c")
    assert back.meta == corpus.meta
    assert len(back.facts) == len(corpus.facts)
    assert back.questions == corpus.questions
