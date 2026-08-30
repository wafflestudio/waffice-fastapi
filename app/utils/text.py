# Zero-width / format chars that str.strip() does not treat as whitespace (e.g. BOM).
ZERO_WIDTH_CHARS = "\u200b\u200c\u200d\u2060\ufeff\u00ad"


def normalize_text(value: str) -> str:
    """Strip surrounding whitespace and zero-width/format characters.

    Used to compare names/ids that may come from very different sources
    (roster file cells vs. form input) so that invisible characters or
    stray whitespace don't cause a false mismatch.
    """
    return value.strip().strip(ZERO_WIDTH_CHARS).strip()
