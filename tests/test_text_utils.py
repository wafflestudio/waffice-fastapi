from app.utils.text import normalize_text


def test_normalize_text_strips_surrounding_whitespace():
    assert normalize_text("  홍길동  ") == "홍길동"


def test_normalize_text_strips_zero_width_and_bom_chars():
    assert normalize_text("​홍길동﻿") == "홍길동"


def test_normalize_text_strips_whitespace_around_zero_width_chars():
    assert normalize_text(" ​ 홍길동 ​ ") == "홍길동"


def test_normalize_text_all_zero_width_normalizes_to_empty():
    assert normalize_text("​‌‍") == ""


def test_normalize_text_leaves_internal_whitespace_untouched():
    assert normalize_text("  홍 길동  ") == "홍 길동"


def test_normalize_text_noop_on_already_clean_value():
    assert normalize_text("홍길동") == "홍길동"
