"""LLM access for drafting: OpenRouter, DeepSeek, or any OpenAI-compatible endpoint.

Keys are never stored in the repo. Resolution order for each setting:
  CLI flag  >  environment variable  >  --env-file (dotenv)  >  config file
Config file: $NOIRSTUDIO_LLM_CONFIG or ~/.config/noirstudio/llm.yaml, e.g.

    provider: openrouter            # openrouter | deepseek | openai-compatible
    model: deepseek/deepseek-chat-v3.1
    # base_url: http://localhost:11434/v1   (openai-compatible only)
    # api_key_env: MY_KEY_VAR             (name of the env var holding the key)

Both OpenRouter and DeepSeek speak the OpenAI chat-completions format, so one
client covers all providers.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml

PROVIDERS: Dict[str, dict] = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "default_model": "deepseek/deepseek-chat-v3.1",
        "headers": {"HTTP-Referer": "https://noirsys.com", "X-Title": "noirstudio"},
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "headers": {},
    },
    "openai-compatible": {
        "base_url": None,  # must be given (e.g. Ollama/vLLM/LM Studio)
        "api_key_env": "OPENAI_API_KEY",
        "default_model": None,
        "headers": {},
    },
}


class LLMError(RuntimeError):
    pass


# Cloudflare-fronted endpoints block Python-urllib's default User-Agent (error 1010)
USER_AGENT = "noirstudio/0.1 (+https://github.com/Noirsys/noirsys-advanced)"


# --- dotenv / config ------------------------------------------------------------

_DOTENV_LINE = re.compile(r"""^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$""")


def parse_dotenv(text: str) -> Dict[str, str]:
    """Minimal .env parser: KEY=value, quotes stripped, # comments, `export` allowed."""
    out: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _DOTENV_LINE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if val[:1] in ("'", '"') and val[-1:] == val[:1] and len(val) >= 2:
            val = val[1:-1]
        else:
            val = val.split(" #", 1)[0].strip()
        out[key] = val
    return out


def load_env_file(path: Path | str, override: bool = False) -> Dict[str, str]:
    """Load a dotenv file into os.environ (existing values win unless override)."""
    p = Path(path).expanduser()
    if not p.exists():
        raise LLMError(f"env file not found: {p}")
    values = parse_dotenv(p.read_text(encoding="utf-8"))
    for k, v in values.items():
        if override or k not in os.environ:
            os.environ[k] = v
    return values


def default_config_path() -> Path:
    env = os.environ.get("NOIRSTUDIO_LLM_CONFIG")
    return Path(env).expanduser() if env else Path("~/.config/noirstudio/llm.yaml").expanduser()


def load_config(path: Optional[Path | str] = None) -> dict:
    p = Path(path).expanduser() if path else default_config_path()
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise LLMError(f"config {p} must be a mapping")
    return data


# --- client ---------------------------------------------------------------------


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    seconds: float = 0.0


Transport = Callable[[str, dict, dict, int], dict]


def _http_transport(url: str, headers: dict, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise LLMError(f"HTTP {exc.code} from {url}: {detail}") from None
    except urllib.error.URLError as exc:
        raise LLMError(f"cannot reach {url}: {exc.reason}") from None


@dataclass
class LLMClient:
    provider: str
    model: str
    api_key: str
    base_url: str
    extra_headers: Dict[str, str] = field(default_factory=dict)
    timeout: int = 180
    transport: Transport = _http_transport
    usage: Usage = field(default_factory=Usage)

    def complete(self, system: str, user: str, *, temperature: float = 0.4, max_tokens: int = 2000,
                 json_mode: bool = False) -> str:
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT,
                   **self.extra_headers}
        if self.api_key:  # a key-less server, or one whose proxy injects the credential, gets no header
            headers["Authorization"] = f"Bearer {self.api_key}"
        t0 = time.time()
        data = self.transport(f"{self.base_url.rstrip('/')}/chat/completions", headers, body, self.timeout)
        self.usage.seconds += time.time() - t0
        self.usage.calls += 1
        if "error" in data and not data.get("choices"):
            raise LLMError(f"{self.provider} error: {data['error']}")
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"unexpected response shape from {self.provider}: {str(data)[:300]}") from None
        u = data.get("usage") or {}
        self.usage.prompt_tokens += int(u.get("prompt_tokens", 0) or 0)
        self.usage.completion_tokens += int(u.get("completion_tokens", 0) or 0)
        return text or ""

    def ping(self) -> str:
        return self.complete("You are a health check.", "Reply with exactly: OK", temperature=0, max_tokens=5).strip()


def resolve_client(provider: Optional[str] = None, model: Optional[str] = None, *,
                   env_file: Optional[str] = None, config_path: Optional[str] = None,
                   base_url: Optional[str] = None, api_key: Optional[str] = None,
                   transport: Transport = _http_transport) -> LLMClient:
    """Build a client from flags > env > env-file > config, with clear errors."""
    if env_file:
        load_env_file(env_file)
    cfg = load_config(config_path)

    provider = provider or os.environ.get("NOIRSTUDIO_LLM_PROVIDER") or cfg.get("provider")
    if not provider:
        for name in ("openrouter", "deepseek"):  # first provider with a key wins
            if os.environ.get(PROVIDERS[name]["api_key_env"]):
                provider = name
                break
    if not provider:
        raise LLMError("no LLM provider: set OPENROUTER_API_KEY or DEEPSEEK_API_KEY (or --env-file / config)")
    if provider not in PROVIDERS:
        raise LLMError(f"unknown provider `{provider}`; known: {sorted(PROVIDERS)}")
    spec = PROVIDERS[provider]

    key_env = cfg.get("api_key_env") or spec["api_key_env"]
    api_key = api_key or os.environ.get(key_env)
    if not api_key:
        raise LLMError(f"{key_env} is not set (provider {provider}); pass --env-file /path/to/.env or export it")
    base_url = base_url or os.environ.get("NOIRSTUDIO_LLM_BASE_URL") or cfg.get("base_url") or spec["base_url"]
    if not base_url:
        raise LLMError(f"provider {provider} needs base_url (config or NOIRSTUDIO_LLM_BASE_URL)")
    model = model or os.environ.get("NOIRSTUDIO_LLM_MODEL") or cfg.get("model") or spec["default_model"]
    if not model:
        raise LLMError(f"provider {provider} needs a model (--model, NOIRSTUDIO_LLM_MODEL, or config)")
    return LLMClient(provider=provider, model=model, api_key=api_key, base_url=base_url,
                     extra_headers=dict(spec["headers"]), transport=transport)


# --- helpers for structured output --------------------------------------------------

_FENCE = re.compile(r"```(?:json|yaml|yml)?\s*(.*?)```", re.S)


def _mend_json(text: str) -> str:
    """The slip models make in a long JSON reply: a value opened with a double quote and closed with a single one at the
    end of its line (`"after": "...no lingering.',`). Only such lines are touched, and only when the text would not parse."""
    fixed = []
    for line in text.split("\n"):
        m = re.match(r"^(\s*\"[^\"\\]+\"\s*:\s*\")(.*)['\u2019](,?)\s*$", line)
        if m and not re.search(r'(?<!\\)"\s*,?\s*$', line):
            line = m.group(1) + m.group(2) + '"' + m.group(3)
        fixed.append(line)
    return "\n".join(fixed)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (fenced or bare). A reply that is nearly JSON (a raw tab or
    newline inside a string, a closing quote of the wrong kind) is mended rather than thrown away."""
    candidates: List[str] = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for cand in candidates:
        start, end = cand.find("{"), cand.rfind("}")
        if start == -1 or end <= start:
            continue
        body = cand[start : end + 1]
        for attempt in (body, _mend_json(body)):
            try:
                obj = json.loads(attempt, strict=False)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    raise LLMError("model reply contained no JSON object:\n" + text[:400])
