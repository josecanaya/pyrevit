# -*- coding: utf-8 -*-
from __future__ import print_function

try:
    unicode
except NameError:
    unicode = str


def _u(v):
    return unicode(v or u"").strip()


def analyze_selection_state(elements, get_current_value):
    combos = {}
    with_any = 0
    for el in elements:
        v1 = _u(get_current_value(el, u"BTZ_Description_01")).upper()
        v2 = _u(get_current_value(el, u"BTZ_Description_02")).upper()
        v3 = _u(get_current_value(el, u"BTZ_Description_03")).upper()
        v4 = _u(get_current_value(el, u"BTZ_Description_04")).upper()
        if v1 or v2 or v3 or v4:
            with_any += 1
        k = (v1, v2, v3, v4)
        combos[k] = int(combos.get(k, 0) or 0) + 1
    return {
        u"elements": len(elements),
        u"with_any": with_any,
        u"unique_combos": combos,
        u"is_mixed": len(combos) > 1,
    }


def apply_manual_hierarchy(
    elements,
    plant_code,
    sector_code,
    subsector_code,
    unit_code,
    overwrite,
    set_text_parameter,
    get_current_value,
):
    result = {
        u"modified": 0,
        u"unchanged": 0,
        u"skipped_existing": 0,
        u"errors": [],
    }
    p1 = _u(plant_code).upper()
    p2 = _u(sector_code).upper()
    p3 = _u(subsector_code).upper()
    p4 = _u(unit_code).upper()

    for el in elements:
        try:
            eid = unicode(el.Id.Value if hasattr(el.Id, 'Value') else el.Id.IntegerValue)
        except Exception:
            eid = u"?"

        c1 = _u(get_current_value(el, u"BTZ_Description_01")).upper()
        c2 = _u(get_current_value(el, u"BTZ_Description_02")).upper()
        c3 = _u(get_current_value(el, u"BTZ_Description_03")).upper()
        c4 = _u(get_current_value(el, u"BTZ_Description_04")).upper()

        if c1 == p1 and c2 == p2 and c3 == p3 and c4 == p4:
            result[u"unchanged"] += 1
            continue

        if (c1 or c2 or c3 or c4) and not overwrite:
            result[u"skipped_existing"] += 1
            continue

        ok1, err1 = set_text_parameter(el, u"BTZ_Description_01", p1)
        if not ok1:
            result[u"errors"].append(u"Id {0} BTZ_Description_01: {1}".format(eid, err1 or u"error"))
            continue
        ok2, err2 = set_text_parameter(el, u"BTZ_Description_02", p2)
        if not ok2:
            result[u"errors"].append(u"Id {0} BTZ_Description_02: {1}".format(eid, err2 or u"error"))
            continue
        ok3, err3 = set_text_parameter(el, u"BTZ_Description_03", p3)
        if not ok3:
            result[u"errors"].append(u"Id {0} BTZ_Description_03: {1}".format(eid, err3 or u"error"))
            continue
        ok4, err4 = set_text_parameter(el, u"BTZ_Description_04", p4)
        if not ok4:
            result[u"errors"].append(u"Id {0} BTZ_Description_04: {1}".format(eid, err4 or u"error"))
            continue

        result[u"modified"] += 1

    return result
