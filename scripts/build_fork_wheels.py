"""Repackage verified upstream wheels with committed Python-only corrections."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Final
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict


class WheelSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    filename: str
    url: str
    sha256: str


class Sources(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: str
    upstream_commit: str
    modules: tuple[str, ...]
    wheels: tuple[WheelSource, ...]


class WheelResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    filename: str
    sha256: str
    upstream_url: str
    upstream_sha256: str


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_commit: str
    upstream_commit: str
    module_sha256: dict[str, str]
    wheel_tool_version: str
    wheels: tuple[WheelResult, ...]


ROOT: Final = Path(__file__).resolve().parent.parent


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def build_wheel(source: WheelSource, sources: Sources, revision: str, destination: Path) -> WheelResult:
    with urllib.request.urlopen(source.url, timeout=120) as response:
        payload: Final = response.read()
    if hashlib.sha256(payload).hexdigest() != source.sha256:
        raise SystemExit(f"Upstream wheel checksum mismatch: {source.filename}")
    patched_modules: Final = {module: git("show", f"{revision}:{module}") for module in sources.modules}
    with tempfile.TemporaryDirectory(prefix="litellm-wheel-") as temporary:
        workspace: Final = Path(temporary)
        original: Final = workspace / source.filename
        original.write_bytes(payload)
        with ZipFile(original) as upstream:
            for module in sources.modules:
                if upstream.read(module) != git("show", f"{sources.upstream_commit}:{module}"):
                    raise SystemExit(
                        f"Upstream wheel Python source differs from pinned tag: {source.filename}: {module}"
                    )
        subprocess.run([sys.executable, "-m", "wheel", "unpack", str(original), "-d", str(workspace)], check=True)
        unpacked: Final = workspace / f"litellm-{sources.version}"
        for module, content in patched_modules.items():
            (unpacked / module).write_bytes(content)
        subprocess.run(
            [sys.executable, "-m", "wheel", "pack", str(unpacked), "-d", str(destination)],
            check=True,
            env={**os.environ, "SOURCE_DATE_EPOCH": git("show", "-s", "--format=%ct", revision).decode().strip()},
        )
        built: Final = destination / source.filename
        with ZipFile(original) as upstream, ZipFile(built) as patched:
            if set(upstream.namelist()) != set(patched.namelist()):
                raise SystemExit(f"Wheel file inventory changed: {source.filename}")
            changed: Final = tuple(name for name in upstream.namelist() if upstream.read(name) != patched.read(name))
            expected: Final = {*sources.modules, f"litellm-{sources.version}.dist-info/RECORD"}
            if set(changed) != expected:
                raise SystemExit(f"Unexpected wheel payload changes in {source.filename}: {changed}")
            for module, content in patched_modules.items():
                if patched.read(module) != content:
                    raise SystemExit(f"Patched module does not match committed source: {source.filename}: {module}")
    return WheelResult(
        filename=source.filename,
        sha256=hashlib.sha256(built.read_bytes()).hexdigest(),
        upstream_url=source.url,
        upstream_sha256=source.sha256,
    )


def main() -> None:
    parser: Final = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--platform", help="Build only wheel filenames containing this platform tag")
    parser.add_argument("--destination", type=Path, default=ROOT / "dist" / "fork")
    args: Final = parser.parse_args()
    sources: Final = Sources.model_validate_json((ROOT / "scripts" / "fork_wheel_sources.json").read_text())
    revision: Final = git("rev-parse", "--verify", f"{args.revision}^{{commit}}").decode().strip()
    destination: Final = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    selected: Final = tuple(
        source for source in sources.wheels if args.platform is None or args.platform in source.filename
    )
    if not selected:
        raise SystemExit("No upstream wheel matches the requested platform")
    provenance: Final = Provenance(
        source_commit=revision,
        upstream_commit=sources.upstream_commit,
        module_sha256={
            module: hashlib.sha256(git("show", f"{revision}:{module}")).hexdigest() for module in sources.modules
        },
        wheel_tool_version=subprocess.check_output([sys.executable, "-m", "wheel", "version"], text=True).strip(),
        wheels=tuple(build_wheel(source, sources, revision, destination) for source in selected),
    )
    (destination / "provenance.json").write_text(provenance.model_dump_json(indent=2) + "\n")
    sys.stdout.write(provenance.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
