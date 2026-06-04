# -*- coding: utf-8 -*-
"""Aplicar BTZ desde CSV confirmado por planta (public/output/{PLANTA}/...)."""
from __future__ import print_function

__title__ = u"APLICARBTZ\nCONFIRMADO"
__doc__ = (
    u"Elige planta y lee public/output/{PLANTA}/match_project_revit_confirmado.csv "
    u"(estado_match confirmado o match_ok). Resultados en la misma carpeta output."
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

from btz_modelo_export_apply import (
    discover_confirmados_por_planta,
    run_aplicar_btz_confirmado,
    summarize_confirmado_csv,
)

try:
    unicode
except NameError:
    unicode = str


def _u(value):
    if value is None:
        return u""
    try:
        return unicode(value).strip()
    except Exception:
        try:
            return unicode(str(value)).strip()
        except Exception:
            return u""


def _pick_planta_confirmada():
    """Solo plantas con CSV confirmado presente; orden P10 → TE → PP → PR."""
    all_entries = discover_confirmados_por_planta()
    available = [e for e in all_entries if e.get(u"exists")]
    order = {u"P10": 0, u"TE": 1, u"PP": 2, u"PR": 3}
    available.sort(key=lambda e: order.get(_u(e.get(u"planta")), 99))
    if not available:
        forms.alert(
            u"No hay match_project_revit_confirmado.csv en public/output/P10, TE, PP ni PR.\n\n"
            u"Ejecute primero preparar_match_project_revit.py --planta … y confirme filas.",
            title=u"Aplicar BTZ confirmado",
            warn_icon=True,
        )
        return None, None
    if len(available) == 1:
        e = available[0]
        return _u(e[u"planta"]), e[u"path"]

    labels = []
    label_to = {}
    for e in available:
        pl = _u(e[u"planta"])
        pth = e[u"path"]
        lab = u"{0} — {1}".format(pl, pth)
        labels.append(lab)
        label_to[lab] = (pl, pth)
    pick = forms.SelectFromList.show(
        labels,
        title=u"Aplicar BTZ confirmado — elegir planta",
        button_name=u"Usar este CSV",
        multiselect=False,
        width=900,
        height=520,
    )
    if not pick:
        return None, None
    pick = _u(pick)
    return label_to.get(pick, (None, None))


def main():
    doc = revit.doc
    if not doc:
        forms.alert(u"No hay documento activo.", title=u"Aplicar BTZ confirmado")
        return

    plant, csv_path = _pick_planta_confirmada()
    if not plant or not csv_path:
        return

    try:
        s = summarize_confirmado_csv(csv_path)
    except Exception as ex:
        try:
            msg = unicode(ex)
        except Exception:
            msg = str(ex)
        forms.alert(msg, title=u"Aplicar BTZ confirmado — error", warn_icon=True)
        return

    adv = u""
    if s.get(u"filas_omitidas", 0):
        adv = u"\n\nAdvertencia: {0} filas con estado_match distinto de confirmado/match_ok (no se aplicarán).".format(
            s[u"filas_omitidas"]
        )

    ok = forms.alert(
        u"\n".join(
            [
                u"Resumen antes de aplicar",
                u"",
                u"Planta: {0}".format(plant),
                u"CSV: {0}".format(csv_path),
                u"",
                u"Filas totales: {0}".format(s.get(u"filas_leidas", 0)),
                u"element_id únicos (con id en fila): {0}".format(s.get(u"element_ids_unicos", 0)),
                u"Filas aplicables (confirmado + match_ok): {0}".format(s.get(u"estados_aplicables", 0)),
                u"  · confirmado: {0}".format(s.get(u"filas_confirmado", 0)),
                u"  · match_ok: {0}".format(s.get(u"filas_match_ok", 0)),
                u"Filas omitidas por estado: {0}".format(s.get(u"filas_omitidas", 0)),
                u"",
                u"Resultados: public/output/{0}/aplicar_btz_confirmado_results.csv".format(plant),
                u"Resumen: public/output/{0}/aplicar_btz_confirmado_summary.txt".format(plant),
            ]
        )
        + adv
        + u"\n\n¿Aplicar al modelo activo?",
        title=u"Confirmar aplicación BTZ",
        yes=True,
        no=True,
    )
    if not ok:
        return

    log_lines = []
    try:
        r = run_aplicar_btz_confirmado(doc, log_lines, csv_in=csv_path, planta=plant)
    except Exception as ex:
        try:
            msg = unicode(ex)
        except Exception:
            msg = str(ex)
        forms.alert(msg, title=u"Aplicar BTZ confirmado — error")
        return

    msg = u"\n".join(
        [
            u"Proceso terminado.",
            u"",
            u"Planta: {0}".format(plant),
            u"Entrada: {0}".format(r.get(u"csv_in", u"")),
            u"Resultados CSV: {0}".format(r.get(u"csv_out", u"")),
            u"Resumen TXT: {0}".format(r.get(u"txt_out", u"")),
            u"",
            u"Filas leídas: {0}".format(r.get(u"filas_leidas", 0)),
            u"Filas aplicadas: {0}".format(r.get(u"filas_aplicadas", 0)),
            u"Filas omitidas (estado): {0}".format(r.get(u"filas_omitidas", 0)),
            u"Errores: {0}".format(r.get(u"errores", 0)),
            u"Elementos no encontrados: {0}".format(r.get(u"no_encontrados", 0)),
            u"Conflictos unique_id: {0}".format(r.get(u"conflictos_uid", 0)),
        ]
    )
    if r.get(u"compat_csv_out"):
        msg += u"\n\nCopia compatibilidad: {0}".format(r[u"compat_csv_out"])
    forms.alert(msg, title=u"Aplicar BTZ confirmado")


if __name__ == "__main__":
    main()
