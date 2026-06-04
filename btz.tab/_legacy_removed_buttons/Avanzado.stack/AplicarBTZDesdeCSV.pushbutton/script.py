# -*- coding: utf-8 -*-
"""
Botón: aplicar BTZ desde CSV resuelto (determinista, sin IA).
"""
from __future__ import print_function

__title__ = u"Aplicar\nBTZ CSV"
__doc__ = (
    u"Lee public/asignacion_automatica_sugerida.csv y escribe BTZ_Description_01..04. "
    u"Sin webhook ni bloques."
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

from btz_apply_from_csv import run_apply_from_csv

try:
    unicode
except NameError:
    unicode = str


def main():
    doc = revit.doc
    if not doc:
        forms.alert(u"No hay documento activo.", title=u"BTZ desde CSV")
        return

    log_lines = []
    try:
        r = run_apply_from_csv(doc, log_lines)
    except Exception as ex:
        try:
            msg = unicode(ex)
        except Exception:
            msg = str(ex)
        forms.alert(msg, title=u"BTZ desde CSV — error")
        return

    msg = u"\n".join(
        [
            u"Proceso terminado.",
            u"",
            u"Entrada: {0}".format(r.get(u"csv_in", u"")),
            u"Resultados CSV: {0}".format(r.get(u"csv_out", u"")),
            u"Resumen TXT: {0}".format(r.get(u"txt_out", u"")),
            u"",
            u"Filas leídas: {0}".format(r.get(u"filas_leidas", 0)),
            u"Sin codigo_activo: {0}".format(r.get(u"filas_sin_codigo", 0)),
            u"Aplicados OK: {0}".format(r.get(u"actualizados", 0)),
            u"Sin match: {0}".format(r.get(u"sin_match", 0)),
            u"Match múltiple (no aplicado): {0}".format(r.get(u"match_multiple", 0)),
            u"Errores escritura: {0}".format(r.get(u"errores_escritura", 0)),
        ]
    )
    forms.alert(msg, title=u"BTZ desde CSV")


if __name__ == "__main__":
    main()
