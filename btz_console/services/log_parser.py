from __future__ import annotations

from pathlib import Path
from typing import List

from btz_console.services.loaders import read_last_lines


def collect_recent_logs(public_dir: Path, max_lines: int = 120) -> List[str]:
    out: List[str] = []
    for fname in ("run_log.txt", "grouping_pipeline.log"):
        p = public_dir / fname
        if not p.exists():
            continue
        out.append("===== {} =====".format(fname))
        out.extend(read_last_lines(p, max_lines=max_lines // 2))
    return out


def extract_warnings(log_lines: List[str], limit: int = 20) -> List[str]:
    keys = ("ERROR", "error", "Warning", "WARNING", "fallback", "FAILED")
    warnings = [ln for ln in log_lines if any(k in ln for k in keys)]
    return warnings[-limit:]

