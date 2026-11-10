"""Build or verify the deployable skills and their source manifest (standard library only)."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def runtime_package(root):
    sources = {"主提示词_v0.2_编排版.md": (root / "主提示词_v0.2_编排版.md").read_bytes()}
    scripts, archives = {}, {}
    for skill in sorted((root / "skills").iterdir()):
        if not skill.is_dir() or not (skill / "SKILL.md").is_file():
            continue
        files = {"SKILL.md": (skill / "SKILL.md").read_bytes()}
        sources[(skill / "SKILL.md").relative_to(root).as_posix()] = files["SKILL.md"]
        if skill.name == "admission-v0-2-catalog":
            files["extract-items-checked.json"] = (skill / "extract-items-checked.json").read_bytes()
            for path in sorted((skill / "scripts").rglob("*")):
                if path.is_file() and path.suffix in {".py", ".json"}:
                    files[path.relative_to(skill).as_posix()] = path.read_bytes()
            scripts.update({(skill / name).relative_to(root).as_posix(): data
                            for name, data in files.items() if name != "SKILL.md"})
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 11, 10, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        filename = "Archive.zip" if skill.name == "admission-v0-2-catalog" else "SKILL.md.zip"
        archives[(skill / filename).relative_to(root).as_posix()] = output.getvalue()
    manifest = {
        "contract": "admission-noshell-v0-2",
        "revision": "0.2",
        "attachment_release": {"mode": "automatic", "agent_tool_config": {}, "requires_marker": False, "read_on_demand": True},
        "runtime_characters": sum(len(data.decode("utf-8")) for data in sources.values()),
        "files": [{"path": name, "sha256": digest(data)} for name, data in sources.items()],
        "script_characters": sum(len(data.decode("utf-8")) for data in scripts.values()),
        "script_files": [{"path": name, "sha256": digest(data)} for name, data in scripts.items()],
        "archives": [{"path": name, "sha256": digest(data)} for name, data in archives.items()],
    }
    return archives, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="rebuild packages and the manifest")
    mode.add_argument("--check", action="store_true", help="fail on any source/package/manifest drift")
    args = parser.parse_args()
    archives, manifest = runtime_package(ROOT)
    outputs = {**archives, "runtime_manifest.json": manifest}
    mismatches = []
    for name, data in outputs.items():
        path = ROOT / name
        if args.write:
            path.write_bytes(data)
        elif not path.is_file() or path.read_bytes() != data:
            mismatches.append(name)
    if mismatches:
        parser.exit(1, "OUT_OF_SYNC\n" + "\n".join(mismatches) + "\n")
    print(f"OK {len(archives)} skill packages and runtime_manifest.json")


if __name__ == "__main__":
    main()
