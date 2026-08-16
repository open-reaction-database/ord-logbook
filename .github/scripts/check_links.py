"""Check relative Markdown links across the logbook.

Verifies that every relative link resolves to a file that exists, that its
heading anchor exists in that file, and that a link's visible text does not
name a path other than the one it points at. External links are not fetched.

Run from the repository root:

    python3 .github/scripts/check_links.py
"""

import argparse
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

LINK = re.compile(r"\[(?P<text>[^\]]*)\]\(\s*(?P<target>[^)\s]+)")
FENCE = re.compile(r"^\s*(```|~~~)")
CODE_SPAN = re.compile(r"`[^`]*`")
HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*?)\s*#*\s*$")
INLINE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
PATH_LIKE = re.compile(r"^[\w./-]+(/|\.[A-Za-z]\w*)$")
EXTERNAL = ("http://", "https://", "mailto:", "ftp://", "//")


def slugify(heading: str) -> str:
    """Convert heading text to its GitHub anchor slug.

    Args:
        heading: Raw heading text, which may contain inline code, links, and
            other Markdown.

    Returns:
        The anchor slug GitHub generates for that heading, without a leading ``#``.
    """
    text = INLINE_LINK.sub(r"\1", heading)
    text = text.replace("`", "").replace("*", "").replace("_", "")
    text = re.sub(r"[^\w\s-]", "", text)
    # Each space becomes its own hyphen, so stripped punctuation leaves a gap:
    # "by contract — not by cost" anchors as "by-contract--not-by-cost".
    return re.sub(r"\s", "-", text.strip()).lower()


def anchors(path: Path) -> set[str]:
    """Collect the anchor slugs a Markdown file defines.

    Args:
        path: Markdown file to scan.

    Returns:
        Every anchor slug reachable in the rendered file, including the
        ``-1``-style suffixes GitHub appends to repeated headings.
    """
    found: set[str] = set()
    counts: dict[str, int] = {}
    in_fence = False
    for line in path.read_text().splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING.match(line)
        if not match:
            continue
        slug = slugify(match.group("text"))
        seen = counts.get(slug, 0)
        counts[slug] = seen + 1
        found.add(slug if seen == 0 else f"{slug}-{seen}")
    return found


def links(path: Path):
    """Yield the relative links a Markdown file contains.

    Fenced blocks are skipped whole. Elsewhere a candidate counts only when its
    target sits outside every code span: SMILES such as ``[N+](=O)[O-]`` and
    Python subscripts such as ``LOADERS[t](v)`` are indistinguishable from link
    syntax. Testing the target's position rather than blanking spans outright
    keeps a backticked path usable as link text.

    Args:
        path: Markdown file to scan.

    Yields:
        Tuples of line number, link text, and raw link target.
    """
    in_fence = False
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        spans = [span.span() for span in CODE_SPAN.finditer(line)]
        for match in LINK.finditer(line):
            start = match.start("target")
            if any(begin <= start < end for begin, end in spans):
                continue
            target = match.group("target")
            if target.startswith(EXTERNAL) or target.startswith("#"):
                continue
            yield lineno, match.group("text"), target


def _names(target: str, shown: str) -> bool:
    """Report whether link text names the path the link points at.

    A directory and the ``README.md`` inside it are the same destination, so
    either spelling of one may stand for the other.

    Args:
        target: The link's path, without any anchor.
        shown: The link's visible text, already stripped of backticks.

    Returns:
        True if the text is a suffix of the target under that equivalence.
    """
    forms = {target, re.sub(r"/README\.md$", "/", target)}
    return any(
        form.rstrip("/").endswith(shown.rstrip("/")) for form in forms if form
    )


def check(path: Path, root: Path) -> list[str]:
    """Check every relative link in one Markdown file.

    Args:
        path: Markdown file to check.
        root: Repository root, used to render paths in messages.

    Returns:
        One message per problem found, empty if the file is clean.
    """
    problems = []
    rel = path.relative_to(root)
    for lineno, text, target in links(path):
        where = f"{rel}:{lineno}"
        path_part, _, anchor = target.partition("#")
        resolved = (path.parent / urllib.parse.unquote(path_part)).resolve()

        if not path_part:
            continue
        if not resolved.exists():
            problems.append(f"{where}: broken link: {target}")
            continue
        if resolved == path.resolve():
            problems.append(f"{where}: link points at its own file: {target}")
            continue
        if anchor and resolved.suffix == ".md":
            if urllib.parse.unquote(anchor).lower() not in anchors(resolved):
                problems.append(f"{where}: no such heading: {target}")

        # A path as link text is a promise about where the link goes.
        shown = text.strip("`")
        if PATH_LIKE.match(shown) and not _names(path_part, shown):
            problems.append(f"{where}: text {shown!r} does not match target {target!r}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root", nargs="?", default=".", help="repository root to check"
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()

    tracked = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    problems = []
    for rel in tracked:
        problems.extend(check(root / rel, root))

    for problem in problems:
        print(problem)
    print(f"checked {len(tracked)} files, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
