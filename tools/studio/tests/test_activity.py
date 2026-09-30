import json
import subprocess
from pathlib import Path

from noirstudio.activity import collect, commits, renders


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin"})


def test_commits_and_renders_are_collected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("one\ntwo\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "Add a.txt")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "commit", "-q", "-am", "Trim a.txt")

    cs = commits(repo, since="1.day")
    assert [c["subject"] for c in cs] == ["Trim a.txt", "Add a.txt"]
    assert cs[1]["insertions"] == 2 and cs[0]["deletions"] == 1

    rdir = tmp_path / "renders" / "x"
    rdir.mkdir(parents=True)
    (rdir / "x.report.json").write_text(json.dumps({
        "spec_id": "x", "brand": "noirsys", "live": False, "duration_seconds": 12.5, "words": 30,
        "scenes": [{"id": "s01"}, {"id": "s02", "fallback": "video engine offline"}], "generated_at": "2026-09-28T00:00:00+00:00",
    }))
    rs = renders(tmp_path / "renders")
    assert rs[0]["spec_id"] == "x" and rs[0]["scenes"] == 2 and rs[0]["fallbacks"] == ["s02"]

    record = collect([repo, tmp_path / "not-a-repo"], since="1.day", render_roots=[tmp_path / "renders"])
    assert record["repos"][0]["totals"]["commits"] == 2
    assert "error" in record["repos"][1]
    assert len(record["renders"]) == 1


def _repo_with_work_waiting_on_a_branch(tmp_path: Path) -> Path:
    """One commit on the default branch, two more on a branch that has not been merged (a pull request)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "On the default branch")
    _git(repo, "checkout", "-q", "-b", "side")
    for name in ("b", "c"):
        (repo / f"{name}.txt").write_text("x\n")
        _git(repo, "add", f"{name}.txt")
        _git(repo, "commit", "-q", "-m", f"Waiting in a pull request: {name}")
    _git(repo, "checkout", "-q", "-")
    return repo


def test_work_waiting_on_another_branch_still_counts(tmp_path):
    """Agent Log 003 said "zero commits today" while 37 sat in an open pull request, because only HEAD was read."""
    repo = _repo_with_work_waiting_on_a_branch(tmp_path)
    assert [c["subject"] for c in commits(repo, since="1.day", all_branches=False)] == ["On the default branch"]
    everything = commits(repo, since="1.day")
    assert {c["subject"] for c in everything} == {"On the default branch", "Waiting in a pull request: b",
                                                  "Waiting in a pull request: c"}  # (commits made in one second have no order)
    totals = collect([repo], since="1.day")["repos"][0]["totals"]
    assert totals["commits"] == 3 and totals["truncated"] is False
    assert collect([repo], since="1.day", all_branches=False)["repos"][0]["totals"]["commits"] == 1


def test_a_count_that_stopped_at_the_limit_says_so(tmp_path):
    repo = _repo_with_work_waiting_on_a_branch(tmp_path)
    totals = collect([repo], since="1.day", limit=2)["repos"][0]["totals"]
    assert totals["commits"] == 2 and totals["truncated"] is True  # a floor, not the number


def test_the_loops_own_commits_are_left_out_of_every_branch(tmp_path):
    repo = _repo_with_work_waiting_on_a_branch(tmp_path)
    got = collect([repo], since="1.day", exclude_authors=["t"])["repos"][0]["totals"]
    assert got["commits"] == 0  # every commit in this repo is by "t"


def test_cli_activity_head_only(tmp_path, capsys):
    from noirstudio.cli import main

    repo = _repo_with_work_waiting_on_a_branch(tmp_path)
    assert main(["activity", "--repo", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)["repos"][0]["totals"]["commits"] == 3
    assert main(["activity", "--repo", str(repo), "--head-only"]) == 0
    assert json.loads(capsys.readouterr().out)["repos"][0]["totals"]["commits"] == 1
