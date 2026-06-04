# -*- coding: utf-8 -*-
"""Exportar modelo BTZ a CSV intermedio (solo lectura, sin matching)."""
from __future__ import print_function

__title__ = u"EXPORTAR\nMODELO"
__doc__ = (
    u"Genera exports de activos, todo_modelo, P10, con BTZ, por planta e inconsistencias "
    u"y modelo_btz_export_summary.txt. "
    u"No modifica el modelo ni ejecuta matching."
)
__author__ = u"btz.extension"

import os
import sys

_bundle_dir = os.path.dirname(os.path.abspath(__file__))
_export_dir = os.path.normpath(
    os.path.join(_bundle_dir, u"..", u"_lib", u"ExportarGrupos")
)
if _export_dir not in sys.path:
    sys.path.insert(0, _export_dir)

from pyrevit import forms, revit

from btz_modelo_export_apply import run_export_modelo_btz

try:
    unicode
except NameError:
    unicode = str


def main():
    doc = revit.doc
    if not doc:
        forms.alert(u"No hay documento activo.", title=u"Exportar Modelo BTZ")
        return

    log_lines = []
    try:
        r = run_export_modelo_btz(doc, log_lines)
    except Exception as ex:
        try:
            msg = unicode(ex)
        except Exception:
            msg = str(ex)
        forms.alert(msg, title=u"Exportar Modelo BTZ — error")
        return

    msg = u"\n".join(
        [
            u"Exportación terminada.",
            u"",
            u"CSV activos: {0}".format(r.get(u"csv_activos_out", u"")),
            u"CSV todo_modelo: {0}".format(r.get(u"csv_todo_modelo_out", u"")),
            u"CSV P10 activos: {0}".format(r.get(u"csv_p10_out", u"")),
            u"CSV PP activos: {0}".format(r.get(u"csv_pp_out", u"")),
            u"CSV TE activos: {0}".format(r.get(u"csv_te_out", u"")),
            u"CSV PR activos: {0}".format(r.get(u"csv_pr_out", u"")),
            u"CSV con BTZ activos: {0}".format(r.get(u"csv_con_btz_out", u"")),
            u"CSV por planta: {0}".format(r.get(u"csv_por_planta_out", u"")),
            u"CSV inconsistencias: {0}".format(r.get(u"csv_inconsistencias_out", u"")),
            u"Resumen: {0}".format(r.get(u"summary_out", u"")),
            u"",
            u"Escaneados antes de filtros: {0}".format(r.get(u"total_before_filters", 0)),
            u"Exportados en todo_modelo: {0}".format(r.get(u"total_todo_modelo", 0)),
            u"Exportados en activos: {0}".format(r.get(u"total_activos", 0)),
            u"Con BTZ en activos: {0}".format(r.get(u"con_btz", 0)),
            u"P10 en activos: {0}".format(r.get(u"p10", 0)),
            u"PP en activos: {0}".format(r.get(u"pp", 0)),
            u"TE en activos: {0}".format(r.get(u"te", 0)),
            u"PR en activos: {0}".format(r.get(u"pr", 0)),
            u"P10 en todo_modelo: {0}".format(r.get(u"p10_todo_modelo", 0)),
            u"Inconsistencias: {0}".format(r.get(u"inconsistencias", 0)),
        ]
    )
    forms.alert(msg, title=u"Exportar Modelo BTZ")


if __name__ == "__main__":
    main()
