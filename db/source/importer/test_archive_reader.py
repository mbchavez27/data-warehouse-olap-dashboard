"""Pytest mirrors of db/source/importer/archive-reader.test.js.

The JS suite needed a real tar subprocess and guarded a close-before-consume
race. The Python reader uses stdlib zipfile with sequential reads, so that
race cannot occur: tests assert content fidelity instead, including unicode
split across tiny chunks.
"""

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_reader import (
    iter_archive_bytes,
    iter_archive_text,
    list_archive_entries,
    match_entries,
)


@pytest.fixture()
def tiny_archive(tmp_path):
    archive = tmp_path / "tiny.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/tiny.sql", "INSERT INTO `Tiny` VALUES (1,'ok');\n")
        zf.writestr("other.txt", "unrelated\n")
    return str(archive)


def test_lists_entries_in_stored_order(tiny_archive):
    assert list_archive_entries(tiny_archive) == ["nested/tiny.sql", "other.txt"]


def test_reads_entry_bytes_verbatim(tiny_archive):
    data = b"".join(iter_archive_bytes(tiny_archive, "nested/tiny.sql"))

    assert b"INSERT INTO `Tiny`" in data
    assert data.endswith(b";\n")


def test_reads_entry_through_directory_prefix(tiny_archive):
    matches = match_entries(
        list_archive_entries(tiny_archive), {"Tiny": "tiny.sql"}
    )

    assert matches == {"Tiny": "nested/tiny.sql"}


def test_match_entries_rejects_zero_or_multiple_hits(tiny_archive):
    with pytest.raises(ValueError, match="missing.sql.*found 0"):
        match_entries(list_archive_entries(tiny_archive), {"Missing": "missing.sql"})


def test_missing_entry_raises_extract_error(tiny_archive):
    with pytest.raises(ValueError, match="could not extract"):
        b"".join(iter_archive_bytes(tiny_archive, "nope.sql"))


def test_text_decoder_survives_multibyte_splits(tmp_path):
    archive = tmp_path / "unicode.zip"
    body = "INSERT INTO `Users` VALUES (100,'José María','ok');\n"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("faker_Users.sql", body)

    # 3-byte chunks guarantee multibyte characters straddle fragments.
    text = "".join(iter_archive_text(str(archive), "faker_Users.sql", chunk_size=3))

    assert text == body
    assert "José María" in text
