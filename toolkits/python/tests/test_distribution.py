"""Check the shipped client surface, independent of the hosted API."""

import hashlib
import json
import tomllib
from pathlib import Path

from resolvesignal_integration import __version__, build_request, validate_request

ROOT = Path(__file__).resolve().parents[1]


def test_license_version_and_source_hashes_match():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    source = json.loads((ROOT / "SOURCE.json").read_text(encoding="utf-8"))
    assert metadata["project"]["license"]["file"] == "LICENSE"
    assert "MIT License" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert metadata["project"]["version"] == source["version"] == __version__
    for name, digest in source["files_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest


def test_archive_example_paths_and_english_offline_fixture():
    profile = json.loads((ROOT / "examples/profile.json").read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / "examples/runtime.json").read_text(encoding="utf-8"))
    assert profile["locale"] == "en"
    assert runtime["observed_at"] == "2026-10-04T00:00:00Z"
    validate_request(build_request(profile, runtime))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "--profile examples/profile.json" in readme
    assert "--runtime examples/runtime.json" in readme
    assert "Do not make old evidence look fresh" in readme
