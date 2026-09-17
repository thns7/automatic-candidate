from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
import yaml

from automatic_candidate.config import Profile, Settings, load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
CHROMIUM_CANDIDATES = [
    os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE", ""),
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
]


@pytest.fixture(scope="session")
def example_profile() -> Profile:
    raw = yaml.safe_load((REPO_ROOT / "config" / "profile.example.yaml").read_text(encoding="utf-8"))
    return Profile(raw)


@pytest.fixture(scope="session")
def example_settings() -> Settings:
    return load_settings(REPO_ROOT / "config" / "settings.example.yaml")


@pytest.fixture(scope="session")
def chromium_path() -> str:
    for candidate in CHROMIUM_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return ""


@pytest.fixture
def form_url() -> str:
    return (REPO_ROOT / "tests" / "fixtures_form.html").as_uri()
