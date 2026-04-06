# -*- coding: utf-8 -*-
"""
Aplicar BTZ desde public/asociacion_por_ancestro_dibujado.csv (un nodo por fila).
"""
from __future__ import print_function

__title__ = u"Aplicar\nBTZ (nodo)"
__doc__ = (
    u"Lee asociacion_por_ancestro_dibujado.csv y aplica BTZ_Description_01..04 "
    u"por match exacto (BTZ_03 → BTZ_04 → … → Comments)."
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

from btz_apply_by_ancestro_csv import run_apply_by_ancestro_csv

try:
    unicode
except NameError:
    unicode = str


def main():
    doc = revit.doc
    if not doc:
        forms.alert(u"No hay documento activo.", title=u"BTZ por ancestro")
        return

    log_lines = []
    try:
        r = run_apply_by_ancestro_csv(doc, log_lines)
    except Exception as ex:
        try:
            msg = unicode(ex)
        except Exception:
            msg = str(ex)
        forms.alert(msg, title=u"BTZ por ancestro — error")
        return

    msg = u"\n".join(
        [
            u"Listo.",
            u"",
            u"Entrada: {0}".format(r.get(u"path_in", u"")),
            u"Resultados: {0}".format(r.get(u"path_out", u"")),
            u"Resumen: {0}".format(r.get(u"path_sum", u"")),
            u"",
            u"Nodos procesados: {0}".format(r.get(u"nodos_procesados", 0)),
            u"Con match: {0}".format(r.get(u"nodos_con_match", 0)),
            u"Sin match: {0}".format(r.get(u"nodos_sin_match", 0)),
            u"Múltiples elementos: {0}".format(r.get(u"nodos_multiple", 0)),
        ]
    )
    forms.alert(msg, title=u"BTZ por ancestro")


if __name__ == "__main__":
    main()
