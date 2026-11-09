from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


class AdmissionError(ValueError):
    def __init__(self, code: str, detail: Any = None):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def require(condition: bool, code: str, detail: Any = None) -> None:
    if not condition:
        raise AdmissionError(code, detail)


def finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def sha(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def read(path: str | Path) -> Any:
    def reject(s):
        raise AdmissionError("NONFINITE_JSON", s)
    def real(s):
        v=float(s)
        if not math.isfinite(v):raise AdmissionError('NONFINITE_JSON',s)
        return v
    return json.loads(Path(path).read_text(), parse_constant=reject,parse_float=real)


def save(path: str | Path, value: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                            allow_nan=False) + "\n")


def locked(item: dict, base: str | Path = ".") -> Path:
    p = (Path(base) / item["path"]).resolve()
    require(p.is_file(), "SOURCE_MISSING", str(p))
    require(sha(p) == item["sha256"], "SOURCE_HASH", str(p))
    return p


def code_identity() -> str:
    files = sorted((ROOT / "national_idf").glob("*.py"))
    files += sorted((ROOT / "configs").glob("*.json"))
    files += sorted((ROOT / "resources").glob("*.json"))
    return digest({str(p.relative_to(ROOT)): sha(p) for p in files})


def seal(folder: Path, metadata: dict) -> dict:
    manifest = {**metadata, "files": {str(p.relative_to(folder)): sha(p)
                for p in sorted(folder.rglob("*")) if p.is_file() and
                p != folder / "MANIFEST.json"}}
    save(folder / "MANIFEST.json", manifest)
    return manifest


def verify(folder: Path) -> dict:
    m = read(folder / "MANIFEST.json")
    actual = {str(p.relative_to(folder)) for p in folder.rglob("*")
              if p.is_file() and p != folder / "MANIFEST.json"}
    require(actual == set(m["files"]), "MANIFEST_FILE_SET")
    for name, signature in m["files"].items():
        p = (folder / name).resolve()
        require(p.is_relative_to(folder.resolve()) and sha(p) == signature,
                "MANIFEST_CONTENT", name)
    return m
