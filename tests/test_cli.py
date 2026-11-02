import os

import click
import pytest

from branch_memory.cli import KEY_NAME, _require_key


@pytest.fixture
def clean_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(KEY_NAME, raising=False)
    # monkeypatch restores this variable after the test, even though the code sets it.
    monkeypatch.setenv(KEY_NAME, "")
    return tmp_path


@pytest.mark.parametrize("line", [
    "ANTHROPIC_API_KEY=from-file",
    'ANTHROPIC_API_KEY="from-file"',
    "export ANTHROPIC_API_KEY=from-file",
    "﻿ANTHROPIC_API_KEY=from-file",
])
def test_key_is_read_from_env_file(clean_dir, line):
    (clean_dir / ".env").write_text(f"{line}\n# comment\nOTHER=x\n", encoding="utf-8")
    _require_key()
    assert os.environ[KEY_NAME] == "from-file"
    assert "OTHER" not in os.environ


def test_environment_wins_over_env_file(clean_dir, monkeypatch):
    (clean_dir / ".env").write_text(f"{KEY_NAME}=from-file\n", encoding="utf-8")
    monkeypatch.setenv(KEY_NAME, "from-shell")
    _require_key()
    assert os.environ[KEY_NAME] == "from-shell"


def test_missing_key_fails_loudly(clean_dir):
    with pytest.raises(click.ClickException, match="not set"):
        _require_key()
