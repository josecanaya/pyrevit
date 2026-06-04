# -*- coding: utf-8 -*-
"""
Importa btz_apply_webhook (mismo módulo que usa Exportar grupos).
No usa importlib/exec sobre script.py completo (evita cierre de Revit).
"""
from __future__ import print_function

__title__ = u"Automático"
__doc__ = (
    u"Aplica en el modelo los BTZ sugeridos guardados en public/webhook_response.json. "
    u"Antes: «Exportar grupos» (export + n8n)."
)
__author__ = u"btz.extension"

import os
import sys

from pyrevit import forms

# Mismo directorio que ExportarGrupos.pushbutton/btz_apply_webhook.py
_EG = os.path.normpath(
    os.path.join(os.path.dirname(__file__), u"..", u"..", u"ExportarGrupos.pushbutton")
)
if _EG not in sys.path:
    sys.path.insert(0, _EG)

import btz_apply_webhook


def main():
    try:
        btz_apply_webhook.main_apply_saved_webhook_only()
    except Exception as ex:
        forms.alert(
            u"Error al aplicar:\n{0}".format(ex),
            title=__title__,
            warn_icon=True,
        )


if __name__ == u"__main__":
    main()
