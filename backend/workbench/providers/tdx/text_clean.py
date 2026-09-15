from __future__ import annotations


def clean_tdx_text(value: object, *, fallback: str = "") -> str:
    """Strip NUL padding / control junk that TDX sometimes embeds in name fields."""
    text = str(value or "")
    cleaned = "".join(ch for ch in text if ch.isprintable() and ch != "\x00").strip()
    return cleaned or fallback
