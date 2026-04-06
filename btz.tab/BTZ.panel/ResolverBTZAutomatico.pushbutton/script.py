# -*- coding: utf-8 -*-
"""
OFFICIAL: un solo flujo determinista (anclas Revit + CSV asociación + CSV asignación).
"""
from __future__ import print_function

__title__ = u"Resolver\nBTZAutomatico"
__doc__ = (
    u"Lee anclas ya clasificadas en el modelo, asociacion_por_ancestro_dibujado.csv "
    u"y asignacion_automatica_sugerida.csv; aplica BTZ_Description_01..04 a los activos. "
    u"Salida: public/resolver_btz_automatico_results.csv y resolver_btz_automatico_summary.txt."
)
__author__ = u"btz.extension"

import os
import sys

_bundle_dir = os.path.dirname(os.path.abspath(__file__))
_export_dir = os.path.normpath(os.path.join(_bundle_dir, u"..", u"ExportarGrupos.pushbutton"))
if _export_dir not in sys.path:
    sys.path.insert(0, _export_dir)

from pyrevit import forms, revit

from btz_resolver_automatico import run_resolver_btz_automatico

try:
    unicode
except NameError:
    unicode = str


def main():
    doc = revit.doc
    if not doc:
        forms.alert(u"No hay documento activo.", title=__title__)
        return

    log_lines = []
    try:
        r = run_resolver_btz_automatico(doc, log_lines)
    except Exception as ex:
        forms.alert(
            u"Error:\n{0}".format(ex),
            title=__title__,
            warn_icon=True,
        )
        raise

    msg = u"\n".join(log_lines[-20:]) if log_lines else unicode(r)
    forms.alert(msg, title=__title__)


if __name__ == u"__main__":
    main()
