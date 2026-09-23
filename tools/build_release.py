#!/usr/bin/env python3
"""Build local archives from a reviewed allowlist; never publish or read author books."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

FILES = [
    ".gitignore", "README.md", "LICENSE", "VERSION", "CHANGELOG.md", "PRIVACY.md", "CONTRIBUTING.md",
    "skills/book-companion/SKILL.md", "skills/book-companion/agents/openai.yaml",
    "skills/book-companion/references/writing-method.md",
    "skills/book-companion/references/project-protocol.md",
    "skills/book-companion/references/materials.md", "skills/book-companion/references/review.md",
    "skills/book-companion/scripts/book_state.py",
    "tests/test_book_state.py", "tests/test_release.py", "tools/build_release.py",
    "docs/RELEASE.md", "docs/TESTING.md", "docs/EVALUATION.md",
]


def collect(root):
    root = root.resolve()
    content = {}
    # A conservative heuristic, not a guarantee that all secrets are detectable.
    patterns = [r"\bsk-[A-Za-z0-9_-]{20,}", r"\bgh[pousr]_[A-Za-z0-9]{20,}",
                r"github_pat_[A-Za-z0-9_]{20,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                r"/" + r"Users/[^/\s]+/", r"[A-Za-z0-9._%+-]+@(?:gmail|qq)\.com"]
    for name in FILES:
        path = root / name
        if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
            raise ValueError("symlink excluded: " + name)
        if root not in path.resolve().parents:
            raise ValueError("path outside package: " + name)
        data = path.read_bytes()
        value = data.decode("utf-8")
        if any(re.search(pattern, value) for pattern in patterns):
            raise ValueError("possible private content; inspect locally: " + name)
        content[name] = data
    return content


def archive(path, content):
    manifest = {name: hashlib.sha256(value).hexdigest() for name, value in sorted(content.items())}
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, value in sorted(content.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, value)
        info = zipfile.ZipInfo("SHA256SUMS.json", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        bundle.writestr(info, json.dumps(manifest, indent=2) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root, output):
    root, output = root.resolve(), output.resolve()
    if root == output or root in output.parents:
        raise ValueError("release output must be outside the source repository")
    content = collect(root)
    version = content["VERSION"].decode().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-z0-9.]+)?", version):
        raise ValueError("invalid version")
    output.mkdir(parents=True, exist_ok=False)
    skill = {"book-companion/" + name.removeprefix("skills/book-companion/"): data
             for name, data in content.items() if name.startswith("skills/book-companion/")}
    skill["book-companion/LICENSE"] = content["LICENSE"]
    sums = {}
    for name, files in [(f"book-companion-source-{version}.zip", content),
                        (f"book-companion-skill-{version}.zip", skill)]:
        sums[name] = archive(output / name, files)
    with (output / "checksums.json").open("x", encoding="utf-8") as stream:
        json.dump(sums, stream, indent=2)
        stream.write("\n")
    return sums


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(build(Path(__file__).resolve().parents[1], args.output_dir), indent=2))
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")
