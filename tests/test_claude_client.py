"""Claude editor client against a fake SDK object (no network, no key)."""

from types import SimpleNamespace

import pytest

anthropic = pytest.importorskip("anthropic")

from harnessforge.claude import AnthropicClient, claude_schema, resolve_api_key  # noqa: E402
from harnessforge.evolve import editor as E  # noqa: E402
from harnessforge.llm import LLMError  # noqa: E402


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def reply(text, stop="end_turn", content_extra=()):
    usage = SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    content = list(content_extra) + [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=content, usage=usage, stop_reason=stop)


def client(replies):
    msgs = FakeMessages(replies)
    fake = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    return AnthropicClient("claude-opus-5-5", effort="medium", client=fake), msgs


def test_schema_adaptation_keeps_ollama_limits_out_of_the_api():
    s = claude_schema(E.op_schema(E.OPS_BY_COMPONENT["any"], "general"))
    text = repr(s)
    assert "maxLength" not in text
    assert s["additionalProperties"] is False
    assert all(v["additionalProperties"] is False for v in s["properties"]["ops"]["items"]["anyOf"])
    # the original schema is untouched
    assert "maxLength" in repr(E.op_schema(E.OPS_BY_COMPONENT["any"], "general"))


def test_json_call_sends_current_api_shape_and_tracks_cost():
    c, msgs = client([reply('{"decision": "keep", "rationale": "no contrast"}')])
    out, u = c.json_call("sys", "prompt", E.COMPOSE_SCHEMA)
    assert out["decision"] == "keep"
    kw = msgs.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"]["effort"] == "medium" and kw["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in kw and "thinking" not in kw
    assert c.usd == pytest.approx((1000 * 4 + 200 * 20) / 1e6)
    assert c.stats()["calls"] == 1


def test_refusal_and_fallback_accounting():
    fb = SimpleNamespace(type="fallback")
    c, _ = client([reply('{"decision": "keep", "rationale": "r"}', content_extra=[fb])])
    c.json_call("s", "p", E.COMPOSE_SCHEMA)
    assert c.fallbacks_used == 1
    c2, _ = client([reply("", stop="refusal")])
    with pytest.raises(LLMError) as e:
        c2.json_call("s", "p", E.COMPOSE_SCHEMA)
    assert not e.value.fatal  # a refusal is one unusable reply, not a reason to stop the run


def test_fatal_errors_stop_runs():
    req = SimpleNamespace(method="POST", url="https://api.anthropic.com/v1/messages")
    resp401 = SimpleNamespace(status_code=401, headers={}, request=req)
    err = anthropic.AuthenticationError("bad key", response=resp401, body=None)
    c, _ = client([err])
    with pytest.raises(LLMError) as e:
        c.json_call("s", "p", E.COMPOSE_SCHEMA)
    assert e.value.fatal and e.value.auth


def test_key_resolution_prefers_env_then_file(monkeypatch, tmp_path):
    f = tmp_path / "k.txt"
    f.write_text("﻿sk-test-file\n", encoding="utf-8")
    monkeypatch.setenv("HARNESSFORGE_KEY_FILE", str(f))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert resolve_api_key() == "sk-test-file"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-env")
    assert resolve_api_key() == "sk-test-env"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("HARNESSFORGE_KEY_FILE", str(tmp_path / "missing.txt"))
    assert resolve_api_key() is None
    with pytest.raises(LLMError) as e:
        AnthropicClient("claude-opus-5-5")
    assert e.value.auth


def test_haiku_gets_no_fallback_parameter():
    msgs = FakeMessages([reply('{"decision": "keep", "rationale": "r"}')])
    fake = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    c = AnthropicClient("claude-haiku-5-5", effort="low", client=fake)
    c.json_call("s", "p", E.COMPOSE_SCHEMA)
    kw = msgs.calls[0]
    assert "fallbacks" not in kw and "betas" not in kw and kw["output_config"]["effort"] == "low"
    assert c.usd == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6)
