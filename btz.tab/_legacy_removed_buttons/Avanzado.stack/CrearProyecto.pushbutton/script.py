# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "Crear proyecto"
__doc__ = "Abre BTZ Console en la vista inicial de preparación del proyecto."
__author__ = "btz.extension"

import os
import sys
import subprocess

from pyrevit import forms


def _resolve_extension_root():
    try:
        from pyrevit import script

        bpaths = script.get_bundle_paths() or []
        for bp in bpaths:
            bp = os.path.abspath(bp)
            ext = os.path.normpath(os.path.join(bp, "..", "..", "..", ".."))
            if os.path.isdir(ext) and os.path.isdir(os.path.join(ext, "public")):
                return ext
    except Exception:
        pass
    return os.path.normpath(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    )


def main():
    ext_dir = _resolve_extension_root()
    public_dir = os.path.join(ext_dir, "public")
    if not os.path.isdir(public_dir):
        try:
            os.makedirs(public_dir)
        except Exception:
            pass

    python_exe = os.environ.get("BTZ_CONSOLE_PYTHON_EXE") or sys.executable or "python"
    cmd = [
        python_exe,
        "-m",
        "btz_console.main",
        "--public-dir",
        public_dir,
        "--section",
        "Prepare",
    ]
    try:
        subprocess.Popen(cmd, cwd=ext_dir)
    except Exception as ex:
        forms.alert(
            u"No se pudo abrir BTZ Console.\n\n{0}\n\n"
            u"Sugerencia: instalar PySide6 en el Python configurado:\n"
            u"python -m pip install PySide6".format(ex),
            title=__title__,
            warn_icon=True,
        )
        return

    forms.alert(
        u"BTZ Console abierto.\nRuta public activa:\n{0}".format(public_dir),
        title=__title__,
        warn_icon=False,
    )


if __name__ == "__main__":
    main()
