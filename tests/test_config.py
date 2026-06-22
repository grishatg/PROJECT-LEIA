"""Config loaders validate good config and reject bad config with clear errors."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from leia.config import load_app_settings, load_icp, load_message_guidelines, load_value_prop


def test_real_icp_loads_and_validates():
    icp = load_icp("config/icp.yaml")
    assert icp.name
    assert icp.industries
    assert 0 <= icp.score_threshold <= 100


def test_real_value_prop_loads():
    vp = load_value_prop("config/value_prop.yaml")
    assert vp.offer
    assert vp.cta


def test_real_message_guidelines_load():
    text = load_message_guidelines("config/message_guidelines.md")
    assert "tone" in text.lower()


def test_bad_threshold_is_rejected(tmp_path):
    bad = tmp_path / "icp.yaml"
    bad.write_text("name: Test\nscore_threshold: 150\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_icp(bad)


def test_missing_required_field_is_rejected(tmp_path):
    bad = tmp_path / "value_prop.yaml"
    bad.write_text("proof_points: [a, b]\n", encoding="utf-8")  # no 'offer' or 'cta'
    with pytest.raises(ValidationError):
        load_value_prop(bad)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_icp(tmp_path / "nope.yaml")


def test_app_settings_defaults_when_no_file():
    s = load_app_settings("definitely-not-here.toml")
    assert s.models.brain == "claude-opus-4-8"
    assert s.limits.daily_spend_cap_usd > 0
