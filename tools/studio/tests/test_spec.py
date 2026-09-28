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
