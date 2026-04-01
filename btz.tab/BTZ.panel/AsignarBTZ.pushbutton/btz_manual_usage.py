# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import csv
import codecs

from Autodesk.Revit.DB import FilteredElementCollector

try:
    unicode
except NameError:
    unicode = str


PARAM_01 = u"BTZ_Description_01"  # planta
PARAM_02 = u"BTZ_Description_02"  # sector
PARAM_03 = u"BTZ_Description_03"  # subsector


def _u(v):
    return unicode(v or u"").strip()


def _get_param_instance_or_type(doc, element, param_name):
    try:
        p = element.LookupParameter(param_name)
    except Exception:
        p = None
    if p is not None:
        return p
    try:
        tid = element.GetTypeId()
        if tid is None:
            return None
        t = doc.GetElement(tid)
        if t is None:
            return None
        return t.LookupParameter(param_name)
    except Exception:
        return None


def _param_value(doc, element, param_name):
    p = _get_param_instance_or_type(doc, element, param_name)
    if p is None:
        return u""
    try:
        s = p.AsString()
        if s is not None:
            return _u(s).upper()
    except Exception:
        pass
    try:
        s2 = p.AsValueString()
        if s2 is not None:
            return _u(s2).upper()
    except Exception:
        pass
    return u""


def scan_model_usage(doc):
    usage = {
        u"plant_counts": {},
        u"sector_counts": {},
        u"subsector_counts": {},
        u"combo_counts": {},
        u"combo_ids": {},
        u"elements_scanned": 0,
        u"elements_with_any_btz": 0,
    }
    collector = FilteredElementCollector(doc).WhereElementIsNotElementType()
    for el in collector:
        usage[u"elements_scanned"] += 1
        p1 = _param_value(doc, el, PARAM_01)
        p2 = _param_value(doc, el, PARAM_02)
        p3 = _param_value(doc, el, PARAM_03)
        if not (p1 or p2 or p3):
            continue
        usage[u"elements_with_any_btz"] += 1

        if p1:
            usage[u"plant_counts"][p1] = int(usage[u"plant_counts"].get(p1, 0) or 0) + 1
        if p2:
            usage[u"sector_counts"][p2] = int(usage[u"sector_counts"].get(p2, 0) or 0) + 1
        if p3:
            usage[u"subsector_counts"][p3] = int(usage[u"subsector_counts"].get(p3, 0) or 0) + 1

        combo = (p1, p2, p3)
        usage[u"combo_counts"][combo] = int(usage[u"combo_counts"].get(combo, 0) or 0) + 1
        if combo not in usage[u"combo_ids"]:
            usage[u"combo_ids"][combo] = []
        try:
            usage[u"combo_ids"][combo].append(unicode(el.Id.IntegerValue))
        except Exception:
            try:
                usage[u"combo_ids"][combo].append(unicode(el.Id))
            except Exception:
                pass
    return usage


def count_plant(usage, plant_code):
    return int(usage[u"plant_counts"].get(_u(plant_code).upper(), 0) or 0)


def count_sector(usage, sector_code):
    return int(usage[u"sector_counts"].get(_u(sector_code).upper(), 0) or 0)


def count_subsector(usage, subsector_code):
    return int(usage[u"subsector_counts"].get(_u(subsector_code).upper(), 0) or 0)


def used_subsectors_for_sector(usage, sector_code):
    out = []
    target = _u(sector_code).upper()
    for (p1, p2, p3), c in usage[u"combo_counts"].items():
        if p2 == target and p3:
            out.append((p3, c))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


def export_usage_report(usage, output_csv_path, output_txt_path):
    parent = os.path.dirname(os.path.abspath(output_csv_path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)

    combos = list(usage[u"combo_counts"].items())
    combos.sort(key=lambda x: (-x[1], x[0][0], x[0][1], x[0][2]))

    with codecs.open(output_csv_path, u"w", u"utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow([u"BTZ_Description_01", u"BTZ_Description_02", u"BTZ_Description_03", u"cantidad", u"element_ids"])
        for combo, count in combos:
            ids = usage[u"combo_ids"].get(combo, [])
            writer.writerow([combo[0], combo[1], combo[2], unicode(count), u";".join(ids)])

    lines = []
    lines.append(u"Resumen BTZ manual 01/02/03")
    lines.append(u"Elementos escaneados: {0}".format(usage[u"elements_scanned"]))
    lines.append(u"Elementos con BTZ 01/02/03: {0}".format(usage[u"elements_with_any_btz"]))
    lines.append(u"Combinaciones únicas: {0}".format(len(combos)))
    lines.append(u"")
    lines.append(u"PLANTA | SECTOR | SUBSECTOR | CANTIDAD")
    for combo, count in combos:
        lines.append(u"{0} | {1} | {2} | {3}".format(combo[0] or u"-", combo[1] or u"-", combo[2] or u"-", count))

    with codecs.open(output_txt_path, u"w", u"utf-8") as fp:
        fp.write(u"\n".join(lines))

    return {
        u"csv_path": output_csv_path,
        u"txt_path": output_txt_path,
        u"rows": len(combos),
    }
