from __future__ import annotations

import re

from workbench.storage.meta_store import MetaStore

_PREFIXED = re.compile(r"^(SH|SZ|BJ)(\d{6})$")
_DIGITS = re.compile(r"^\d{6}$")


def resolve_stock_symbols(meta: MetaStore, inputs: list[str]) -> dict[str, object]:
    with meta.connect() as connection:
        rows = connection.execute("SELECT symbol, name FROM security_master").fetchall()
    names = {str(row[0]).upper(): str(row[1]) for row in rows}
    symbol_set = set(names)
    resolved: list[dict[str, str]] = []
    unresolved: list[str] = []
    seen: set[str] = set()

    for raw in inputs:
        token = str(raw).strip().upper()
        if not token:
            continue
        candidate: str | None = None
        if _PREFIXED.fullmatch(token):
            candidate = token if token in symbol_set else None
        elif _DIGITS.fullmatch(token):
            for prefix in ("SH", "SZ", "BJ"):
                symbol = f"{prefix}{token}"
                if symbol in symbol_set:
                    candidate = symbol
                    break
        else:
            code_matches = [symbol for symbol in symbol_set if token in symbol]
            name_matches = [
                symbol for symbol, name in names.items() if token in name.upper()
            ]
            matches = sorted(set(code_matches + name_matches))
            if len(matches) == 1:
                candidate = matches[0]

        if candidate and candidate not in seen:
            seen.add(candidate)
            resolved.append({"symbol": candidate, "name": names[candidate]})
        else:
            unresolved.append(str(raw).strip())

    return {"resolved": resolved, "unresolved": unresolved}
