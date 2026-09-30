"""Safe-area audit on a synthetic 9:16 video with one safe box and one under the buttons."""

from pathlib import Path

import pytest

from noirstudio import ffmpeg
from noirstudio.cli import main
from noirstudio.safearea import audit, verdict


@pytest.fixture(scope="module")
def video(tmp_path_factory) -> Path:
    """540x960, 4 s: a centred box throughout; a box in the button column (above the bottom band) from t=2 s."""
    path = tmp_path_factory.mktemp("sa") / "v.mp4"
    boxes = ("drawbox=x=150:y=400:w=240:h=80:color=white:t=fill,"
             "drawbox=x=470:y=500:w=60:h=60:color=white:t=fill:enable='gte(t,2)'")
    ffmpeg.run(["-y", "-f", "lavfi", "-i", "color=c=0x100D11:s=540x960:r=10:d=4", "-vf", boxes,
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)])
    return path


def test_audit_finds_the_box_under_the_buttons(video):
    r = audit(video, fps=2)
    assert r["frames"] == 8
    zones = r["zones"]
    assert zones["top"]["share"] == 0 and zones["bottom"]["share"] == 0 and zones["left"]["share"] == 0
    assert 0.35 <= zones["right"]["share"] <= 0.65 and zones["right"]["worst_s"] >= 2
    assert 0.35 <= zones["buttons"]["share"] <= 0.65
    x0, y0, x1, y1 = r["content_extents"]  # in 1080x1920 reference pixels
    assert 290 <= x0 <= 310 and x1 >= 1050 and 790 <= y0 <= 810
    warnings = verdict(r)
    assert any("right edge" in w for w in warnings) and any("button column" in w for w in warnings)


def test_cli_exit_code_signals_trouble(video, capsys):
    assert main(["safe-area", str(video), "--fps", "2"]) == 1
    assert "warning: content in the right edge" in capsys.readouterr().out
