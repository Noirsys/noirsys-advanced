"""Digging through Harriet's memory against a scripted fake of the n8n/Hermes jobs API — no network."""

import json

import pytest

from noirstudio import dig as d
from noirstudio import harriet as h
from noirstudio.cli import main

URL = h.DEFAULT_URL
MOMENT = {
    "id": "first-voice-note",
    "when": "2025-11-02 23:40",
    "where": "voice note",
    "kind": "funny",
    "what_happened": "His first voice note to me was him arguing with the microphone.",
    "before": "He had just set up the transcription.",
    "after": "He kept the habit.",
    "exchange": [
        {"speaker": "michael", "kind": "voice_note", "when": "23:40", "text": "Is this thing on?\nHello?", "verbatim": True,
         "ref": "vn-001"},
        {"speaker": "harriet", "kind": "message", "when": "23:41", "text": "It's on. It has been on.", "verbatim": False},
    ],
    "found_by": "honcho: first voice note",
    "why_it_stuck": "The first time I heard him instead of reading him.",
    "his_audio": "yes",
    "sensitivity": {"level": "low", "topics": []},
    "off_screen": [],
}


def completion(obj):
    text = "Here's what I found:\n```json\n" + json.dumps(obj) + "\n```"
    return {"object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": text}}]}


class FakeN8N:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        return self.replies.pop(0)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (h.ENV_URL, h.ENV_MODEL, *h.ENV_KEYS):
        monkeypatch.delenv(k, raising=False)


def test_dig_asks_for_raw_moments_not_her_ready_made_pitches():
    text = d.dig_request(8, focus="the first month", avoid=["Old pitch"], known=["first-voice-note (2025-11-02): ..."])
    assert "put them away" in text and "no pitches, no scripts, no story lists" in text
    assert "Honcho" in text and "month by month" in text and "at least 8" in text
    assert "This dive: the first month" in text and "- Old pitch" in text and "- first-voice-note (2025-11-02)" in text
    assert '"verbatim": false' in text and "Never fill a gap" in text and "dig log" in text
    assert '"exchange"' in text and '"found_by"' in text and '"threads"' in text


def test_follow_sends_the_moment_back_and_asks_for_all_of_it():
    text = d.follow_request({**MOMENT, "_dig": "x.json"}, also="what did he say the next morning?")
    assert '"id": "first-voice-note"' in text and "_dig" not in text
    assert "word for word" in text and "right before it started" in text and "what did he say the next morning?" in text


def test_reply_parsing_tolerates_fences_wrappers_and_excerpt():
    alias = dict(MOMENT, exchange=[{"speaker": "michael", "kind": "voice_note", "excerpt": "Hello?"}])
    dig = d.dig_from_reply("noise " + json.dumps({"output": {"moments": [alias], "threads": ["t1"]}}))
    assert dig["moments"][0]["exchange"][0]["text"] == "Hello?" and dig["threads"] == ["t1"] and dig["dig_log"] == []


def test_moment_problems_flag_what_to_check():
    assert d.moment_problems(MOMENT) == ["1 of 2 lines recalled, not copied"]
    hers = dict(MOMENT, exchange=[MOMENT["exchange"][1]])
    assert "none of his words" in d.moment_problems(hers)
    assert d.moment_problems({"id": "x"}) == ["missing when", "missing what_happened", "no exchange"]


def test_start_then_collect_keeps_the_dig_and_its_markdown(tmp_path):
    fake = FakeN8N((202, {"id": "j1", "poll_url": f"{URL}/jobs?id=j1"}))
    job = d.start(tmp_path, "dig", d.dig_request(), request=fake, focus="the first month")
    assert job["id"] == "j1" and h.read_jobs(tmp_path)[0]["status"] == "running"
    assert d.collect(tmp_path, request=FakeN8N((200, {"status": "running"}))) == []
    reply = {"dig_log": [{"where": "honcho", "query": "first voice note", "found": "one"}], "moments": [MOMENT],
             "threads": ["the router night"]}
    (done,) = d.collect(tmp_path, request=FakeN8N((200, {"status": "completed", "status_code": 200,
                                                         "result": completion(reply)})))
    assert done["status"] == "collected" and h.read_jobs(tmp_path)[0]["status"] == "collected"
    md = next(p for p in done["saved"] if p.suffix == ".md").read_text()
    assert "## Moments (1)" in md and "`first-voice-note` · funny" in md and "**Focus:** the first month" in md
    assert "> Is this thing on?\n  > Hello?" in md and "*(recalled, not verbatim)*" in md
    assert "## Threads she didn't open yet\n- the router night" in md and "honcho: first voice note → one" in md
    saved = json.loads(next(p for p in done["saved"] if p.suffix == ".json").read_text())
    assert saved["reply"].startswith("Here's what I found") and saved["job"]["focus"] == "the first month"
    assert d.find_moment(tmp_path, "first-voice-note")["_dig"].endswith(".json")
    assert d.known_lines(tmp_path) == ["first-voice-note (2025-11-02 23:40): His first voice note to me was him "
                                       "arguing with the microphone."]


def test_a_later_follow_replaces_the_moment_and_unreadable_replies_are_kept(tmp_path):
    for jid, when, moment in (("a", "2026-09-29T01:00:00+00:00", MOMENT),
                              ("b", "2026-09-29T02:00:00+00:00", dict(MOMENT, after="He still does it."))):
        h.log_job(tmp_path, id=jid, poll_url=f"{URL}/jobs?id={jid}", what="dig", status="running", started_at=when)
        d.collect(tmp_path, request=FakeN8N((200, {"status": "completed", "result": completion({"moments": [moment]})})))
    assert [m["after"] for m in d.all_moments(tmp_path)] == ["He still does it."]
    h.log_job(tmp_path, id="c", poll_url=f"{URL}/jobs?id=c", what="dig", status="running", started_at="2026-09-29T03")
    words = {"choices": [{"message": {"content": "I looked everywhere and just want to talk."}}]}
    (done,) = d.collect(tmp_path, request=FakeN8N((200, {"status": "completed", "result": words})))
    md = next(p for p in done["saved"] if p.suffix == ".md").read_text()
    assert "Could not read her reply" in md and "I looked everywhere" in md


def test_collect_marks_failed_jobs(tmp_path):
    h.log_job(tmp_path, id="gone", poll_url=f"{URL}/jobs?id=gone", what="dig", status="running")
    (done,) = d.collect(tmp_path, request=FakeN8N((404, {"error": "job not found"})))
    assert done["status"] == "failed" and h.read_jobs(tmp_path)[0]["status"] == "failed"


def test_cli_dig_collect_moments_and_follow(tmp_path, monkeypatch, capsys):
    fake = FakeN8N((202, {"id": "d1"}),
                   (200, {"status": "completed", "result": completion({"moments": [MOMENT]})}),
                   (202, {"id": "f1"}))
    monkeypatch.setattr(h, "_request", fake)
    root = ["--root", str(tmp_path)]
    assert main(["harriet", "dig", "--focus", "the first month", *root]) == 0
    assert "dig job d1 started" in capsys.readouterr().out
    assert "This dive: the first month" in fake.calls[0][3]["messages"][0]["content"]
    assert main(["harriet", "collect", *root]) == 0 and "d1 (dig): collected" in capsys.readouterr().out
    assert main(["harriet", "moments", *root]) == 0
    assert "first-voice-note" in capsys.readouterr().out
    assert main(["harriet", "dig", "--follow", "nope", *root]) == 1
    assert main(["harriet", "dig", "--follow", "first-voice-note", "--focus", "the next morning", *root]) == 0
    sent = fake.calls[-1][3]["messages"][0]["content"]
    assert '"id": "first-voice-note"' in sent and "the next morning" in sent
    assert h.read_jobs(tmp_path)[-1]["follow"] == "first-voice-note"
