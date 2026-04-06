from __future__ import annotations

from pathlib import Path


def _project_config_dir(public_dir: Path) -> Path:
    # Compatibilidad: nueva ruta en _optional; fallback a ruta legacy en raiz.
    new_dir = public_dir / "_optional" / "project_config"
    old_dir = public_dir / "project_config"
    if new_dir.exists():
        return new_dir
    if old_dir.exists():
        return old_dir
    return new_dir


def prompt_project_path(public_dir: Path) -> Path:
    return _project_config_dir(public_dir) / "prompt_project.md"


def ensure_project_prompt_file(public_dir: Path) -> Path:
    cfg_dir = _project_config_dir(public_dir)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    p = prompt_project_path(public_dir)
    if not p.exists():
        p.write_text("", encoding="utf-8")
    return p


def load_project_prompt(public_dir: Path) -> str:
    p = ensure_project_prompt_file(public_dir)
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin1"]
    for enc in encodings:
        try:
            return p.read_text(encoding=enc)
        except Exception:
            continue
    return ""


def save_project_prompt(public_dir: Path, text: str) -> Path:
    p = ensure_project_prompt_file(public_dir)
    p.write_text(text or "", encoding="utf-8")
    return p

