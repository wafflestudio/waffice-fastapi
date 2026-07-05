from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import Iterator, Sequence

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.exceptions import EmptyRosterError, InvalidRosterFileError, RosterTooLargeError

MAX_ROWS = 2000
_MAX_NAME = 100
_MAX_STUDENT_ID = 50

# Header aliases (normalized: lowercased, non-alphanumeric/non-Hangul stripped).
_NAME_HEADERS = {"이름", "성명", "성함", "name"}
_STUDENT_ID_HEADERS = {"학번", "studentid", "sid", "학번sid"}

# Zero-width / format chars that str.strip() does not treat as whitespace (e.g. BOM).
_ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff\u00ad"


def _norm_header(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"[^0-9a-z가-힣]", "", str(value).strip().lower())


def _cell_to_str(value: object) -> str:
    """Render a cell as a trimmed string (int/float ids -> digits, not '2021.0')."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def _normalize(value: str) -> str:
    return value.strip().strip(_ZERO_WIDTH).strip()


def _xlsx_rows(content: bytes) -> Iterator[Sequence[object]]:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError):
        raise InvalidRosterFileError()
    try:
        yield from workbook.active.iter_rows(values_only=True)
    finally:
        workbook.close()


def _csv_rows(content: bytes) -> Iterator[Sequence[object]]:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            text = None
    if text is None:
        raise InvalidRosterFileError()
    yield from csv.reader(io.StringIO(text))


def parse_member_roster(
    content: bytes,
    filename: str,
) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """
    Parse an .xlsx or .csv member roster into (valid_rows, invalid_rows).

    The file type is chosen by the filename extension (.xlsx or .csv); any other
    extension is rejected. The first row is the header; the name and student_id
    columns are located by header text (case-insensitive, Korean/English aliases,
    column order agnostic):
      - name:       이름 / 성명 / name
      - student_id: 학번 / student_id / sid

    Returns:
      valid_rows:   list of (name, student_id), normalized.
      invalid_rows: list of (name, student_id, reason) for rows missing a field —
                    reason is "missing_name", "missing_student_id", or "invalid"
                    (over-length). Skipped, not fatal.

    Raises:
      InvalidRosterFileError (400): unsupported extension, unreadable file, or
                                    missing name/student_id header.
      EmptyRosterError (422): header present but no data rows.
      RosterTooLargeError (400): more than MAX_ROWS data rows.
    """
    name = (filename or "").lower()
    if name.endswith(".csv"):
        rows = _csv_rows(content)
    elif name.endswith(".xlsx"):
        rows = _xlsx_rows(content)
    else:
        raise InvalidRosterFileError()

    try:
        header = next(rows)
    except StopIteration:
        raise EmptyRosterError()

    name_idx = student_id_idx = None
    for index, cell in enumerate(header or ()):
        key = _norm_header(cell)
        if name_idx is None and key in _NAME_HEADERS:
            name_idx = index
        if student_id_idx is None and key in _STUDENT_ID_HEADERS:
            student_id_idx = index

    if name_idx is None:
        raise InvalidRosterFileError("이름 헤더를 찾을 수 없습니다.")
    if student_id_idx is None:
        raise InvalidRosterFileError("학번 헤더를 찾을 수 없습니다.")

    valid: list[tuple[str, str]] = []
    invalid: list[tuple[str, str, str]] = []
    count = 0
    for row in rows:
        name = _normalize(_cell_to_str(row[name_idx]) if name_idx < len(row) else "")
        student_id = _normalize(
            _cell_to_str(row[student_id_idx]) if student_id_idx < len(row) else ""
        )
        if not name and not student_id:
            continue  # fully-empty spacer row
        count += 1
        if count > MAX_ROWS:
            raise RosterTooLargeError()

        if not student_id:
            invalid.append((name, student_id, "missing_student_id"))
        elif not name:
            invalid.append((name, student_id, "missing_name"))
        elif len(name) > _MAX_NAME or len(student_id) > _MAX_STUDENT_ID:
            invalid.append((name, student_id, "invalid"))
        else:
            valid.append((name, student_id))

    if not valid and not invalid:
        raise EmptyRosterError()

    return valid, invalid
