"""Stream a single entry out of the dataset ZIP using stdlib zipfile.

Replaces db/source/importer/archive-reader.js (``tar -xOf`` subprocess).
Because the archive is a ZIP, no external ``tar``/bsdtar binary is needed,
which also removes that prerequisite on Windows. Reads are sequential, so
the close-before-consume race the JS reader guarded against cannot occur.
"""

from __future__ import annotations

import codecs
import zipfile
from typing import Dict, Iterator, List


def list_archive_entries(archive_path: str) -> List[str]:
    """Return every entry name in the archive, in stored order."""
    with zipfile.ZipFile(archive_path) as archive:
        return archive.namelist()


def match_entries(
    entries: List[str], wanted: Dict[str, str]
) -> Dict[str, str]:
    """Map each logical name to its exactly-one matching archive entry.

    ``wanted`` maps logical name -> expected basename (tolerates the
    ``Dump20250923/`` directory prefix inside the official archive).
    Mirrors ``matchEntries`` in cli.js, including the strictness.
    """
    import posixpath

    matches: Dict[str, str] = {}
    for logical, filename in wanted.items():
        found = [
            entry
            for entry in entries
            if posixpath.basename(entry.replace("\\", "/")) == filename
        ]
        if len(found) != 1:
            raise ValueError(
                f"{filename}: expected exactly one archive entry, "
                f"found {len(found)}"
            )
        matches[logical] = found[0]
    return matches


def iter_archive_bytes(
    archive_path: str, entry_name: str, chunk_size: int = 65536
) -> Iterator[bytes]:
    """Yield raw bytes of one archive entry in ``chunk_size`` fragments."""
    with zipfile.ZipFile(archive_path) as archive:
        try:
            member = archive.open(entry_name)
        except KeyError as exc:
            raise ValueError(f"could not extract {entry_name}: not in archive") from exc
        with member:
            while True:
                chunk = member.read(chunk_size)
                if not chunk:
                    break
                yield chunk


def iter_archive_text(
    archive_path: str, entry_name: str, chunk_size: int = 65536
) -> Iterator[str]:
    """Yield decoded text fragments for one archive entry.

    Decodes with an incremental UTF-8 decoder so multibyte characters split
    across chunk boundaries survive intact, mirroring Node's
    ``readable.setEncoding('utf8')`` in the JS reader.
    """
    decoder = codecs.getincrementaldecoder("utf-8")()
    for chunk in iter_archive_bytes(archive_path, entry_name, chunk_size):
        text = decoder.decode(chunk)
        if text:
            yield text
    tail = decoder.decode(b"", final=True)
    if tail:
        yield tail
