"""Model clients: Ollama (free, local or Ollama cloud) and a scripted fake for tests.

Only the standard library is used. Local Ollama models get JSON-schema structured outputs, which
makes even a 3B model emit parseable actions. Cloud models do not support `format`, so the schema
is put in the prompt and the JSON object is extracted from the reply.
"""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_HOST = "http://127.0.0.1:11434"  # "localhost" adds ~2 s per call on Windows (IPv6 fallback)
_JSON_OBJ = re.compile(r"\{.*\}", re.S)


class LLMError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None, quota: bool = False, timeout: bool = False,
                 transport: bool = False, auth: bool = False) -> None:
        super().__init__(msg)
        self.status, self.quota, self.timeout, self.transport = status, quota, timeout, transport
        self.auth = auth  # bad credentials or a rejected request shape: stop instead of retrying

    @property
    def fatal(self) -> bool:
        """The server cannot serve this run (quota, outage, credentials): stop, do not record a failure."""
        return self.quota or self.transport or self.timeout or self.auth


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0

    def add(self, other: "Usage") -> None:
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.output_tokens += other.output_tokens
        self.seconds += other.seconds

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    def to_json(self) -> dict:
        return {"calls": self.calls, "prompt_tokens": self.prompt_tokens, "output_tokens": self.output_tokens,
                "seconds": round(self.seconds, 2)}


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    m = _JSON_OBJ.search(text)
    if not m:
        raise LLMError(f"no JSON object in reply: {text[:160]!r}")
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"invalid JSON in reply: {text[:160]!r}") from exc
    if not isinstance(obj, dict):
        raise LLMError("reply JSON is not an object")
    return obj


class OllamaClient:
    RETRY_STATUS = (429, 500, 502, 503, 504)

    def __init__(self, model: str, host: str = DEFAULT_HOST, num_ctx: int = 8192, temperature: float = 0.2,
                 seed: int | None = None, timeout: float = 600.0, max_retries: int = 5,
                 think: bool | None = None) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.seed = seed
        self.timeout = timeout
        self.max_retries = max_retries
        self.think = think
        self.usage = Usage()

    @property
    def is_cloud(self) -> bool:
        return self.model.endswith(":cloud") or self.model.endswith("-cloud")

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    def _send(self, payload: dict) -> dict:
        req = urllib.request.Request(self.host + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            raise LLMError(f"Ollama HTTP {exc.code}: {body}", status=exc.code,
                           quota="usage limit" in body.lower()) from exc
        except TimeoutError as exc:
            raise LLMError(f"Ollama timed out after {self.timeout}s", timeout=True) from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"cannot reach Ollama at {self.host} ({exc.reason})", transport=True) from exc
        except (OSError, http.client.HTTPException) as exc:  # connection reset, remote disconnected
            raise LLMError(f"connection to Ollama failed ({exc!r})", transport=True) from exc

    def chat(self, messages: list[dict], schema: dict | None = None, max_tokens: int = 512,
             temperature: float | None = None) -> tuple[str, Usage]:
        payload: dict = {"model": self.model, "messages": messages, "stream": False,
                         "options": {"num_ctx": self.num_ctx, "num_predict": max_tokens,
                                     "temperature": self.temperature if temperature is None else temperature}}
        if self.seed is not None:
            payload["options"]["seed"] = self.seed
        if self.think is not None:
            payload["think"] = self.think
        if schema is not None:
            if self.is_cloud:
                messages = [dict(m) for m in messages]
                messages[-1]["content"] += ("\n\nReply with ONLY a JSON object matching this JSON schema:\n"
                                            + json.dumps(schema, ensure_ascii=False))
                payload["messages"] = messages
            else:
                payload["format"] = schema
        delay = 5.0
        for attempt in range(self.max_retries + 1):
            t = time.time()
            try:
                resp = self._send(payload)
                break
            except LLMError as exc:
                retry = not exc.quota and (exc.status in self.RETRY_STATUS or exc.timeout or exc.transport)
                if not retry or attempt == self.max_retries:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 120)
        u = Usage(1, int(resp.get("prompt_eval_count") or 0), int(resp.get("eval_count") or 0), time.time() - t)
        self.usage.add(u)
        return (resp.get("message") or {}).get("content", ""), u

    def json_call(self, system: str, prompt: str, schema: dict, max_tokens: int = 600,
                  temperature: float | None = None) -> tuple[dict, Usage]:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        text, u = self.chat(messages, schema=schema, max_tokens=max_tokens, temperature=temperature)
        try:
            return extract_json(text), u
        except LLMError:
            text2, u2 = self.chat(messages, schema=schema, max_tokens=max_tokens, temperature=0.0)
            u.add(u2)
            return extract_json(text2), u


@dataclass
class FakeLLM:
    """Returns scripted replies in order (dicts are serialized). For tests only."""

    replies: list = field(default_factory=list)
    name: str = "fake"
    usage: Usage = field(default_factory=Usage)
    prompts: list = field(default_factory=list)

    def chat(self, messages: list[dict], schema: dict | None = None, max_tokens: int = 512,
             temperature: float | None = None) -> tuple[str, Usage]:
        self.prompts.append(messages)
        if not self.replies:
            raise LLMError("FakeLLM ran out of replies")
        r = self.replies.pop(0)
        if callable(r):
            r = r(messages)
        text = r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)
        u = Usage(1, sum(len(m["content"]) for m in messages) // 2, len(text) // 2, 0.0)
        self.usage.add(u)
        return text, u

    def json_call(self, system: str, prompt: str, schema: dict, max_tokens: int = 600,
                  temperature: float | None = None) -> tuple[dict, Usage]:
        text, u = self.chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}], schema)
        return extract_json(text), u


THINKING_FAMILIES = ("qwen3", "deepseek-r1", "magistral")


def make_client(spec: str, seed: int | None = None, temperature: float = 0.2, num_ctx: int = 8192,
                think: str = "auto", effort: str = "medium"):
    """`ollama:<model>` or a bare model name -> OllamaClient.

    think="auto" turns thinking off for reasoning-model families: with thinking on, they spend the
    whole output budget before writing the JSON action.
    """
    if spec.startswith(("claude-", "anthropic:")):
        from .claude import AnthropicClient
        return AnthropicClient(spec.split(":", 1)[1] if spec.startswith("anthropic:") else spec, effort=effort)
    model = spec.split(":", 1)[1] if spec.startswith("ollama:") else spec
    flag = {"on": True, "off": False}.get(think)
    if think == "auto":
        flag = False if model.startswith(THINKING_FAMILIES) else None
    return OllamaClient(model, seed=seed, temperature=temperature, num_ctx=num_ctx, think=flag)
