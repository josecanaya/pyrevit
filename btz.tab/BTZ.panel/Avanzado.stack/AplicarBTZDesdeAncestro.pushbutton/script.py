# -*- coding: utf-8 -*-
"""
Botón: aplicar BTZ agrupando por ancestro_dibujado (sin IA, sin código activo).
"""
from __future__ import print_function

__title__ = u"Aplicar\nBTZ ancestro"
__doc__ = (
    u"Agrupa asignacion_automatica_sugerida.csv por ancestro_dibujado y escribe BTZ "
    u"en el elemento Revit que representa ese nodo (match dedicado / BTZ_03 / BTZ_04)."
)
__author__ = u"btz.extension"

import os
import sys

_bundle_dir = os.path.dirname(os.path.abspath(__file__))
_export_dir = os.path.normpath(
    os.path.join(_bundle_dir, u"..", u"..", u"ExportarGrupos.pushbutton")
)
if _export_dir not in sys.path:
    sys.path.insert(0, _export_dir)

from pyrevit import forms, revit

from btz_apply_from_csv_ancestor import run_apply_from_ancestor

try:
    unicode
except NameError:
    unicode = str


def main():
    doc = revit.doc
    if not doc:
        forms.alert(u"No hay documento activo.", title=u"BTZ ancestro")
        return

    log_lines = []
    try:
        r = run_apply_from_ancestor(doc, log_lines)
    except Exception as ex:
        try:
            msg = unicode(ex)
        except Exception:
            msg = str(ex)
        forms.alert(msg, title=u"BTZ ancestro — error")
        return

    msg = u"\n".join(
        [
            u"Proceso terminado (por ancestro_dibujado).",
            u"",
            u"Entrada: {0}".format(r.get(u"csv_in", u"")),
            u"Informe: {0}".format(r.get(u"csv_report", u"")),
            u"Resumen: {0}".format(r.get(u"txt_summary", u"")),
            u"",
            u"Grupos ancestro: {0}".format(r.get(u"grupos_ancestro", 0)),
            u"Match OK: {0}".format(r.get(u"aplicados", 0)),
            u"Sin match: {0}".format(r.get(u"sin_match", 0)),
            u"Múltiples elementos: {0}".format(r.get(u"multiple_match", 0)),
        ]
    )
    forms.alert(msg, title=u"BTZ ancestro")


if __name__ == "__main__":
    main()
