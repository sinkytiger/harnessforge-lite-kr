"""Claude (Anthropic API) client for the editor role. Optional: `pip install -e ".[claude]"`.

Same interface as OllamaClient (`json_call`, `chat`, `usage`, `name`), so it can be used as the
harness editor while the executor stays a free local model:

    python -m harnessforge evolve --model qwen3:4b --editor-model claude-opus-5-5 ...

Credentials: the ANTHROPIC_API_KEY environment variable, or (when it is not set) a key file outside
the repository, by default ~/.harnessforge/anthropic_api_key.txt (override the path with
HARNESSFORGE_KEY_FILE). The key is never logged or written anywhere by this module.

Request settings follow the current API: structured JSON output through `output_config.format`,
reasoning depth through `output_config.effort` (Claude Opus 5.5 always thinks; sampling parameters
are not accepted), and server-side refusal fallbacks (`fallbacks="default"`), so a false-positive
safety decline is retried on Anthropic's recommended fallback model instead of failing the run.
"""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

from .llm import LLMError, Usage, extract_json

# $ per million tokens: input, output, cache read (first-party API rates, 2026-10).
PRICES = {"claude-opus-5-5": (4.0, 20.0, 0.20), "claude-sonnet-5-5": (2.0, 10.0, 0.20),
          "claude-haiku-5-5": (0.10, 0.50, 0.01)}
UNSUPPORTED = ("maxLength", "minLength", "minimum", "maximum", "multipleOf", "maxItems", "minItems")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Server-side refusal fallbacks exist for these models only (Claude Haiku 5.5 has none).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


def key_file() -> Path:
    return Path(os.environ.get("HARNESSFORGE_KEY_FILE") or Path.home() / ".harnessforge" / "anthropic_api_key.txt")


def resolve_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    f = key_file()
    if f.is_file():
        key = f.read_text(encoding="utf-8-sig").strip()
        return key or None
    return None


def claude_schema(schema: dict) -> dict:
    """Adapt a JSON schema to structured outputs: every object gets additionalProperties=false and
    unsupported constraints (string lengths, numeric bounds) are removed. Length limits are still
    enforced for Ollama models, which accept them."""
    s = copy.deepcopy(schema)

    def fix(node):
        if isinstance(node, dict):
            for k in UNSUPPORTED:
                node.pop(k, None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)

    fix(s)
    return s


class AnthropicClient:
    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium", max_tokens: int = 16000,
                 timeout: float = 600.0, max_retries: int = 4, client=None) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.usage = Usage()
        self.usd = 0.0
        self.fallbacks_used = 0
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on the environment
                raise LLMError('the anthropic package is not installed: pip install -e ".[claude]"', auth=True) from exc
            key = resolve_api_key()
            if not key:
                raise LLMError(f"no Anthropic API key: set ANTHROPIC_API_KEY or create {key_file()}", auth=True)
            client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=max_retries)
        self.client = client

    @property
    def name(self) -> str:
        return f"anthropic:{self.model}"

    def _price(self, u) -> float:
        p_in, p_out, p_cache = PRICES.get(self.model, (4.0, 20.0, 0.20))
        cache_read = int(getattr(u, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
        return ((int(u.input_tokens or 0) * p_in + cache_write * p_in * 1.25 + cache_read * p_cache
                 + int(u.output_tokens or 0) * p_out) / 1_000_000)

    def _create(self, system: str, messages: list[dict], schema: dict | None):
        import anthropic
        output_config: dict = {"effort": self.effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": claude_schema(schema)}
        extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if self.model in FALLBACK_MODELS else {}
        try:
            return self.client.beta.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system, messages=messages,
                output_config=output_config, **extra)
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic API key was rejected", status=401, auth=True) from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError(f"Anthropic API permission denied: {exc.message}", status=403, auth=True) from exc
        except anthropic.RateLimitError as exc:
            raise LLMError(f"Anthropic rate limit after retries: {exc.message}", status=429, transport=True) from exc
        except anthropic.BadRequestError as exc:
            msg = str(exc.message)
            raise LLMError(f"Anthropic request rejected: {msg[:300]}", status=400,
                           quota="credit balance" in msg.lower(), auth="credit balance" not in msg.lower()) from exc
        except anthropic.APITimeoutError as exc:
            raise LLMError("Anthropic request timed out", timeout=True) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("cannot reach the Anthropic API", transport=True) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}", status=exc.status_code, transport=True) from exc

    def chat(self, messages: list[dict], schema: dict | None = None, max_tokens: int = 512,
             temperature: float | None = None) -> tuple[str, Usage]:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        t = time.time()
        resp = self._create(system, rest, schema)
        u = Usage(1, int(resp.usage.input_tokens or 0) + int(getattr(resp.usage, "cache_read_input_tokens", 0) or 0),
                  int(resp.usage.output_tokens or 0), time.time() - t)
        self.usage.add(u)
        self.usd += self._price(resp.usage)
        if any(getattr(b, "type", "") == "fallback" for b in resp.content):
            self.fallbacks_used += 1
        if resp.stop_reason == "refusal":
            raise LLMError("the model declined this request (refusal)")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return text, u

    def json_call(self, system: str, prompt: str, schema: dict, max_tokens: int = 600,
                  temperature: float | None = None) -> tuple[dict, Usage]:
        text, u = self.chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}], schema)
        try:
            return extract_json(text), u
        except LLMError:
            text2, u2 = self.chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}], schema)
            u.add(u2)
            return extract_json(text2), u

    def stats(self) -> dict:
        return self.usage.to_json() | {"usd": round(self.usd, 4), "fallbacks_used": self.fallbacks_used,
                                        "model": self.model, "effort": self.effort}


def check(model: str = "claude-opus-5-5") -> str:
    """One tiny structured request; returns a one-line status. Never prints the key."""
    c = AnthropicClient(model, effort="low", max_tokens=2000)
    out, _ = c.json_call("Reply in JSON.", "Return ok=true.", {"type": "object", "properties": {"ok": {"type": "boolean"}},
                                                               "required": ["ok"]})
    return f"{model}: ok={out.get('ok')} tokens={c.usage.total_tokens} cost=${c.usd:.4f}"


if __name__ == "__main__":  # python -m harnessforge.claude
    print(json.dumps({"key_source": "env" if os.environ.get("ANTHROPIC_API_KEY") else str(key_file()),
                      "key_found": resolve_api_key() is not None}))
