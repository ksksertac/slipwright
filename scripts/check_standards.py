"""Lint the standards corpus: front-matter, short single-topic sections, unique headings.

Run with: uv run python scripts/check_standards.py [<project repo with .slipwright/standards>]
Exit status 1 lists every problem; tests run the same check.
"""

import sys
from pathlib import Path

from slipwright.standards import chunk_corpus, lint, load_corpus

if __name__ == "__main__":
    repo = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    pages = load_corpus(project_repo=repo)
    problems = lint(pages)
    for problem in problems:
        print(problem)
    print(
        f"{len(pages)} page(s), {len(chunk_corpus(pages))} section(s), {len(problems)} problem(s)"
    )
    sys.exit(1 if problems else 0)
