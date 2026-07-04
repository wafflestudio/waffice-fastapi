from __future__ import annotations

import io
import re
import zipfile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import ValidationError

from app.exceptions import (
    EmptyRosterError,
    InvalidRosterFileError,
    RosterTooLargeError,
)
from app.schemas.user import TempMemberInput

MAX_ROWS = 2000

# Header aliases (normalized: lowercased, non-alphanumeric/non-Hangul stripped).
_NAME_HEADERS = {"이름", "성명", "성함", "name"}
_STUDENT_ID_HEADERS = {"학번", "studentid", "sid", "학번sid"}


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


def parse_member_roster(
    content: bytes,
) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """
    Parse an .xlsx member roster into (valid_rows, invalid_rows).

    The first row is the header; the name and student_id columns are located by
    header text (case-insensitive, Korean/English aliases, column order agnostic):
      - name:       이름 / 성명 / 성함 / name
      - student_id: 학번 / student_id / sid

    Returns:
      valid_rows:   list of (name, student_id), normalized via TempMemberInput.
      invalid_rows: list of (name, student_id, "invalid") for rows whose name or
                    student_id is blank/invalid — skipped, not fatal.

    Raises:
      InvalidRosterFileError (400): unreadable file, or missing name/student_id column.
      EmptyRosterError (422): header present but no data rows.
      RosterTooLargeError (400): more than MAX_ROWS data rows.
    """
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError):
        raise InvalidRosterFileError(
            "Could not read the uploaded file as an .xlsx spreadsheet."
        )

    try:
        rows = workbook.active.iter_rows(values_only=True)

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

        if name_idx is None or student_id_idx is None:
            raise InvalidRosterFileError(
                "Header must contain a name column (이름/성명/name) and a "
                "student_id column (학번/student_id/sid)."
            )

        valid: list[tuple[str, str]] = []
        invalid: list[tuple[str, str, str]] = []
        count = 0
        for row in rows:
            raw_name = _cell_to_str(row[name_idx]) if name_idx < len(row) else ""
            raw_sid = (
                _cell_to_str(row[student_id_idx]) if student_id_idx < len(row) else ""
            )
            if not raw_name and not raw_sid:
                continue  # fully-empty spacer row
            count += 1
            if count > MAX_ROWS:
                raise RosterTooLargeError()
            try:
                member = TempMemberInput(name=raw_name, student_id=raw_sid)
                valid.append((member.name, member.student_id))
            except ValidationError:
                invalid.append((raw_name, raw_sid, "invalid"))

        if not valid and not invalid:
            raise EmptyRosterError()

        return valid, invalid
    finally:
        workbook.close()
