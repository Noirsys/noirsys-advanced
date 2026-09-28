import pytest

from noirstudio.brandkit import get_brand
from noirstudio.spec import SpecError, spec_from_dict


def test_overrides_replace_fields_without_mutating_builtin():
    base = get_brand("noirsys")
    kit = get_brand("noirsys", {"wordmark": "HER", "accent": "#8B7CFF", "url": "her.example"})
    assert kit.wordmark == "HER" and kit.accent == "#8B7CFF" and kit.url == "her.example"
    assert kit.font_display == base.font_display
    assert get_brand("noirsys").wordmark == "NOIRSYS"


def test_spec_validates_overrides():
    ok = spec_from_dict({"id": "x", "title": "T", "scenes": ["a"], "brand_overrides": {"wordmark": "HER", "accent": "#123456"}})
    assert ok.brand_overrides["wordmark"] == "HER"
    with pytest.raises(SpecError, match="not overridable"):
        spec_from_dict({"id": "x", "title": "T", "scenes": ["a"], "brand_overrides": {"font_display": "x"}})
    with pytest.raises(SpecError, match="RRGGBB"):
        spec_from_dict({"id": "x", "title": "T", "scenes": ["a"], "brand_overrides": {"accent": "purple"}})
