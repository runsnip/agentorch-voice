"""Build the voice engine for this machine: dist/voice-<target>.tar.gz and its .sha256.

    python tools/build.py [--tag v1.0.0]

The bundle is self-contained, so AgentOrch only has to download and unpack it:

    voice/
      python/        a standalone CPython 3.12 (python-build-standalone, fetched by uv) with the libraries in it
      worker.py      the resident reader (see worker.py)
      manifest.json  version, and the language packs (models), downloaded separately when turned on
      LICENSE, NOTICE

Needs uv on PATH. <target> is what AgentOrch asks for: macos-arm64, macos-x64, linux-x64, linux-arm64, windows-x64.
"""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD, DIST = ROOT / "build", ROOT / "dist"


def target() -> str:
    os_name = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}[platform.system()]
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "AMD64": "x64"}[platform.machine()]
    return f"{os_name}-{arch}"


def run(*args: str) -> None:
    print("$", " ".join(args), flush=True)
    subprocess.run(args, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if a.tag and a.tag.lstrip("v") != manifest["version"]:
        sys.exit(f"tag {a.tag} doesn't match manifest version {manifest['version']}")

    shutil.rmtree(BUILD, ignore_errors=True)
    out = BUILD / "voice"
    pys = BUILD / "pythons"
    run("uv", "python", "install", "--install-dir", str(pys), manifest["python"])
    found = [p for p in pys.iterdir() if p.is_dir() and not p.is_symlink() and p.name.startswith("cpython-")]
    if not found:
        sys.exit("uv installed no python")
    out.mkdir(parents=True)
    shutil.move(str(found[0]), out / "python")
    exe = out / "python" / ("python.exe" if platform.system() == "Windows" else "bin/python3")
    for marker in (out / "python").rglob("EXTERNALLY-MANAGED"):   # it's ours to install into
        marker.unlink()
    pip = ["uv", "pip", "install", "--python", str(exe), "--break-system-packages", "--no-cache"]
    run(*pip, "-r", str(ROOT / "requirements.txt"))
    run(*pip, "--no-deps", *manifest["no_deps"])
    for f in ("worker.py", "manifest.json", "LICENSE", "NOTICE"):
        shutil.copy2(ROOT / f, out / f)
    # trim what a reader never needs
    for junk in ("**/__pycache__", "**/test", "**/tests", "**/idlelib", "**/tkinter", "**/turtledemo", "**/ensurepip"):
        for p in out.glob(junk):
            shutil.rmtree(p, ignore_errors=True)
    run(str(exe), "-c", "import onnxruntime, vieneu, kokoro_onnx, espeakng_loader, soundfile; print('imports ok', onnxruntime.__version__)")

    DIST.mkdir(exist_ok=True)
    pack = DIST / f"voice-{target()}.tar.gz"
    with tarfile.open(pack, "w:gz") as t:
        t.add(out, arcname="voice")
    digest = hashlib.sha256(pack.read_bytes()).hexdigest()
    (DIST / f"{pack.name}.sha256").write_text(f"{digest}  {pack.name}\n")
    print(pack, round(pack.stat().st_size / 1e6, 1), "MB", digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
