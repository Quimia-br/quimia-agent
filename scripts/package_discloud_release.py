"""Empacota o quimia-agent no ZIP aceito pela Discloud.

Uso: python scripts/package_discloud_release.py OUTPUT_ZIP
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDED_DIRS = ("app", "data")
OPTIONAL_DIRS = {"data"}
INCLUDED_FILES = ("requirements.txt", "discloud.config")
EXCLUDED_PARTS = {"__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
REQUIRED_ENTRIES = {"discloud.config", "requirements.txt", "app/main.py"}
FORBIDDEN_NAMES = {".env"}


def collect_files() -> list[Path]:
    files = [ROOT / name for name in INCLUDED_FILES]
    for directory in INCLUDED_DIRS:
        if directory in OPTIONAL_DIRS and not (ROOT / directory).is_dir():
            continue
        files.extend(
            path
            for path in sorted((ROOT / directory).rglob("*"))
            if path.is_file()
            and not EXCLUDED_PARTS.intersection(path.parts)
            and path.suffix not in EXCLUDED_SUFFIXES
        )
    return files


def validate_entries(entries: set[str]) -> None:
    missing = REQUIRED_ENTRIES - entries
    if missing:
        raise SystemExit(f"ZIP is missing required entries: {sorted(missing)}")
    leaked = {e for e in entries if Path(e).name in FORBIDDEN_NAMES}
    if leaked:
        raise SystemExit(f"ZIP must not contain secrets: {sorted(leaked)}")
    top_level = {e.split("/")[0] for e in entries}
    allowed = set(INCLUDED_DIRS) | set(INCLUDED_FILES)
    if not top_level <= allowed:
        raise SystemExit(f"Unexpected top-level entries: {sorted(top_level - allowed)}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: package_discloud_release.py OUTPUT_ZIP", file=sys.stderr)
        return 2

    output = Path(argv[1])
    if output.is_dir():
        print("output path is invalid", file=sys.stderr)
        return 1

    files = collect_files()
    for path in files:
        if not path.is_file():
            print(f"required file is missing: {path.relative_to(ROOT)}", file=sys.stderr)
            return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())

    with zipfile.ZipFile(output) as archive:
        validate_entries(set(archive.namelist()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
