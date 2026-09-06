"""Bring an already-harvested Wikipedia pack up to the current import rules.

The long network harvest and the decisions about how imported text should be
labelled happened in that order, so a pack fetched by the earlier code carries
three defects:

  * ``kids_safe: true`` on text nobody has read, across a harvest that includes
    wars, battles, diseases and human anatomy;
  * an ``age9_12`` reading level for the Simple English text, which is written
    for readers with limited English rather than for children specifically; and
  * Wikipedia's own reference superscripts — "[2]", "[17]", "[citation needed]"
    — surviving into article bodies. In this schema ``[n]`` *is* a citation
    link, so an inherited one points at a citation the article does not have.

The first two are relabelling. The third removes text, but only text that would
otherwise render as a false citation: the words of every claim are untouched.
Running the current importer over the network would produce exactly this output,
which is why this exists instead of a 55-minute refetch.

Re-running is safe and idempotent: the first run keeps the untouched harvest as
``*.orig`` and every later run rewrites from that original.

    python scripts/retag_import.py content/packs/wikipedia
"""

from __future__ import annotations

import gzip
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from encarta.pipeline.wikipedia import _WIKI_REF_RE, strip_reference_markers

OLD_LEVEL = "age9_12"
NEW_LEVEL = "teen"

#: Which citation marker belongs on each level's opening paragraph, matching
#: WikipediaImporter._article(): [1] cites the English revision, [2] the Simple
#: English one.
LEVEL_MARKER = {"adult": 1, NEW_LEVEL: 2}


def _open(path: Path, mode: str, *, gz: bool):
    """Open a text stream, always UTF-8.

    Compression is decided by the caller rather than by the filename: the
    working copies are named `.gz.orig` and `.gz.tmp`, so trusting the
    suffix would read a gzip stream as plain text — and on Windows an
    unspecified encoding silently means cp1252, which mangles every
    non-ASCII title in the pack.
    """
    if gz:
        return gzip.open(path, mode, encoding="utf-8")
    return open(path, mode, encoding="utf-8")


def retag(pack: Path) -> tuple[int, int, int, int]:
    """Rewrite the pack's JSONL in place.

    Returns (articles, demoted, relevelled, bodies_cleaned).
    """
    source = next(
        (pack / name for name in ("articles.jsonl.gz", "articles.jsonl")
         if (pack / name).is_file()),
        None,
    )
    if source is None:
        raise SystemExit(f"no articles.jsonl[.gz] in {pack}")

    gz = source.suffix == ".gz"
    backup = source.with_suffix(source.suffix + ".orig")
    if not backup.exists():
        shutil.copy2(source, backup)

    total = demoted = relevelled = cleaned_bodies = 0
    temp = source.with_suffix(source.suffix + ".tmp")
    with _open(backup, "rt", gz=gz) as fin, _open(temp, "wt", gz=gz) as fout:
        for line_no, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                continue
            try:
                article = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{source.name}:{line_no}: {exc}") from exc

            total += 1
            if article.get("kids_safe") is not False:
                article["kids_safe"] = False
                demoted += 1

            content = article.get("content") or {}
            if OLD_LEVEL in content:
                # Preserve ordering: adult first, then the simplified text.
                content[NEW_LEVEL] = content.pop(OLD_LEVEL)
                article["content"] = content
                relevelled += 1

            for level, block in content.items():
                marker = LEVEL_MARKER.get(level)
                if marker is None:
                    continue
                before = block.get("body") or ""
                # Strip every marker, ours included, then put ours back exactly
                # where the importer puts it. Reproducing the importer's output
                # is the point: this pack must be indistinguishable from one
                # fetched by the current code.
                # Every body carries exactly one marker of our own, so anything
                # beyond the first match is inherited from Wikipedia. Counting
                # actual removals rather than any change keeps the reported
                # number honest — whitespace normalisation touches thousands of
                # bodies and would otherwise be reported as false citations.
                strays = len(_WIKI_REF_RE.findall(before)) - 1
                if strays > 0:
                    cleaned_bodies += strays

                cleaned = strip_reference_markers(before)
                paragraphs = cleaned.split("\n\n")
                paragraphs[0] = f"{paragraphs[0].rstrip()} [{marker}]"
                block["body"] = "\n\n".join(paragraphs)
                if "summary" in block:
                    block["summary"] = strip_reference_markers(block["summary"])
            if article.get("summary"):
                article["summary"] = strip_reference_markers(article["summary"])

            fout.write(json.dumps(article, ensure_ascii=False) + "\n")

    temp.replace(source)
    return total, demoted, relevelled, cleaned_bodies


def main(argv: list[str]) -> int:
    pack = Path(argv[1]) if len(argv) > 1 else Path("content/packs/wikipedia")
    if not pack.is_dir():
        raise SystemExit(f"no pack at {pack}")
    total, demoted, relevelled, cleaned = retag(pack)
    print(f"{pack.name}: {total} articles")
    print(f"  {demoted} demoted out of Kids Mode")
    print(f"  {relevelled} Simple English levels moved {OLD_LEVEL} -> {NEW_LEVEL}")
    print(f"  {cleaned} false citation links removed "
          "(Wikipedia reference superscripts that would render as our citations)")
    print("  original kept alongside as *.orig")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
