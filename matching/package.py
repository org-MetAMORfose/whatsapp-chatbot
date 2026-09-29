"""Build a Lambda ZIP containing matching and the shared domain/ORM only."""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def copy_sources(target: Path) -> None:
    for directory in ("matching", "app/domain/db", "app/domain/enum", "app/domain/matching"):
        destination = target / directory
        destination.mkdir(parents=True, exist_ok=True)
        for source in (ROOT / directory).glob("*.py"):
            if directory == "matching" and source.name in ("deploy.py", "package.py", "simulate.py"):
                continue
            shutil.copy2(source, destination / source.name)
    (target / "app").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "app/__init__.py", target / "app/__init__.py")


def build(output: Path, runtime: str = "python3.13", architecture: str = "x86_64") -> Path:
    if runtime not in ("python3.12", "python3.13") or architecture not in ("x86_64", "arm64"):
        raise ValueError("Use a Python 3.12–3.13 Lambda (x86_64 or arm64)")
    machine = "aarch64" if architecture == "arm64" else "x86_64"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="matching-package-") as directory:
        target = Path(directory)
        subprocess.run([sys.executable,  # noqa: S603
             "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
            "--only-binary=:all:", "--implementation", "cp", "--python-version", runtime.removeprefix("python"),
            "--platform", f"manylinux2014_{machine}", "--platform", f"manylinux_2_28_{machine}",
            "--target", str(target), "-r", str(ROOT / "matching/requirements.txt")], check=True)
        copy_sources(target)
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for path in sorted(target.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    archive.write(path, path.relative_to(target))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist/matching.zip"))
    parser.add_argument("--runtime", default="python3.13")
    parser.add_argument("--architecture", default="x86_64")
    args = parser.parse_args()
    build(args.output, args.runtime, args.architecture)
