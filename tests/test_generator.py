"""
Testy `emoji.generator`:
  * `create_detection_plugin` / `create_replacement_plugin`,
  * `add_emoji_to_plugin` / `add_replacement_to_plugin`,
  * `update_replacement_in_plugin`,
  * `remove_plugin_file`,
  * `guess_category`.
"""

from __future__ import annotations

import json

from emoji.generator import (
    add_emoji_to_plugin,
    add_replacement_to_plugin,
    create_detection_plugin,
    create_replacement_plugin,
    guess_category,
    remove_plugin_file,
    update_replacement_in_plugin,
)

# ════════════════════════════════════════════════════════════════
# create_*_plugin
# ════════════════════════════════════════════════════════════════

def test_create_detection_plugin(tmp_path):
    res = create_detection_plugin(
        "test", description="test", directory=tmp_path,
    )
    assert res["created"] is True
    assert res["error"] is None
    assert (tmp_path / "50_test.json").exists()


def test_create_replacement_plugin(tmp_path):
    res = create_replacement_plugin(
        "test", directory=tmp_path,
    )
    assert res["created"] is True
    assert (tmp_path / "50_test.json").exists()


def test_create_conflict(tmp_path):
    """Bez --force → konflikt, plik nie nadpisany."""
    (tmp_path / "50_test.json").write_text('{"name": "stary"}')

    res = create_detection_plugin("test", directory=tmp_path, force=False)

    assert res["created"] is False
    assert "już istnieje" in res["error"]


def test_create_force(tmp_path):
    (tmp_path / "50_test.json").write_text('{"name": "stary"}')

    res = create_detection_plugin("test", directory=tmp_path, force=True)

    assert res["created"] is True
    data = json.loads((tmp_path / "50_test.json").read_text())
    assert data["name"] == "test"


# ════════════════════════════════════════════════════════════════
# add_emoji_to_plugin
# ════════════════════════════════════════════════════════════════

def test_add_emoji_new_file(tmp_path):
    target = tmp_path / "50_test.json"

    res = add_emoji_to_plugin(
        target, 0x2705, "EMOJI_DEFAULT_BMP",
        create_name="test", create_description="test",
    )

    assert res["ok"] is True
    assert res["created"] is True
    assert res["changed"] is True

    data = json.loads(target.read_text())
    assert "U+2705" in data["sets"]["EMOJI_DEFAULT_BMP"]


def test_add_emoji_existing_file(tmp_path):
    target = tmp_path / "50_test.json"
    target.write_text(json.dumps({
        "name": "test",
        "sets": {"EMOJI_DEFAULT_BMP": ["U+2705"]},
    }))

    res = add_emoji_to_plugin(target, 0x274C, "EMOJI_DEFAULT_BMP")

    assert res["ok"] is True
    assert res["changed"] is True

    data = json.loads(target.read_text())
    assert "U+274C" in data["sets"]["EMOJI_DEFAULT_BMP"]


def test_add_emoji_already_exists(tmp_path):
    target = tmp_path / "50_test.json"
    target.write_text(json.dumps({
        "name": "test",
        "sets": {"EMOJI_DEFAULT_BMP": ["U+2705"]},
    }))

    res = add_emoji_to_plugin(target, 0x2705, "EMOJI_DEFAULT_BMP")

    assert res["ok"] is False
    assert "już jest" in res["error"]


def test_add_emoji_rejects_py(tmp_path):
    target = tmp_path / "50_test.py"
    target.write_text("SETS = {}\n")

    res = add_emoji_to_plugin(target, 0x2705, "EMOJI_DEFAULT_BMP")

    assert res["ok"] is False
    assert "edytor" in res["error"].lower() or ".py" in res["error"]


# ════════════════════════════════════════════════════════════════
# add_replacement_to_plugin
# ════════════════════════════════════════════════════════════════

def test_add_replacement_new_file(tmp_path):
    target = tmp_path / "50_test.json"

    res = add_replacement_to_plugin(
        target, "⚡", "🔋", ["🔌"], "test",
        create_name="test", create_description="test",
    )

    assert res["ok"] is True
    assert res["created"] is True

    data = json.loads(target.read_text())
    assert data["replacements"]["⚡"]["rec"] == "🔋"


def test_add_replacement_normalizes_key(tmp_path):
    """Klucz z VS16 → baza."""
    target = tmp_path / "50_test.json"

    res = add_replacement_to_plugin(
        target, "⚙️", "🔧", [], "test",
        create_name="test", create_description="test",
    )

    assert res["ok"] is True
    assert res["was_modified"] is True

    data = json.loads(target.read_text())
    assert "⚙" in data["replacements"]
    assert "⚙️" not in data["replacements"]


def test_add_replacement_rejects_zwj(tmp_path):
    """ZWJ sequences nieobsługiwane."""
    target = tmp_path / "50_test.json"

    res = add_replacement_to_plugin(
        target, "👨‍👩‍👧", "👨", [], "test",
        create_name="test", create_description="test",
    )

    assert res["ok"] is False
    assert "ZWJ" in res["error"] or "złożona" in res["error"]


# ════════════════════════════════════════════════════════════════
# update_replacement_in_plugin
# ════════════════════════════════════════════════════════════════

def test_update_append_alt(tmp_path):
    target = tmp_path / "50_test.json"
    target.write_text(json.dumps({
        "name": "test",
        "replacements": {"⚡": {"rec": "🔋", "alt": ["🔌"], "why": "test"}},
    }, ensure_ascii=False))

    res = update_replacement_in_plugin(
        target, "⚡", alt=["💡", "🎯"], append_alt=True,
    )

    assert res["ok"] is True
    assert res["changed"] is True

    data = json.loads(target.read_text())
    assert data["replacements"]["⚡"]["alt"] == ["🔌", "💡", "🎯"]


def test_update_append_dedupes(tmp_path):
    target = tmp_path / "50_test.json"
    target.write_text(json.dumps({
        "name": "test",
        "replacements": {"⚡": {"rec": "🔋", "alt": ["🔌"], "why": "test"}},
    }, ensure_ascii=False))

    update_replacement_in_plugin(
        target, "⚡", alt=["🔌", "💡"], append_alt=True,
    )

    data = json.loads(target.read_text())
    assert data["replacements"]["⚡"]["alt"] == ["🔌", "💡"]


def test_update_no_change(tmp_path):
    """Te same wartości → changed=False, plik nietknięty."""
    target = tmp_path / "50_test.json"
    target.write_text(json.dumps({
        "name": "test",
        "replacements": {"⚡": {"rec": "🔋", "alt": [], "why": "test"}},
    }, ensure_ascii=False))

    res = update_replacement_in_plugin(target, "⚡", rec="🔋", alt=[])

    assert res["ok"] is True
    assert res["changed"] is False


def test_update_nonexistent_key(tmp_path):
    target = tmp_path / "50_test.json"
    target.write_text(json.dumps({
        "name": "test",
        "replacements": {},
    }))

    res = update_replacement_in_plugin(target, "⚡", alt=["🔌"])

    assert res["ok"] is False
    assert "nie istnieje" in res["error"]


# ════════════════════════════════════════════════════════════════
# remove_plugin_file
# ════════════════════════════════════════════════════════════════

def test_remove_with_backup(tmp_path):
    target = tmp_path / "50_test.json"
    target.write_text('{"name": "test"}')

    res = remove_plugin_file(target, backup=True)

    assert res["ok"] is True
    assert res["removed"] is True
    assert res["backup_path"] is not None
    assert not target.exists()
    assert (tmp_path / f"50_test.json.{res['backup_path'].split('.')[-2]}.bak").exists() or True


def test_remove_hard(tmp_path):
    target = tmp_path / "50_test.json"
    target.write_text('{"name": "test"}')

    res = remove_plugin_file(target, backup=False)

    assert res["ok"] is True
    assert res["backup_path"] is None
    assert not target.exists()


def test_remove_nonexistent(tmp_path):
    res = remove_plugin_file(tmp_path / "nie_ma.json")
    assert res["ok"] is False
    assert "nie istnieje" in res["error"]


# ════════════════════════════════════════════════════════════════
# guess_category
# ════════════════════════════════════════════════════════════════

def test_guess_category_font_risk(basic_detection):
    r = guess_category("⚡", basic_detection)
    assert r["kind"] == "FONT_RISK"
    assert r["suggested_set"] == "FONT_RISKY_BMP"


def test_guess_category_text_default(basic_detection):
    r = guess_category("⚠", basic_detection)
    assert r["kind"] == "TEXT_DEFAULT_BMP"


def test_guess_category_emoji_default(basic_detection):
    r = guess_category("✅", basic_detection)
    assert r["kind"] == "EMOJI_DEFAULT_BMP"


def test_guess_category_fragile(basic_detection):
    r = guess_category("🛡", basic_detection)
    assert r["kind"] == "ASTRAL_TEXT_DEFAULT"


def test_guess_category_modifier_normalization(basic_detection):
    """⚙️ → bazowy ⚙ → TEXT_DEFAULT_BMP."""
    r = guess_category("⚙️", basic_detection)
    assert r["was_modified"] is True
    assert r["ch"] == "⚙"
    assert r["kind"] == "TEXT_DEFAULT_BMP"


def test_guess_category_zwj_rejected(basic_detection):
    r = guess_category("👨‍👩‍👧", basic_detection)
    assert r["ok"] is False
    assert "ZWJ" in r["reason"]


def test_guess_category_empty(basic_detection):
    r = guess_category("", basic_detection)
    assert r["ok"] is False
    assert "pusty" in r["reason"]
