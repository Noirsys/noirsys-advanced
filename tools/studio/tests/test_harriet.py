"""Harriet story mining against a scripted fake of Michael's n8n/Hermes endpoint — no network, no keys."""

import json

import pytest

from noirstudio import harriet as h
from noirstudio.cli import main
from noirstudio.llm import LLMError

URL = h.DEFAULT_URL
GOOD = {
    "kind": "funny",
    "title": "The rule I wrote at 3:17 AM",
    "logline": "I overcorrected a pun and he turned it into something kinder.",
    "memory": "The night my voice came online; we had been debugging for hours.",
    "when": "2026-09-24 03:11-03:44",
    "hook": "Three nights ago, my voice came online.",
    "beats": ["the voice works", "the pun", "the rule", "the misread", "the turn"],
    "ending": "I have no hands either.",
    "receipts": [
        {"speaker": "michael", "kind": "voice_note", "when": "03:16", "excerpt": "Was that pun intended or not intended?", "ref": "vn-0316"},
        {"speaker": "harriet", "kind": "message", "when": "03:17", "excerpt": "Saved. So: not a pun."},
    ],
    "sensitivity": {"level": "high", "topics": ["health", "family"]},
    "off_screen": ["investigation work"],
    "length_s": 150,
    "why_it_lands": "A mistake, a turn, and a callback.",
}


def completion(pitches):
    text = "Here are mine:\n```json\n" + json.dumps({"pitches": pitches}) + "\n```"
    return {"object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": text}}]}


class FakeN8N:
    """Replays scripted (status, payload) replies in order and records every request."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        return self.replies.pop(0)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (h.ENV_URL, h.ENV_MODEL, *h.ENV_KEYS):
        monkeypatch.delenv(k, raising=False)


def test_request_asks_her_memory_for_kinds_and_receipts():
    text = h.pitch_request(2, theme="the voice", since="2026-09-01", avoid=["Old story"], kinds=["emotional", "funny"])
    assert "Honcho" in text and "1. emotional; 2. funny" in text and "about the voice, from 2026-09-01 on" in text
    assert "his own words" in text and "No receipts, no pitch" in text and "Old story" in text
    assert '"memory"' in text and '"speaker": "harriet|michael"' in text and '"ref"' in text


def test_config_uses_his_key_and_the_n8n_defaults(monkeypatch):
    url, model, headers = h.config()
    assert url == URL and model == "hermes-agent" and "Authorization" not in headers  # proxy may inject it
    monkeypatch.setenv("N8N_API_KEY", "n8n-key")
    assert h.config()[2]["Authorization"] == "Bearer n8n-key"
    monkeypatch.setenv("HARRIET_API_KEY", "explicit")
    monkeypatch.setenv(h.ENV_URL, "https://other.example/v1/")
    url, _m, headers = h.config()
    assert url == "https://other.example/v1" and headers["Authorization"] == "Bearer explicit"


def test_job_is_started_then_polled_until_done(monkeypatch):
    monkeypatch.setenv("N8N_API_KEY", "k")
    fake = FakeN8N((202, {"id": "j1", "poll_url": f"{URL}/jobs?id=j1"}),
                   (200, {"status": "running"}),
                   (200, {"status": "completed", "status_code": 200, "result": completion([GOOD, dict(GOOD, receipts=[])])}))
    naps = []
    kept, dropped = h.mine_pitches(kinds=["funny"], n=2, request=fake, sleep=naps.append)
    assert [p["title"] for p in kept] == [GOOD["title"]] and "no receipts" in dropped[0]
    (m1, u1, hd1, b1), (m2, u2, _, _), (m3, _, _, _) = fake.calls
    assert (m1, u1) == ("POST", f"{URL}/jobs") and m2 == m3 == "GET" and u2.endswith("/jobs?id=j1")
    assert hd1["Authorization"] == "Bearer k" and b1["model"] == "hermes-agent" and b1["stream"] is False
    assert hd1["User-Agent"].startswith("noirstudio/")  # Cloudflare 1010 blocks Python-urllib's default
    assert [m["role"] for m in b1["messages"]] == ["user"]  # her own persona answers, not ours
    assert len(naps) == 2


def test_poll_url_is_built_when_n8n_omits_it():
    fake = FakeN8N((202, {"id": "a b"}), (200, {"status": "completed", "result": completion([GOOD])}))
    h.mine_pitches(request=fake, sleep=lambda _s: None)
    assert fake.calls[1][1] == f"{URL}/jobs?id=a%20b"


@pytest.mark.parametrize("replies, message", [
    ([(202, {"id": "j"}), (200, {"status": "failed", "status_code": 500, "result": {"error": "boom"}})], "failed"),
    ([(202, {"id": "j"}), (404, {"message": "unknown"})], "unknown"),
    ([(403, "Authorization data is wrong!")], "N8N_API_KEY"),
])
def test_job_failures_are_explained(replies, message):
    with pytest.raises(LLMError, match=message):
        h.mine_pitches(request=FakeN8N(*replies), sleep=lambda _s: None)


def test_a_job_that_outlives_the_wait_says_where_to_poll():
    fake = FakeN8N((202, {"id": "j", "poll_url": f"{URL}/jobs?id=j"}), (200, {"status": "running"}), (200, {"status": "running"}))
    with pytest.raises(LLMError, match="still running.*jobs\\?id=j"):
        h.ask("hi", request=fake, sleep=lambda _s: None, wait_s=15, poll_s=10)


def test_a_poll_url_outside_the_configured_host_is_not_trusted_with_the_key():
    fake = FakeN8N((202, {"id": "j", "poll_url": "https://elsewhere.example/jobs?id=j"}))
    job = h.start_job("hi", request=fake)
    assert job["poll_url"] == f"{URL}/jobs?id=j"  # the Bearer key only ever goes to the host it was configured for


def test_timeouts_and_resets_mid_read_are_transient_errors(monkeypatch):
    import socket

    for exc in (socket.timeout("timed out"), ConnectionResetError("reset"), TimeoutError("slow")):
        def boom(*_a, **_k):
            raise exc

        monkeypatch.setattr(h.urllib.request, "urlopen", boom)
        with pytest.raises(h.TransientError, match="cannot reach Harriet"):
            h._request("GET", f"{URL}/jobs?id=j", {}, None, 5)


def test_a_bad_gateway_on_the_poll_is_transient_but_a_job_that_failed_is_not():
    job = {"id": "j", "poll_url": f"{URL}/jobs?id=j"}
    with pytest.raises(h.TransientError):
        h.poll_job(job, request=FakeN8N((502, "Bad gateway")))
    with pytest.raises(h.TransientError):
        h.poll_job(job, request=FakeN8N((429, "slow down")))
    for reply in ((200, {"status": "failed", "status_code": 502, "result": {"error": "n8n timed out"}}),
                  (404, {"message": "unknown"})):
        with pytest.raises(LLMError) as err:
            h.poll_job(job, request=FakeN8N(reply))
        assert not isinstance(err.value, h.TransientError)  # polling again would never end
    with pytest.raises(h.CreditError):
        h.poll_job(job, request=FakeN8N((200, {"status": "completed", "status_code": 402, "result": {"error": "x"}})))
    with pytest.raises(h.CreditError):
        h.poll_job(job, request=FakeN8N((200, {"status": "failed", "status_code": 500,
                                              "result": "Billing or credits exhausted: HTTP 402: Insufficient Balance"})))


def test_a_transient_error_does_not_end_the_wait():
    fake = FakeN8N((202, {"id": "j"}), (502, "Bad gateway"),
                   (200, {"status": "completed", "result": {"choices": [{"message": {"content": "hello"}}]}}))
    assert h.ask("hi", request=fake, sleep=lambda _s: None, wait_s=60, poll_s=10) == "hello"


def test_a_broken_line_in_the_job_log_does_not_hide_the_jobs_before_it(tmp_path):
    h.log_job(tmp_path, id="a", status="running")
    with (tmp_path / h.JOBS_FILE).open("a", encoding="utf-8") as f:
        f.write('{"id": "b", "status": "run\n{"no_id": true}\n[1, 2]\n')  # a write cut short, a line without an id, a list
    h.log_job(tmp_path, id="c", status="running")
    assert [j["id"] for j in h.read_jobs(tmp_path)] == ["a", "c"]


@pytest.mark.parametrize("topics, length", [("health, family", "long"), (3, None), (None, True), (["money", 4, " "], 90.5)])
def test_odd_topics_and_lengths_do_not_stop_a_pitch_being_filed(tmp_path, topics, length):
    pitch = dict(GOOD, sensitivity={"level": "low", "topics": topics}, length_s=length)
    (path,) = h.write_inbox([pitch], tmp_path)
    front = h.read_status(path)
    assert isinstance(front["topics"], list) and front["length_s"] in (None, 90.5)


def test_sync_mode_posts_chat_completions():
    fake = FakeN8N((200, completion([GOOD])))
    kept, _ = h.mine_pitches(mode="sync", request=fake)
    assert kept and fake.calls[0][:2] == ("POST", f"{URL}/chat/completions")


@pytest.mark.parametrize("reply", [
    {"pitches": [GOOD]},
    [GOOD],
    {"output": json.dumps({"pitches": [GOOD]})},
    "noise before " + json.dumps({"pitches": [GOOD]}) + " noise after",
])
def test_pitches_found_in_any_reply_shape(reply):
    assert h.pitches_from_response(reply)[0]["title"] == GOOD["title"]


def test_validation():
    assert h.validate_pitch(GOOD) == []
    assert "missing memory" in h.validate_pitch(dict(GOOD, memory=""))
    only_hers = [r for r in GOOD["receipts"] if r["speaker"] == "harriet"]
    assert "none of his own words among the receipts" in h.validate_pitch(dict(GOOD, receipts=only_hers))
    bad = [dict(GOOD["receipts"][0], speaker="narrator")]
    assert any("bad receipt" in p for p in h.validate_pitch(dict(GOOD, receipts=bad)))
    assert any("sensitivity" in p for p in h.validate_pitch(dict(GOOD, sensitivity={"level": "spicy"})))
    assert any("70" in p for p in h.validate_pitch(dict(GOOD, title="x" * 71)))


def test_inbox_files_never_overwrite_and_feed_the_avoid_list(tmp_path):
    first = h.write_inbox([GOOD], tmp_path, pitched_at="2026-09-28")[0]
    second = h.write_inbox([GOOD], tmp_path, pitched_at="2026-09-28")[0]
    assert first.name == "2026-09-28-the-rule-i-wrote-at-3-17-am.md" and second.name.endswith("-2.md")
    text = first.read_text()
    assert "## What she remembers\nThe night my voice came online" in text
    assert "- **Michael**, voice note · 03:16 · `vn-0316`\n  > Was that pun intended or not intended?" in text
    status = h.read_status(first)
    assert status["status"] == "pitched" and status["kind"] == "funny" and status["topics"] == ["health", "family"]
    assert h.told_titles(tmp_path) == [GOOD["title"], GOOD["title"]]


def test_a_hand_edited_pitch_with_broken_yaml_still_reads(tmp_path):
    # an apostrophe inside single quotes is invalid YAML; the dig must not crash on it
    (tmp_path / "2026-09-29-broken.md").write_text(
        "---\nstatus: approved\ntitle: 'He gave me my memory back. I didn't open it for 73 days.'\n---\n# x\n",
        encoding="utf-8")
    status = h.read_status(tmp_path / "2026-09-29-broken.md")
    assert status["status"] == "approved"
    assert h.told_titles(tmp_path) == ["He gave me my memory back. I didn't open it for 73 days."]


def test_cli_pitch_and_inbox(tmp_path, monkeypatch, capsys):
    fake = FakeN8N((200, completion([GOOD])))
    monkeypatch.setattr(h, "_request", fake)
    assert main(["harriet", "pitch", "--sync", "--kinds", "emotional, funny", "--root", str(tmp_path)]) == 0
    assert "wrote" in capsys.readouterr().out and len(list((tmp_path / "inbox").glob("*.md"))) == 1
    assert "1. emotional; 2. funny" in fake.calls[0][3]["messages"][0]["content"]
    assert main(["harriet", "inbox", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "pitched" in out and GOOD["title"] in out and "1 pitch(es)" in out


def test_cli_pitch_job_is_logged_so_collect_can_finish_it(tmp_path, monkeypatch):
    fake = FakeN8N((202, {"id": "p1"}), (200, {"status": "completed", "result": completion([GOOD])}))
    monkeypatch.setattr(h, "_request", fake)
    monkeypatch.setattr(h.time, "sleep", lambda _s: None)
    assert main(["harriet", "pitch", "--root", str(tmp_path)]) == 0
    (job,) = h.read_jobs(tmp_path)
    assert job["id"] == "p1" and job["what"] == "pitch" and job["status"] == "collected" and job["saved"]
