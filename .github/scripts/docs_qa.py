"""Static QA for the AISdb GitBook repository.

Checks every Markdown page for the repository's editorial and structural
invariants. Exits non-zero when any check fails so CI can gate on it.
"""

import glob
import os
import re
import sys

ERRORS = []

DEAD_HOSTS = ("aisdb.meridian.cs.dal.ca",)

DELETED_REPOS = (
    "AISdb-Server",
    "AISdb-WebAssembly",
    "AISdb-Web",
    "aisdb-api",
    "aisdb-cli",
    "aisdb-server-installer",
    "supporting-scripts",
    "NOAA-AIS-Integrator",
)


def error(msg):
    ERRORS.append(msg)


def md_files():
    return sorted(
        f for f in glob.glob("**/*.md", recursive=True) if not f.startswith(".git/")
    )


def strip_code(text):
    """Remove fenced code blocks and GitBook <pre> blocks from Markdown."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"<pre[^>]*>.*?</pre>", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]+`", "", text)
    return text


def check_no_em_dash(path, text):
    prose = strip_code(text)
    for i, line in enumerate(prose.split("\n"), 1):
        if "—" in line:
            error(f"{path}: em-dash in prose near line {i}")


def check_no_artifacts(path, text):
    for tag in ("</content>", "</document>", "<system-reminder"):
        if tag in text:
            error(f"{path}: leftover artifact tag {tag!r}")


def check_balanced_fences(path, text):
    if text.count("```") % 2:
        error(f"{path}: unbalanced code fences")


def check_internal_links(path, text):
    base = os.path.dirname(path)
    for m in re.finditer(r"\]\((?!https?://|mailto:|#)([^)#]+\.md)(#[^)]*)?\)", text):
        target = os.path.normpath(os.path.join(base, m.group(1)))
        if not os.path.exists(target):
            error(f"{path}: broken internal link -> {m.group(1)}")


def check_images(path, text):
    base = os.path.dirname(path)
    patterns = [
        r"!\[[^\]]*\]\(<([^>]+)>\)",  # GitBook form for paths with spaces
        r"!\[[^\]]*\]\((?!https?://|<)([^)]+)\)",
        r'<img src="(?!https?://)([^"]+)"',
        r'{% file src="(?!https?://)([^"]+)"',
    ]
    for pat in patterns:
        for m in re.finditer(pat, text):
            raw = m.group(1).replace("%20", " ").replace("&#x20;", " ")
            target = os.path.normpath(os.path.join(base, raw))
            if not os.path.exists(target):
                error(f"{path}: missing asset -> {raw}")


def check_no_drift(path, text):
    for i, line in enumerate(text.split("\n"), 1):
        for needle in DEAD_HOSTS:
            if needle in line:
                error(f"{path}: dead host {needle!r} at line {i}")
        found = [n for n in DELETED_REPOS if n in line]
        for needle in found:
            if any(needle != other and needle in other for other in found):
                continue  # shadowed by a longer repo name on the same line
            error(f"{path}: deleted repo {needle!r} at line {i}")


def check_summary():
    with open("SUMMARY.md", encoding="utf-8") as fh:
        summary = fh.read()
    for m in re.finditer(r"\]\(([^)]+\.md)\)", summary):
        if not os.path.exists(m.group(1)):
            error(f"SUMMARY.md: entry points at missing page {m.group(1)}")


def main():
    for path in md_files():
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        check_no_em_dash(path, text)
        check_no_artifacts(path, text)
        check_balanced_fences(path, text)
        check_internal_links(path, text)
        check_images(path, text)
        check_no_drift(path, text)
    check_summary()

    if ERRORS:
        print(f"FAILED: {len(ERRORS)} issue(s)")
        for e in ERRORS:
            print(f"  {e}")
        return 1
    print(f"OK: {len(md_files())} Markdown files pass all checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
