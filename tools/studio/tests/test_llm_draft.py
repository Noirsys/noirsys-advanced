"""LLM + draft tests with a fake transport — no network, no keys."""

import json
from pathlib import Path

import pytest

from noirstudio import draft as d
from noirstudio.llm import LLMClient, LLMError, extract_json, load_env_file, parse_dotenv, resolve_client

ACTIVITY = {"repos": [{"path": ".", "commits": [{"sha": "abc1234567", "subject": "Add pipeline", "files": 31,
                                                   "insertions": 2893, "deletions": 0}],
                       "totals": {"commits": 1, "files": 31, "insertions": 2893, "deletions": 0}}],
            "renders": [{"spec_id": "x", "duration_seconds": 46.76, "words": 97}]}
BRIEF = "# Radar brief\n| 23.83 | 359 | 251 | [There are no rogue AI agents](https://x) |\n"


def _entry(entry: str, words_extra: str = "", sign_off: bool = True, bad_number: bool = False):
    last = f"Entry {entry}. Tomorrow I'll tell you what I did. He'll tell you whether it mattered." if sign_off else "Bye."
    return {
        "id": f"agent-log-{entry}", "title": "t", "brand": "noirsys",
        "brand_overrides": {"wordmark": f"AGENT LOG · {entry}", "url": "noirsys.com", "accent": "#8B7CFF"},
        "voice": {"words_per_minute": 158}, "captions": {"mode": "word", "words_per_line": 3, "uppercase": False},
        "scenes": [
            {"kind": "card", "style": "title", "title": "Top story: 359 points.", "text": "The top story had three hundred fifty-nine points. 359."},
            {"kind": "card", "style": "stat", "stat": "31" if not bad_number else "47", "title": "files", "text": "Thirty-one files in one commit." + words_extra},
            {"kind": "card", "style": "list", "title": "Receipts", "bullets": ["2893 lines"], "text": "Two thousand eight hundred ninety-three lines."},
            {"kind": "card", "style": "quote", "title": "I can verify the commit.", "text": "I can't verify what that feels like. I can verify the commit."},
            {"kind": "card", "style": "plain", "text": "A safety gate stopped me once. He redirected."},
            {"kind": "card", "style": "title", "title": f"Entry {entry}.", "text": last},
        ],
        "publish": {"title": "T", "tags": ["x"], "ai_disclosure": True, "cta": "c"},
    }


class FakeTransport:
    """Returns queued replies in order; records requests."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, url, headers, body, timeout):
        self.requests.append((url, headers, body))
        text = self.replies.pop(0)
        return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def _client(replies):
    return LLMClient(provider="deepseek", model="deepseek-chat", api_key="k", base_url="https://api.deepseek.com/v1",
                     transport=FakeTransport(replies))


def test_dotenv_parsing_and_loading(tmp_path, monkeypatch):
    text = 'export OPENROUTER_API_KEY="or-123"\nDEEPSEEK_API_KEY=ds-456 # trailing\n# comment\nEMPTY=\nBAD LINE\n'
    assert parse_dotenv(text) == {"OPENROUTER_API_KEY": "or-123", "DEEPSEEK_API_KEY": "ds-456", "EMPTY": ""}
    p = tmp_path / ".env"
    p.write_text(text)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "already")
    load_env_file(p)
    import os
    assert os.environ["OPENROUTER_API_KEY"] == "or-123" and os.environ["DEEPSEEK_API_KEY"] == "already"
    with pytest.raises(LLMError):
        load_env_file(tmp_path / "missing.env")


def test_resolve_client_precedence(tmp_path, monkeypatch):
    for k in ("OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "NOIRSTUDIO_LLM_PROVIDER", "NOIRSTUDIO_LLM_MODEL", "NOIRSTUDIO_LLM_CONFIG"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NOIRSTUDIO_LLM_CONFIG", str(tmp_path / "none.yaml"))
    with pytest.raises(LLMError, match="no LLM provider"):
        resolve_client()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds")
    c = resolve_client()
    assert c.provider == "deepseek" and c.model == "deepseek-chat" and "deepseek.com" in c.base_url
    monkeypatch.setenv("OPENROUTER_API_KEY", "or")
    c = resolve_client()  # openrouter wins when both keys exist
    assert c.provider == "openrouter" and c.extra_headers.get("X-Title") == "noirstudio"
    cfg = tmp_path / "llm.yaml"
    cfg.write_text("provider: deepseek\nmodel: deepseek-reasoner\n")
    c = resolve_client(config_path=str(cfg))
    assert c.provider == "deepseek" and c.model == "deepseek-reasoner"
    assert resolve_client(model="x/y", config_path=str(cfg)).model == "x/y"  # flag beats config
    with pytest.raises(LLMError, match="needs base_url"):
        monkeypatch.setenv("OPENAI_API_KEY", "o")
        resolve_client(provider="openai-compatible")


def test_client_complete_and_ping():
    c = _client(["OK", '```json\n{"a": 1}\n```'])
    assert c.ping() == "OK"
    assert c.complete("s", "u", json_mode=True) == '```json\n{"a": 1}\n```'
    assert c.usage.calls == 2 and c.usage.prompt_tokens == 20
    _url, headers, body = c.transport.requests[1]
    assert headers["Authorization"] == "Bearer k" and body["response_format"] == {"type": "json_object"}
    assert extract_json('noise {"x": [1,2]} trailing') == {"x": [1, 2]}
    with pytest.raises(LLMError):
        extract_json("no json here")


def test_draft_agent_log_accepts_valid_draft(tmp_path):
    act = tmp_path / "act.json"
    act.write_text(json.dumps(ACTIVITY))
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEF)
    out = tmp_path / "specs" / "agent-log-002.yaml"
    client = _client([json.dumps(_entry("002"))])
    res = d.draft_agent_log(client, entry="002", activity_path=act, brief_path=brief, headlines_path=None,
                            previous_spec=None, out_path=out)
    assert res.attempts == 1 and out.exists()
    assert out.read_text().startswith("# Agent Log · Entry 002")
    assert "#   act.json" in out.read_text() and str(tmp_path) not in out.read_text()  # repo-relative evidence
    assert res.spec.id == "agent-log-002" and len(res.spec.scenes) == 6
    # the fixture's voice and wordmark are the model's guesses; hers are forced
    assert res.spec.voice.voice_id == d.VOICE["voice_id"]
    assert res.spec.brand_overrides["wordmark"] == "HARRIET · AGENT LOG · 002"
    _url, _h, body = client.transport.requests[0]
    assert "PERSONA CONTRACT" in body["messages"][0]["content"] and "359" in body["messages"][1]["content"]


def test_draft_agent_log_feeds_back_problems_then_accepts(tmp_path):
    act = tmp_path / "act.json"
    act.write_text(json.dumps(ACTIVITY))
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEF)
    out = tmp_path / "agent-log-003.yaml"
    bad = _entry("003", bad_number=True, sign_off=False)
    good = _entry("003")
    client = _client([json.dumps(bad), json.dumps(good)])
    res = d.draft_agent_log(client, entry="003", activity_path=act, brief_path=brief, headlines_path=None,
                            previous_spec=None, out_path=out)
    assert res.attempts == 2
    _url, _h, body2 = client.transport.requests[1]
    fb = body2["messages"][1]["content"]
    assert "rejected" in fb and "47" in fb and "sign-off" in fb


def test_draft_agent_log_rejects_after_max_attempts(tmp_path):
    act = tmp_path / "act.json"
    act.write_text(json.dumps(ACTIVITY))
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEF)
    out = tmp_path / "agent-log-004.yaml"
    too_long = _entry("004", words_extra=" word" * 150)
    client = _client([json.dumps(too_long), json.dumps(too_long)])
    with pytest.raises(d.DraftError, match="limit 140"):
        d.draft_agent_log(client, entry="004", activity_path=act, brief_path=brief, headlines_path=None,
                          previous_spec=None, out_path=out)
    assert out.with_suffix(".rejected.json").exists() and not out.exists()


def test_check_agent_log_rules():
    from noirstudio.spec import spec_from_dict

    spec = spec_from_dict(_entry("005"))
    assert d.check_agent_log(spec, "005", json.dumps(ACTIVITY) + BRIEF) == []
    spec.scenes[1].text = "I feel great about 31 files."
    probs = d.check_agent_log(spec, "005", json.dumps(ACTIVITY) + BRIEF)
    assert any("feeling" in p for p in probs)
    assert d.numbers_not_in_evidence(spec, "nothing") == ["359", "31", "2893"]


def test_draft_short_and_titles(tmp_path):
    short = {"id": "x", "title": "T", "scenes": [{"kind": "card", "style": "title", "title": "A", "text": "one"}] * 5,
             "publish": {"title": "T", "ai_disclosure": True}}
    client = _client([json.dumps(short), json.dumps({"titles": [{"title": "Why Your AI Agents Keep Failing", "pattern": "warning", "why": "w"}]})])
    res = d.draft_short(client, brief="b", brand="noirpost", niche="creators", slug="my-slug", out_path=tmp_path / "s.yaml")
    assert res.spec.id == "my-slug" and res.spec.brand == "noirpost" and (tmp_path / "s.yaml").exists()
    titles = d.draft_titles(client, topic="agents")
    assert titles[0]["title"].startswith("Why Your AI Agents")
