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
