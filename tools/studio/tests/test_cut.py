"""Platform cuts on a synthetic master: tone bursts with real pauses between them."""

import json
from pathlib import Path

import pytest

from noirstudio import ffmpeg
from noirstudio.cli import main
from noirstudio.cut import CutError, load_plan, plan_problems, probe, run_plan, seam_warnings, silences

PLAN = """id: test-ep
master: master.mp4
outputs:
  - name: short
    cap_s: 5
    segments:
      - [0.00, 1.60]   # first burst, ends in the pause
      - [2.60, 4.40]   # second burst, from pause to pause
"""


@pytest.fixture(scope="module")
def master(tmp_path_factory) -> Path:
    """6 s, 540x960, 30 fps; a 440 Hz tone at 0-1.5 s and 2.7-4.3 s, silence elsewhere."""
    path = tmp_path_factory.mktemp("cut") / "master.mp4"
    tone = "if(between(t,0,1.5)+between(t,2.7,4.3),0.25*sin(2*PI*440*t),0)"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", "testsrc2=s=540x960:r=30:d=6",
                "-f", "lavfi", "-i", f"aevalsrc='{tone}':s=48000:d=6",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)])
    return path


def _plan(tmp_path: Path, text: str = PLAN) -> Path:
    p = tmp_path / "ep.cuts.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_probe_and_pauses(master):
    info = probe(master)
    assert 5.9 < info["duration"] < 6.1 and (info["width"], info["height"]) == (540, 960)
    pauses = silences(master)
    assert any(a < 2.0 and b > 2.5 for a, b in pauses), pauses  # the gap between the bursts


def test_plan_problems(tmp_path):
    plan = load_plan(_plan(tmp_path))
    assert plan_problems(plan, master_duration=6.0) == []
    plan.outputs[0].cap_s = 3
    assert any("over its 3s cap" in p for p in plan_problems(plan, 6.0))
    plan.outputs[0].segments.append((5.5, 6.9))
    assert any("past the master's end" in p for p in plan_problems(plan, 6.0))
    plan.outputs[0].segments.append((2.0, 1.0))
    assert any("empty or reversed" in p for p in plan_problems(plan, 6.0))


def test_bad_plans_are_rejected(tmp_path):
    with pytest.raises(CutError, match="needs `id`"):
        load_plan(_plan(tmp_path, "outputs: []\n"))
    with pytest.raises(CutError, match="lowercase `name`"):
        load_plan(_plan(tmp_path, "id: x\noutputs:\n  - name: Short\n    segments: [[0, 1]]\n"))
    with pytest.raises(CutError, match=r"\[start, end\]"):
        load_plan(_plan(tmp_path, "id: x\noutputs:\n  - name: s\n    segments: [[0]]\n"))


def test_seams_mid_speech_are_flagged(master, tmp_path):
    plan = load_plan(_plan(tmp_path))
    pauses, dur = silences(master), probe(master)["duration"]
    assert seam_warnings(plan, pauses, dur) == []
    plan.outputs[0].segments[0] = (0.0, 1.0)  # cuts the first burst mid-tone
    warnings = seam_warnings(plan, pauses, dur)
    assert len(warnings) == 1 and "out-point 1.00s" in warnings[0]


def test_render_cut_to_length_and_loudness(master, tmp_path):
    plan = load_plan(_plan(tmp_path))
    report = run_plan(plan, master, tmp_path / "out", log=lambda _m: None)
    out = report["outputs"][0]
    assert out["seams"] == 1 and out["duration_s"] == 3.4
    rendered = probe(Path(out["path"]))
    assert abs(rendered["duration"] - 3.4) < 0.15 and (rendered["width"], rendered["height"]) == (540, 960)
    assert abs(out["loudness"]["lufs"] - (-14.0)) < 1.5 and out["loudness"]["true_peak_db"] <= -0.5
    assert json.loads((tmp_path / "out" / "test-ep.cuts.json").read_text())["outputs"][0]["name"] == "short"
    assert not list((tmp_path / "out").glob("*.stage.mov"))  # intermediates cleaned up


def test_over_cap_fails_before_rendering(master, tmp_path):
    plan = load_plan(_plan(tmp_path, PLAN.replace("cap_s: 5", "cap_s: 2")))
    with pytest.raises(CutError, match="over its 2s cap"):
        run_plan(plan, master, tmp_path / "out", log=lambda _m: None)
    assert not (tmp_path / "out").exists()


def test_cli_check(master, tmp_path, capsys):
    plan = _plan(tmp_path)
    assert main(["cut", str(plan), "--master", str(master), "--check"]) == 0
    assert "short" in capsys.readouterr().out
    assert main(["cut", str(plan), "--master", str(tmp_path / "missing.mp4")]) == 1
