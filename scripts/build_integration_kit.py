"""Build the public client archive without private application dependencies."""

import argparse
import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "toolkits/python"
STAMP = (2026, 10, 8, 0, 0, 0)
FILES = (
    "pyproject.toml", "README.md", "LICENSE",
    "resolvesignal_integration/__init__.py",
    "resolvesignal_integration/__main__.py",
    "resolvesignal_integration/cli.py",
    "resolvesignal_integration/client.py",
    "resolvesignal_integration/schemas/request-schema.json",
    "examples/profile.json", "examples/runtime.json",
)


def build(output: Path) -> Path:
    source = json.loads((KIT / "SOURCE.json").read_text(encoding="utf-8"))
    metadata = tomllib.loads((KIT / "pyproject.toml").read_text(encoding="utf-8"))
    version = metadata["project"]["version"]
    if source["version"] != version or set(source["files_sha256"]) != set(FILES):
        raise ValueError("Source manifest/version mismatch")
    for name in FILES:
        actual = hashlib.sha256((KIT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != source["files_sha256"][name]:
            raise ValueError(f"Source hash mismatch: {name}")
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / f"resolvesignal-python-{version}.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        for name in FILES:
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (KIT / name).read_bytes().replace(b"\r\n", b"\n"))
        archive.writestr(
            zipfile.ZipInfo("SOURCE.json", STAMP),
            (KIT / "SOURCE.json").read_bytes().replace(b"\r\n", b"\n"),
        )
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {bundle.name}\n", encoding="utf-8")
    return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".release/integration")
    print(build(parser.parse_args().output))
