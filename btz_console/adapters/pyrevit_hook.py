from __future__ import annotations

from pathlib import Path
from typing import List


def build_launch_command(public_dir: Path) -> List[str]:
    """
    Hook de integración futura con pyRevit:
    devuelve comando sugerido para abrir BTZ Console con ruta específica.
    """
    return ["python", "-m", "btz_console.main", "--public-dir", str(public_dir)]

