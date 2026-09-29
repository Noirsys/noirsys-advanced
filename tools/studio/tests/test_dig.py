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
         "his_words": "yes: a voice note, transcribed", "ref": "vn-001"},
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


def test_the_request_tells_her_a_row_under_his_role_is_not_always_him():
    text = d.dig_request(5)
    assert "not always him" in text and "compaction handoff" in text and "api-*" in text and '"his_words"' in text
    assert "nai-creative" in text and "not with you" in text and "never write it as something you did" in text


def test_moment_problems_flag_authorship_that_is_not_his_or_not_checked():
    line = dict(MOMENT["exchange"][0])
    no = dict(MOMENT, exchange=[dict(line, his_words="no: a compaction handoff"), MOMENT["exchange"][1]])
    unsure = dict(MOMENT, exchange=[dict(line, his_words="unsure"), MOMENT["exchange"][1]])
    unchecked = dict(MOMENT, exchange=[{k: v for k, v in line.items() if k != "his_words"}, MOMENT["exchange"][1]])
    assert "1 of his lines are NOT his words" in d.moment_problems(no)
    assert "1 of his lines: authorship unsure" in d.moment_problems(unsure)
    assert "1 of his lines: authorship not checked" in d.moment_problems(unchecked)
    assert d.moment_problems(dict(MOMENT, exchange=[dict(line, his_words=True), MOMENT["exchange"][1]])) == \
        ["1 of 2 lines recalled, not copied"]
    md = d.dig_markdown({"moments": [no]}, {"id": "j"})
    assert "his words? no: a compaction handoff" in md and "**Check:**" in md and "NOT his words" in md


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


def test_a_job_that_ran_past_her_limit_is_told_to_go_out_in_pieces(tmp_path):
    h.log_job(tmp_path, id="big", poll_url=f"{URL}/jobs?id=big", what="note", status="running")
    gateway = {"status": "failed", "status_code": 502,
               "result": {"error": {"message": "timeout of 1800000ms exceeded", "type": "upstream_error"}}}
    (done,) = d.collect(tmp_path, request=FakeN8N((200, gateway)))
    assert done["status"] == "failed" and "smaller pieces" in done["error"]
    assert "smaller pieces" in h.read_jobs(tmp_path)[0]["error"]
    assert not h.job_timed_out("Harriet job x failed: HTTP 500: boom") and not h.job_timed_out(None)


NO_CREDIT = ("Billing or credits exhausted: HTTP 402: Insufficient Balance (request_id: x)\n\nDeepSeek reported that billing, "
             "credits, or account entitlement is exhausted for deepseek-flash.\nAdd credits or update billing with that provider.")


def test_the_providers_402_is_told_apart_from_her_own_answer():
    assert h.out_of_credit(NO_CREDIT) and h.out_of_credit("  Insufficient Balance ")
    assert not h.out_of_credit("ready") and not h.out_of_credit(None)
    story = "The gateway kept answering HTTP 402: Insufficient Balance for forty-seven days. " * 30
    assert not h.out_of_credit(story)  # her own long story about it is an answer, not the notice


def test_a_402_blocks_the_job_keeps_nothing_and_retry_sends_the_same_prompt_again(tmp_path):
    fake = FakeN8N((202, {"id": "j1", "poll_url": f"{URL}/jobs?id=j1"}),
                   (200, {"status": "completed", "result": {"choices": [{"message": {"content": NO_CREDIT}}]}}),
                   (202, {"id": "j2", "poll_url": f"{URL}/jobs?id=j2"}))
    d.start(tmp_path, "note", "Harriet, please check the row.", request=fake, note="Harriet, please check the row.")
    (done,) = d.collect(tmp_path, request=fake)
    assert done["status"] == "blocked" and "top" in done["error"].lower() and "retry" in done["error"]
    assert h.read_jobs(tmp_path)[0]["status"] == "blocked"
    assert not (tmp_path / "notes").exists() and not (tmp_path / "digs").exists()  # nothing kept
    (again,) = d.retry(tmp_path, request=fake)
    assert again["id"] == "j2" and again["was"] == "j1"
    assert fake.calls[2][3]["messages"][0]["content"] == "Harriet, please check the row."
    jobs = {j["id"]: j for j in h.read_jobs(tmp_path)}
    assert jobs["j1"]["status"] == "retried" and jobs["j1"]["retried_as"] == "j2"
    assert jobs["j2"]["status"] == "running" and jobs["j2"]["note"] == "Harriet, please check the row."
    assert d.retry(tmp_path, request=FakeN8N()) == []  # nothing left blocked


def test_ping_says_ready_or_out_of_credit_and_logs_nothing(tmp_path):
    def reply(text):
        return (200, {"status": "completed", "result": {"choices": [{"message": {"content": text}}]}})

    no_sleep = lambda _s: None  # noqa: E731
    assert d.ping(request=FakeN8N((202, {"id": "p"}), reply("ready")), sleep=no_sleep) == "ready"
    assert d.ping(request=FakeN8N((202, {"id": "p"}), reply(NO_CREDIT)), sleep=no_sleep) == "out of credit"
    running = (200, {"status": "running"})
    assert d.ping(request=FakeN8N((202, {"id": "p"}), running, running), sleep=no_sleep, wait_s=10, poll_s=5) == "no answer"
    assert h.read_jobs(tmp_path) == []


def test_cli_collect_says_blocked_and_ping_exits_3_when_out_of_credit(tmp_path, monkeypatch, capsys):
    root = ["--root", str(tmp_path)]
    fake = FakeN8N((202, {"id": "n1"}),
                   (200, {"status": "completed", "result": {"choices": [{"message": {"content": NO_CREDIT}}]}}),
                   (202, {"id": "p1"}),
                   (200, {"status": "completed", "result": {"choices": [{"message": {"content": NO_CREDIT}}]}}))
    monkeypatch.setattr(h, "_request", fake)
    monkeypatch.setattr(h.time, "sleep", lambda _s: None)
    assert main(["harriet", "tell", "--note", "hello", *root]) == 0
    capsys.readouterr()
    assert main(["harriet", "collect", *root]) == 0
    out = capsys.readouterr().out
    assert "n1 (note): blocked" in out and "BLOCKED:" in out and "top-up" not in out
    assert main(["harriet", "ping"]) == 3
    assert "OUT OF CREDIT" in capsys.readouterr().out


def test_a_transient_poll_error_leaves_the_job_running_for_the_next_collect(tmp_path):
    h.log_job(tmp_path, id="j", poll_url=f"{URL}/jobs?id=j", what="dig", status="running", started_at="2026-09-29T01")
    assert d.collect(tmp_path, request=FakeN8N((502, "Bad gateway"))) == []
    assert h.read_jobs(tmp_path)[0]["status"] == "running"
    (done,) = d.collect(tmp_path, request=FakeN8N((200, {"status": "completed", "result": completion({"moments": [MOMENT]})})))
    assert done["status"] == "collected"


def test_a_402_through_the_jobs_own_status_blocks_it_too(tmp_path):
    h.log_job(tmp_path, id="j", poll_url=f"{URL}/jobs?id=j", what="note", status="running", prompt="hi", note="hi")
    (done,) = d.collect(tmp_path, request=FakeN8N(
        (200, {"status": "completed", "status_code": 402, "result": {"error": "Insufficient Balance"}})))
    assert done["status"] == "blocked" and h.read_jobs(tmp_path)[0]["status"] == "blocked"


def test_wait_for_sees_a_job_that_another_collect_picked_up_first(tmp_path):
    h.log_job(tmp_path, id="j", poll_url=f"{URL}/jobs?id=j", what="dig", status="running", started_at="2026-09-29T01")
    h.log_job(tmp_path, id="j", status="collected", saved=[str(tmp_path / "digs" / "x.md")])  # the heartbeat got there first
    done = d.wait_for(tmp_path, "j", request=FakeN8N(), sleep=lambda _s: None, wait_s=30, poll_s=15)
    assert done["status"] == "collected" and done["saved"] == [tmp_path / "digs" / "x.md"]


def test_a_reply_that_cannot_be_filed_is_kept_raw_and_does_not_stall_the_jobs_behind_it(tmp_path, monkeypatch):
    for jid in ("a", "b"):
        h.log_job(tmp_path, id=jid, poll_url=f"{URL}/jobs?id={jid}", what="dig", status="running", started_at="2026-09-29T01")
    real = d.save_reply
    monkeypatch.setattr(d, "save_reply", lambda root, job, reply: (_ for _ in ()).throw(TypeError("odd topics"))
                        if job["id"] == "a" else real(root, job, reply))
    ok = (200, {"status": "completed", "result": completion({"moments": [MOMENT]})})
    changed = d.collect(tmp_path, request=FakeN8N(ok, ok))
    assert [j["status"] for j in changed] == ["failed", "collected"]
    assert "could not file" in changed[0]["error"]
    raw = next((tmp_path / "raw").glob("*-a.txt"))
    assert "first-voice-note" in raw.read_text(encoding="utf-8")
    assert {j["id"]: j["status"] for j in h.read_jobs(tmp_path)} == {"a": "failed", "b": "collected"}


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


def test_tell_sends_a_note_and_keeps_her_answer(tmp_path, monkeypatch, capsys):
    fake = FakeN8N((202, {"id": "n1"}), (200, {"status": "completed", "result": {
        "choices": [{"message": {"content": "Copied all 18 files. Nothing deleted."}}]}}))
    monkeypatch.setattr(h, "_request", fake)
    assert main(["harriet", "tell", "--root", str(tmp_path)]) == 1
    assert main(["harriet", "tell", "--note", "Please keep his voice notes.", "--root", str(tmp_path)]) == 0
    assert fake.calls[0][3]["messages"][0]["content"] == "Please keep his voice notes."
    assert main(["harriet", "collect", "--root", str(tmp_path)]) == 0
    (note,) = (tmp_path / "notes").glob("*.md")
    text = note.read_text()
    assert "Please keep his voice notes." in text and "# Harriet\n\nCopied all 18 files." in text
