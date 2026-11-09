"""Small IDF reader/writer and version-bound field access; no eppy dependency."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from .common import require


def parse(text: str) -> list[list[str]]:
    rows, row, token = [], [], []
    quoted, comment = False, False
    for ch in text:
        if comment:
            if ch in "\r\n": comment = False
            continue
        if ch == '"':
            quoted = not quoted
            token.append(ch)
        elif ch == "!" and not quoted:
            comment = True
        elif ch in ",;" and not quoted:
            row.append("".join(token).strip().strip('"'))
            token = []
            if ch == ";":
                if row[0]: rows.append(row)
                row = []
        else:
            token.append(ch)
    require(not quoted and not row and not "".join(token).strip(), "IDF_UNTERMINATED")
    return rows


def render(rows: list[list]) -> str:
    def fmt(v):
        if isinstance(v, float): return f"{v:.12g}"
        text = str(v)
        return '"' + text + '"' if any(c in text for c in ",;!") else text
    return "\n\n".join(",\n  ".join(fmt(v) for v in row) + ";" for row in rows) + "\n"


class Fields:
    def __init__(self, schema: str | Path):
        self.schema = json.loads(Path(schema).read_text())

    def names(self, kind: str) -> list[str]:
        return self.schema["properties"][kind]["legacy_idd"]["fields"]

    def index(self, kind: str, name: str) -> int:
        return 1 + self.names(kind).index(name)

    def get(self, row: list, name: str, default=""):
        i = self.index(row[0], name)
        return row[i] if i < len(row) and row[i] != "" else default

    def set(self, row: list, name: str, value) -> None:
        i = self.index(row[0], name)
        row.extend([""] * max(0, i + 1 - len(row)))
        row[i] = value

    def obj(self, kind: str, **values) -> list:
        row = [kind]
        for key, value in values.items(): self.set(row, key, value)
        return row


def objects(rows, kind):
    return [r for r in rows if r[0].lower() == kind.lower()]


def one(rows, kind):
    result = objects(rows, kind)
    require(len(result) == 1, "IDF_OBJECT_CARDINALITY", [kind, len(result)])
    return result[0]


def replace_type(rows, kind, new):
    return [copy.deepcopy(r) for r in rows if r[0].lower() != kind.lower()] + new
