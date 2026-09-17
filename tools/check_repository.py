"""Check distributable docs, image resources and accidental sensitive files."""

from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ElementTree

from markdown_it import MarkdownIt
from PySide6.QtGui import QImage


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = MarkdownIt("commonmark").enable("table")
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    ).decode("utf-8").split("\0")
    paths = sorted({ROOT / name for name in files if name and (ROOT / name).is_file()})
    failures = []
    images = set()
    links = 0
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        generated_directories = {".venv", "__pycache__", ".pytest_cache", "artifacts", "build", "dist", "release"}
        if generated_directories.intersection(path.relative_to(ROOT).parts[:-1]):
            failures.append(f"Generated/environment file in publishable tree: {relative}")
        if path.suffix.lower() in (".exe", ".pfx", ".pem", ".key", ".pyc", ".pyo", ".log") or path.name.startswith(".env"):
            failures.append(f"Sensitive/build file in publishable tree: {relative}")
        if path.stat().st_size > 25 * 1024 * 1024:
            failures.append(f"Oversized Git file: {relative}")
        if path.suffix.lower() not in (".md", ".py", ".txt", ".json", ".yml", ".toml", ".cmd", ".qss", ".spec"):
            continue
        text = path.read_text(encoding="utf-8")
        secret_patterns = [r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                           r"gh[pousr]_[A-Za-z0-9]{30,}", r"github_pat_[A-Za-z0-9_]{60,}",
                           r"(?i)[a-z]:[\\/]Users[\\/][^\s]+"]
        if any(re.search(pattern, text) for pattern in secret_patterns):
            failures.append(f"Possible secret or personal machine path: {relative}")
        if path.suffix != ".md":
            continue
        tokens = parser.parse(text)
        headings = {re.sub(r"[^a-z0-9 _-]", "", tokens[index + 1].content.lower()).replace(" ", "-")
                    for index, token in enumerate(tokens) if token.type == "heading_open"}
        for token in tokens:
            for child in token.children or []:
                if child.type not in ("link_open", "image"):
                    continue
                target = child.attrGet("src" if child.type == "image" else "href")
                parsed = urlsplit(target)
                if parsed.scheme:
                    continue
                links += 1
                if not parsed.path:
                    if parsed.fragment and unquote(parsed.fragment) not in headings:
                        failures.append(f"Broken heading: {relative}: {target}")
                    continue
                linked = (path.parent / unquote(parsed.path)).resolve()
                if not linked.is_relative_to(ROOT) or not linked.is_file() or linked not in paths:
                    failures.append(f"Missing/unpublished local link: {relative}: {target}")
                elif child.type == "image":
                    images.add(linked)
    stylesheet = ROOT / "nfc_workbench" / "assets" / "theme.qss"
    if stylesheet.is_file():
        for filename in re.findall(r'url\("@ASSETS@/([^"\n]+)"\)', stylesheet.read_text(encoding="utf-8")):
            image = stylesheet.parent / filename
            if image not in paths:
                failures.append(f"Missing/unpublished UI image: {filename}")
            else:
                images.add(image)
    for path in paths:
        if path.suffix.lower() in (".png", ".svg", ".jpg", ".jpeg", ".webp") and path not in images:
            failures.append(f"Unreferenced image in publishable tree: {path.relative_to(ROOT)}")
    for image in images:
        if image.suffix == ".svg":
            ElementTree.parse(image)
        elif QImage(str(image)).isNull():
            failures.append(f"Invalid image: {image.relative_to(ROOT)}")
    print(f"Checked {len(paths)} publishable files, {links} local document links and {len(images)} images.")
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())