from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List


def _read_text(path: Path) -> str:
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin1"]
    last_error = None
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except Exception as ex:  # pragma: no cover - fallback chain
            last_error = ex
            continue
    raise ValueError("No se pudo leer archivo texto {}: {}".format(path, last_error))


def load_json(path: Path):
    return json.loads(_read_text(path))


def load_csv_rows(path: Path) -> List[Dict[str, str]]:
    raw = _read_text(path)
    sample = raw[:4096]
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,").delimiter
    except Exception:
        if sample.count(";") > sample.count(","):
            delimiter = ";"
    reader = csv.DictReader(raw.splitlines(), delimiter=delimiter)
    return [dict(r) for r in reader]


def read_last_lines(path: Path, max_lines: int = 120) -> List[str]:
    raw = _read_text(path)
    lines = raw.splitlines()
    return lines[-max_lines:]

