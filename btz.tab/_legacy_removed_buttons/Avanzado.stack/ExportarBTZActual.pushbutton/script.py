# -*- coding: utf-8 -*-
"""
Exporta estado BTZ actual del modelo a CSV (sin IA, sin agrupar).
"""
from __future__ import print_function

__title__ = u"Exportar\nBTZ actual"
__doc__ = (
    u"OPTIONAL: escribe public/_optional/revit_btz_actual.csv "
    u"con elementos que tengan BTZ_02 o BTZ_03."
)
__author__ = u"btz.extension"

import os
import sys
import csv
import codecs

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    ElementId,
    FamilySymbol,
    FilteredElementCollector,
    BuiltInParameter,
)

from pyrevit import forms, revit

try:
    unicode
except NameError:
    unicode = str

_bundle_dir = os.path.dirname(os.path.abspath(__file__))
_export_dir = os.path.normpath(
    os.path.join(_bundle_dir, u"..", u"..", u"ExportarGrupos.pushbutton")
)
if _export_dir not in sys.path:
    sys.path.insert(0, _export_dir)

from btz_apply_webhook import _ensure_public_dir
from btz_paths import get_public_file

PARAM_01 = u"BTZ_Description_01"
PARAM_02 = u"BTZ_Description_02"
PARAM_03 = u"BTZ_Description_03"
PARAM_04 = u"BTZ_Description_04"

OUT_CSV = get_public_file(u"revit_btz_actual.csv", u"optional", fallback=False)

CSV_HEADER = [
    u"element_id",
    u"category",
    u"family",
    u"type",
    u"btz_01",
    u"btz_02",
    u"btz_03",
    u"btz_04",
]


def _u(v):
    if v is None:
        return u""
    try:
        return unicode(v).strip()
    except Exception:
        return u""


def _element_id_str(eid):
    try:
        if hasattr(eid, u"Value"):
            return unicode(int(eid.Value))
        return unicode(int(eid.IntegerValue))
    except Exception:
        return u""


def _param_display(param):
    if param is None or not param.HasValue:
        return u""
    try:
        s = param.AsString()
        if s is not None and _u(s):
            return _u(s)
    except Exception:
        pass
    try:
        vs = param.AsValueString()
        if vs is not None and _u(vs):
            return _u(vs)
    except Exception:
        pass
    return u""


def _get_param_instance_or_type(doc, element, param_name):
    try:
        p = element.LookupParameter(param_name)
    except Exception:
        p = None
    if p is not None:
        return p
    try:
        tid = element.GetTypeId()
        if tid is None or tid == ElementId.InvalidElementId:
            return None
        t = doc.GetElement(tid)
        if t is None:
            return None
        return t.LookupParameter(param_name)
    except Exception:
        return None


def _safe_type_display_name(elem_type):
    if elem_type is None:
        return u""
    for bip in (
        BuiltInParameter.SYMBOL_NAME_PARAM,
        BuiltInParameter.ALL_MODEL_TYPE_NAME,
    ):
        try:
            p = elem_type.get_Parameter(bip)
            if p is not None and p.HasValue:
                s = p.AsString()
                if s:
                    return unicode(s)
        except Exception:
            pass
    try:
        n = elem_type.Name
        if n is not None:
            return unicode(n)
    except Exception:
        pass
    return u""


def _safe_family_display_name(fam):
    if fam is None:
        return u""
    try:
        n = fam.Name
        if n is not None:
            return unicode(n)
    except Exception:
        pass
    try:
        p = fam.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
        if p is not None and p.HasValue:
            s = p.AsString()
            if s:
                return unicode(s)
    except Exception:
        pass
    return u""


def _safe_category_name(element):
    try:
        cat = element.Category
        return unicode(cat.Name) if cat is not None else u""
    except Exception:
        return u""


def _family_and_type_names(doc, element):
    family_name = u""
    type_name = u""
    try:
        tid = element.GetTypeId()
    except Exception:
        tid = None
    if tid and tid != ElementId.InvalidElementId:
        et = doc.GetElement(tid)
        if et is not None:
            type_name = _safe_type_display_name(et)
            if isinstance(et, FamilySymbol):
                fam = et.Family
                family_name = _safe_family_display_name(fam)
                if not family_name:
                    try:
                        p = et.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
                        if p is not None and p.HasValue:
                            family_name = _u(p.AsString() or u"")
                    except Exception:
                        pass
    return family_name, type_name


def main():
    doc = revit.doc
    if not doc:
        forms.alert(u"No hay documento activo.", title=u"BTZ export")
        return

    _ensure_public_dir()

    rows = []
    collector = FilteredElementCollector(doc).WhereElementIsNotElementType()

    for el in collector:
        try:
            p2 = _get_param_instance_or_type(doc, el, PARAM_02)
            p3 = _get_param_instance_or_type(doc, el, PARAM_03)
            v2 = _param_display(p2)
            v3 = _param_display(p3)
            if not v2 and not v3:
                continue

            eid = _element_id_str(el.Id)
            cat = _safe_category_name(el)
            fam, typ = _family_and_type_names(doc, el)
            b1 = _param_display(_get_param_instance_or_type(doc, el, PARAM_01))
            b4 = _param_display(_get_param_instance_or_type(doc, el, PARAM_04))

            rows.append([eid, cat, fam, typ, b1, v2, v3, b4])
        except Exception:
            continue

    try:
        with codecs.open(OUT_CSV, u"w", encoding=u"utf-8-sig") as fp:
            w = csv.writer(fp, lineterminator=u"\n")
            w.writerow(CSV_HEADER)
            for r in rows:
                w.writerow(r)
    except Exception as ex:
        forms.alert(
            u"No se pudo escribir el CSV.\n\n{0}".format(ex), title=u"BTZ export"
        )
        return

    forms.alert(
        u"Listo: {0}\nFilas: {1}".format(OUT_CSV, len(rows)),
        title=u"BTZ export",
    )


if __name__ == "__main__":
    main()
