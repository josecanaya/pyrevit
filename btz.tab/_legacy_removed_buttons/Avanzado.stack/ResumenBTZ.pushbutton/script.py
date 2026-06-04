# -*- coding: utf-8 -*-
"""
OPTIONAL: agrupa public/_optional/revit_btz_actual.csv en
public/_optional/revit_btz_resumen.csv (sin IA).
"""
from __future__ import print_function

__title__ = u"Resumen\nBTZ"
__doc__ = (
    u"Lee public/revit_btz_actual.csv y escribe public/revit_btz_resumen.csv "
    u"(conteos por combinación BTZ, orden descendente)."
)
__author__ = u"btz.extension"

import os
import sys
import csv
import codecs
from collections import Counter

from pyrevit import forms

_bundle_dir = os.path.dirname(os.path.abspath(__file__))
_export_dir = os.path.normpath(
    os.path.join(_bundle_dir, u"..", u"..", u"ExportarGrupos.pushbutton")
)
if _export_dir not in sys.path:
    sys.path.insert(0, _export_dir)

from btz_apply_webhook import _ensure_public_dir
from btz_paths import get_public_file

SRC = get_public_file(u"revit_btz_actual.csv", u"optional", fallback=True)
OUT = get_public_file(u"revit_btz_resumen.csv", u"optional", fallback=False)

HEADER_OUT = [u"btz_01", u"btz_02", u"btz_03", u"btz_04", u"cantidad_elementos"]

COL_KEYS = [u"btz_01", u"btz_02", u"btz_03", u"btz_04"]


def _u(v):
    if v is None:
        return u""
    try:
        return unicode(v).strip()
    except Exception:
        return u""


def _row_key(row):
    return tuple(_u(row.get(k, u"")) for k in COL_KEYS)


def main():
    _ensure_public_dir()

    if not os.path.isfile(SRC):
        forms.alert(
            u"No existe el archivo fuente:\n{0}\n\n"
            u"Ejecutá primero «Exportar BTZ actual».".format(SRC),
            title=u"BTZ resumen",
        )
        return

    counts = Counter()
    try:
        with codecs.open(SRC, u"r", encoding=u"utf-8-sig") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                if not row:
                    continue
                counts[_row_key(row)] += 1
    except Exception as ex:
        forms.alert(
            u"No se pudo leer el CSV.\n\n{0}".format(ex), title=u"BTZ resumen"
        )
        return

    ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0]))

    try:
        with codecs.open(OUT, u"w", encoding=u"utf-8-sig") as fp:
            w = csv.writer(fp, lineterminator=u"\n")
            w.writerow(HEADER_OUT)
            for key, n in ordered:
                w.writerow(list(key) + [n])
    except Exception as ex:
        forms.alert(
            u"No se pudo escribir el resumen.\n\n{0}".format(ex), title=u"BTZ resumen"
        )
        return

    forms.alert(
        u"Listo: {0}\nCombinaciones: {1}".format(OUT, len(ordered)),
        title=u"BTZ resumen",
    )


if __name__ == "__main__":
    main()
