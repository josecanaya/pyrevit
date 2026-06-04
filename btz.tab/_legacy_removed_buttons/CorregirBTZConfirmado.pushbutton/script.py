# -*- coding: utf-8 -*-
"""Completa BTZ_Description vacíos desde asociación externa confirmada."""
from __future__ import print_function

__title__ = u"Corregir\nBTZ Confirmado"
__doc__ = (
    u"Lee public/asociacion_contenedor_hijos_final_p10.csv y completa "
    u"BTZ_Description_01..80 en slots vacíos, sin borrar ni sobrescribir."
)
__author__ = u"btz.extension"

import os
import sys

_bundle_dir = os.path.dirname(os.path.abspath(__file__))
_export_dir = os.path.normpath(
    os.path.join(_bundle_dir, u"..", u"ExportarGrupos.pushbutton")
)
if _export_dir not in sys.path:
    sys.path.insert(0, _export_dir)

from pyrevit import forms, revit

from btz_modelo_export_apply import run_corregir_btz_confirmado, DRY_RUN_CORREGIR

try:
    unicode
except NameError:
    unicode = str


def main():
    doc = revit.doc
    if not doc:
        forms.alert(u"No hay documento activo.", title=u"Corregir BTZ confirmado")
        return

    log_lines = []
    try:
        r = run_corregir_btz_confirmado(doc, log_lines, dry_run=DRY_RUN_CORREGIR)
    except Exception as ex:
        try:
            msg = unicode(ex)
        except Exception:
            msg = str(ex)
        forms.alert(msg, title=u"Corregir BTZ confirmado — error")
        return

    msg = u"\n".join(
        [
            u"Corrección terminada.",
            u"",
            u"Entrada: {0}".format(r.get(u"csv_in", u"")),
            u"Resultados CSV: {0}".format(r.get(u"csv_out", u"")),
            u"Por contenedor CSV: {0}".format(r.get(u"por_contenedor_out", u"")),
            u"Debug fuente CSV: {0}".format(r.get(u"debug_fuente_out", u"")),
            u"Debug fuente por contenedor CSV: {0}".format(r.get(u"debug_por_contenedor_out", u"")),
            u"Debug sectores CSV: {0}".format(r.get(u"debug_sectores_out", u"")),
            u"Resumen TXT: {0}".format(r.get(u"txt_out", u"")),
            u"",
            u"DRY_RUN: {0}".format(u"SI" if r.get(u"dry_run") else u"NO"),
            u"Contenedores leídos: {0}".format(r.get(u"total_contenedores_leidos", 0)),
            u"Contenedores encontrados: {0}".format(r.get(u"total_contenedores_encontrados", 0)),
            u"Códigos asociados leídos: {0}".format(r.get(u"total_codigos_asociados", 0)),
            u"Ya existían: {0}".format(r.get(u"total_ya_existian", 0)),
            u"Escritos: {0}".format(r.get(u"total_escritos", 0)),
            u"Omitidos sin slot: {0}".format(r.get(u"total_omitidos_sin_slot", 0)),
            u"Elementos modificados: {0}".format(r.get(u"total_elementos_modificados", 0)),
            u"Errores: {0}".format(r.get(u"total_errores", 0)),
            u"Filas debug sectores: {0}".format(r.get(u"debug_sectores_rows", 0)),
        ]
    )
    forms.alert(msg, title=u"Corregir BTZ confirmado")


if __name__ == "__main__":
    main()
