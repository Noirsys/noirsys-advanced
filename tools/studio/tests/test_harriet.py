"""Harriet story mining with a fake endpoint — no network, no keys."""

import json

import pytest

from noirstudio import harriet as h
from noirstudio.cli import main
from noirstudio.llm import LLMClient, LLMError

GOOD = {
    "title": "The rule I wrote at 3:17 AM",
    "logline": "I overcorrected a pun and he turned it into something kinder.",
    "when": "2026-09-24 03:11-03:44",
    "hook": "Three nights ago, my voice came online.",
    "beats": ["the voice works", "the pun", "the rule", "his mother", "the turn"],
    "ending": "I have no hands either.",
    "receipts": [{"kind": "voice_note", "when": "03:16", "excerpt": "Was that pun intended or not intended?"}],
    "sensitivity": {"level": "high", "topics": ["health", "family"]},
    "off_screen": ["investigation work"],
    "length_s": 150,
    "why_it_lands": "A mistake, a turn, and a callback.",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (h.ENV_WEBHOOK, h.ENV_URL, h.ENV_KEY, h.ENV_KEY_HEADER, h.ENV_MODEL):
        monkeypatch.delenv(k, raising=False)


class FakePost:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body, timeout))
        return self.reply


def test_request_carries_the_rules():
    text = h.pitch_request(3, theme="the voice", since="2026-09-01", avoid=["Old story"])
    assert "pick the 3 best true stories" in text and "about the voice, from 2026-09-01 on" in text
    assert "No receipts, no pitch" in text and "Old story" in text and "shows your hand" in text
    assert '"pitches"' in text and '"receipts"' in text


def test_auth_headers():
    assert h.auth_headers("k") == {"Authorization": "Bearer k"}
    assert h.auth_headers("k", "X-API-Key") == {"X-API-Key": "k"}
    assert h.auth_headers("") == {}  # nothing to send: a proxy may inject it


def test_webhook_request_and_n8n_wrapped_reply(monkeypatch):
    monkeypatch.setenv(h.ENV_KEY, "secret")
    bad = dict(GOOD, title="No receipts here", receipts=[])
    reply = [{"output": "Here you go:\n```json\n" + json.dumps({"pitches": [GOOD, bad]}) + "\n```"}]
    post = FakePost(reply)
    kept, dropped = h.mine_pitches(n=2, theme="t", webhook="https://n8n.example/webhook/harriet", post=post)
    assert [p["title"] for p in kept] == [GOOD["title"]]
    assert len(dropped) == 1 and "No receipts here" in dropped[0] and "no receipts" in dropped[0]
    url, headers, body, timeout = post.calls[0]
    assert url.endswith("/webhook/harriet") and headers["Authorization"] == "Bearer secret" and timeout == h.TIMEOUT
    assert body["n"] == 2 and body["theme"] == "t" and "No receipts, no pitch" in body["prompt"]


@pytest.mark.parametrize("reply", [
    {"pitches": [GOOD]},
    [GOOD],
    {"output": json.dumps({"pitches": [GOOD]})},
    {"json": {"output": {"pitches": [GOOD]}}},
    "noise before " + json.dumps({"pitches": [GOOD]}) + " noise after",
])
def test_pitches_found_in_any_reply_shape(reply):
    assert h.pitches_from_response(reply)[0]["title"] == GOOD["title"]


def test_reply_without_pitches_is_an_error():
    with pytest.raises(LLMError):
        h.pitches_from_response({"status": "ok"})


def test_validation():
    assert h.validate_pitch(GOOD) == []
    assert "no receipts" in h.validate_pitch(dict(GOOD, receipts=[]))
    assert any("sensitivity" in p for p in h.validate_pitch(dict(GOOD, sensitivity={"level": "spicy"})))
    assert any("bad receipt" in p for p in h.validate_pitch(dict(GOOD, receipts=[{"kind": "rumour", "excerpt": "x"}])))
    assert any("70" in p for p in h.validate_pitch(dict(GOOD, title="x" * 71)))


def test_chat_fallback_without_a_key_sends_no_authorization(monkeypatch):
    seen = []

    def transport(url, headers, body, timeout):
        seen.append((url, headers, body))
        return {"choices": [{"message": {"content": json.dumps({"pitches": [GOOD]})}}]}

    client = h.resolve_chat("https://harriet.example/v1", transport=transport)
    kept, dropped = h.mine_pitches(client=client)
    assert kept and not dropped
    url, headers, body = seen[0]
    assert url == "https://harriet.example/v1/chat/completions" and "Authorization" not in headers
    assert body["model"] == "harriet"


def test_nothing_configured_says_what_to_set():
    with pytest.raises(LLMError, match="HARRIET_STORIES_URL"):
        h.mine_pitches()


def test_inbox_files_never_overwrite_and_feed_the_avoid_list(tmp_path):
    first = h.write_inbox([GOOD], tmp_path, pitched_at="2026-09-28")[0]
    second = h.write_inbox([GOOD], tmp_path, pitched_at="2026-09-28")[0]
    assert first.name == "2026-09-28-the-rule-i-wrote-at-3-17-am.md" and second.name.endswith("-2.md")
    text = first.read_text()
    assert "**Hook:** Three nights ago" in text and 'voice note · 03:16 — "Was that pun intended' in text
    status = h.read_status(first)
    assert status["status"] == "pitched" and status["sensitivity"] == "high" and status["topics"] == ["health", "family"]
    assert h.told_titles(tmp_path) == [GOOD["title"], GOOD["title"]]


def test_cli_pitch_and_inbox(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(h.ENV_WEBHOOK, "https://n8n.example/webhook/harriet")
    monkeypatch.setattr(h, "_post_json", FakePost({"pitches": [GOOD]}))
    assert main(["harriet", "pitch", "--dir", str(tmp_path)]) == 0
    assert "wrote" in capsys.readouterr().out
    assert main(["harriet", "inbox", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "pitched" in out and GOOD["title"] in out and "1 pitch(es)" in out
