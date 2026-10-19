import pytest

from harnessforge.harness import EditError, Harness, compose


def test_seed_harnesses_are_valid():
    for v in ("longharness", "notes"):
        h = Harness.seed(v)
        assert h.validate() == []
        assert h.config()["state_mode"] == v


def test_component_and_scope_restrictions():
    h = Harness.seed()
    child, done = h.apply([{"op": "set_config", "scope": "general", "key": "read_chars", "value": "1800"}],
                          component="tools", scope="general")
    assert child.config()["read_chars"] == 1800 and child.hash != h.hash
    with pytest.raises(EditError):
        h.apply([{"op": "set_config", "scope": "general", "key": "max_turns", "value": "20"}], component="tools", scope="general")
    with pytest.raises(EditError):
        h.apply([{"op": "write_skill", "scope": "general", "name": "x", "content": "y"}], component="logic", scope="general")
    with pytest.raises(EditError):
        h.apply([{"op": "append_text", "scope": "domain", "file": "domain.md", "content": "z"}], component="logic", scope="general")
    with pytest.raises(EditError):
        h.apply([{"op": "set_gate", "scope": "general", "key": "correction_check", "value": "true"}], component="logic", scope="general")


def test_bounds_frozen_keys_and_noop():
    h = Harness.seed()
    child, _ = h.apply([{"op": "set_config", "scope": "domain", "key": "max_turns", "value": "999"}])
    assert child.config()["max_turns"] == 30
    with pytest.raises(EditError):
        h.apply([{"op": "set_config", "scope": "general", "key": "state_mode", "value": "notes"}])
    with pytest.raises(EditError):
        h.apply([{"op": "set_gate", "scope": "general", "key": "numeric_answer", "value": "true"}])  # already true


def test_leakage_guard():
    h = Harness.seed()
    with pytest.raises(EditError):
        h.apply([{"op": "write_skill", "scope": "domain", "name": "cheat", "content": "한빛전자 영업이익은 크다"}],
                forbidden_terms=["한빛전자"])
    with pytest.raises(EditError):
        h.apply([{"op": "append_text", "scope": "general", "file": "system.md", "content": "answer is 12,345,678"}])


def test_skills_move_and_compose_router():
    h = Harness.seed()
    h2, _ = h.apply([{"op": "write_skill", "scope": "domain", "name": "corrections", "when": ["최종"],
                      "summary": "prefer corrected filings", "content": "Check list_docs for [기재정정]."}])
    inst = compose(h2, "최종 확정 공시 기준으로 답하시오")
    assert "domain/corrections" in inst.skills and "[기재정정]" in inst.system
    inst2 = compose(h2, "아무 관련 없는 질문")
    assert "domain/corrections" not in inst2.skills
    h3, _ = h2.apply([{"op": "move_skill", "scope": "domain", "name": "corrections", "to": "general"}], component="generalize")
    assert [s.scope for s in h3.skills() if s.name == "corrections"] == ["general"]


def test_transfer_mode_loads_general_components_only():
    h = Harness.seed()
    h2, _ = h.apply([{"op": "set_gate", "scope": "domain", "key": "correction_check", "value": "true"}])
    full = compose(h2, "q", scopes=("general", "domain"))
    gen = compose(h2, "q", scopes=("general",))
    assert full.gates["correction_check"] is True
    assert "correction_check" not in gen.gates and "Domain notes" not in gen.system


def test_save_load_roundtrip(tmp_path):
    h = Harness.seed()
    h.save(tmp_path / "h")
    assert Harness.load(tmp_path / "h").hash == h.hash


@pytest.mark.parametrize("ops", [["not an object"], [None], [{"op": "write_skill", "scope": "general", "name": "x",
                                                                "content": "y", "when": 3}],
                                 [{"op": "set_config", "scope": "general", "key": "read_chars", "value": "inf"}],
                                 [{"op": "move_skill", "scope": "general", "name": "table_reading", "to": "domain"}]])
def test_malformed_ops_raise_edit_error(ops):
    h = Harness.seed()
    if ops and isinstance(ops[0], dict) and ops[0].get("when") == 3:
        child, _ = h.apply(ops)  # a non-list trigger is coerced, not a crash
        assert any(s.name == "x" for s in child.skills())
        return
    with pytest.raises(EditError):
        h.apply(ops)
