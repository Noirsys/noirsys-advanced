from pathlib import Path

import pytest
import yaml

from noirstudio.spec import SpecError, load_spec, spec_from_dict, starter_spec, validate

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_example_specs_load_and_validate():
    for path in sorted(EXAMPLES.glob("*.yaml")):
        spec = load_spec(path)
        assert validate(spec) == []
        assert spec.scenes[0].id == "s01"
        assert spec.digest() == spec.digest()


def test_starter_spec_is_valid():
    spec = spec_from_dict(yaml.safe_load(starter_spec("demo", "noirpost")))
    assert spec.id == "demo"
    assert spec.brand == "noirpost"
    assert len(spec.scenes) == 3


def test_scene_shorthand_string_becomes_card():
    spec = spec_from_dict({"id": "x", "title": "T", "scenes": ["Just narration."]})
    assert spec.scenes[0].kind == "card"
    assert spec.scenes[0].text == "Just narration."


@pytest.mark.parametrize(
    "data, fragment",
    [
        ({"title": "T", "scenes": ["a"]}, "missing required `id`"),
        ({"id": "x", "title": "T"}, "non-empty `scenes`"),
        ({"id": "Bad ID", "title": "T", "scenes": ["a"]}, "`id` must be"),
        ({"id": "x", "title": "T", "scenes": [{"text": "a", "kind": "hologram"}]}, "kind must be"),
        ({"id": "x", "title": "T", "scenes": [{"text": "a", "kind": "broll"}]}, "needs a `prompt`"),
        ({"id": "x", "title": "T", "scenes": [{"text": "a", "kind": "image"}]}, "needs `media`"),
        ({"id": "x", "title": "T", "scenes": [{"text": "a", "bogus": 1}]}, "unknown keys"),
        ({"id": "x", "title": "T", "scenes": ["a"], "captions": {"mode": "karaoke"}}, "captions.mode"),
        ({"id": "x", "title": "T", "scenes": ["a"], "output": {"width": 1081}}, "must be even"),
        ({"id": "x", "title": "T", "scenes": [{"text": "a", "id": "d"}, {"text": "b", "id": "d"}]}, "duplicate"),
    ],
)
def test_invalid_specs_raise(data, fragment):
    with pytest.raises(SpecError) as excinfo:
        spec_from_dict(data)
    assert fragment in str(excinfo.value)


def test_narration_joins_scene_text():
    spec = spec_from_dict({"id": "x", "title": "T", "scenes": ["One.", {"text": " Two. "}]})
    assert spec.narration == "One. Two."


def test_production_specs_validate_and_fit_shorts():
    specs_dir = Path(__file__).resolve().parents[3] / "specs"
    found = sorted(specs_dir.glob("*.yaml"))
    assert found, "no production specs in specs/"
    for path in found:
        spec = load_spec(path)
        assert validate(spec) == []
        words = len(spec.narration.split())
        assert words <= 160, f"{path.name}: {words} words is too long for a Short"
        if spec.id.startswith("agent-log-"):
            assert spec.publish.ai_disclosure is True
            assert spec.captions.uppercase is False


def test_agent_log_never_uses_his_voice():
    # persona bible: she speaks with a designed voice, never his clone
    specs = [load_spec(p) for p in sorted((Path(__file__).resolve().parents[3] / "specs").glob("*.yaml"))]
    his = {s.voice.voice_id for s in specs if s.voice.voice_id and not s.id.startswith("agent-log-")}
    assert his, "no spec carries his voice_id"
    for s in specs:
        if s.id.startswith("agent-log-"):
            assert s.voice.voice_id not in his, f"{s.id} uses a voice from his specs"
