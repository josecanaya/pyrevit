# -*- coding: utf-8 -*-
"""
Índices deterministas para emparejar ancestro_dibujado (CSV) con elementos Revit.

Orden de búsqueda (primera coincidencia no vacía gana):
1) Parámetros dedicados al nodo / ancestro (mismo nombre que columna CSV u homónimos).
2) Valor actual de BTZ_Description_03 en el elemento.
3) Valor actual de BTZ_Description_04 en el elemento.
4) Par BTZ_03 + "|" + BTZ_04 (solo si ambos tienen valor).

Sin familia, tipo ni heurísticas semánticas: solo igualdad de cadenas normalizadas (NFC + trim).
"""
from __future__ import print_function

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    CategoryType,
    ElementId,
    FilteredElementCollector,
)

from btz_revit_code_index import normalize_codigo
from btz_apply_webhook import _param_value_as_string

try:
    unicode
except NameError:
    unicode = str

# Parámetros por nombre (instancia o tipo) que identifican el nodo dibujado.
ANCESTRO_DEDICATED_PARAM_NAMES = [
    u"ancestro_dibujado",
    u"BTZ_AncestroDibujado",
    u"Nodo_Dibujado",
    u"Codigo_Nodo",
    u"Código_Nodo",
]

PARAM_BTZ = [
    u"BTZ_Description_01",
    u"BTZ_Description_02",
    u"BTZ_Description_03",
    u"BTZ_Description_04",
]


def _u(v):
    if v is None:
        return u""
    try:
        return unicode(v).strip()
    except Exception:
        return u""


def _param_display(param):
    if param is None or not param.HasValue:
        return u""
    try:
        st = param.AsString()
        if st is not None and _u(st):
            return _u(st)
    except Exception:
        pass
    try:
        vs = param.AsValueString()
        if vs is not None and _u(vs):
            return _u(vs)
    except Exception:
        pass
    return u""


def _lookup_named_instance_or_type(doc, element, param_name):
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


def _append_id(bucket, key, eid):
    if not key:
        return
    if key not in bucket:
        bucket[key] = []
    bucket[key].append(eid)


def _dedupe_ids(id_list):
    seen = set()
    out = []
    for eid in id_list:
        sk = _element_id_str(eid)
        if sk in seen:
            continue
        seen.add(sk)
        out.append(eid)
    return out


def _element_id_str(eid):
    try:
        if hasattr(eid, u"Value"):
            return unicode(int(eid.Value))
        return unicode(int(eid.IntegerValue))
    except Exception:
        return u""


def build_ancestor_maps(doc, log_lines=None):
    """
    Construye mapas clave normalizada -> lista ElementId.
    Retorna dict con:
      by_dedicated, by_btz3, by_btz4, by_btz34
    y stats.
    """
    if log_lines is None:
        log_lines = []

    by_dedicated = {}
    by_btz3 = {}
    by_btz4 = {}
    by_btz34 = {}

    scanned = 0
    skipped_no_cat = 0

    col = FilteredElementCollector(doc).WhereElementIsNotElementType()
    for el in col:
        scanned += 1
        try:
            cat = el.Category
            if cat is None:
                skipped_no_cat += 1
                continue
            if cat.CategoryType != CategoryType.Model:
                continue
        except Exception:
            skipped_no_cat += 1
            continue

        eid = el.Id

        for pname in ANCESTRO_DEDICATED_PARAM_NAMES:
            p = _lookup_named_instance_or_type(doc, el, pname)
            v = _param_display(p)
            if v:
                _append_id(by_dedicated, normalize_codigo(v), eid)

        b3 = _u(_param_value_as_string(el, PARAM_BTZ[2]))
        b4 = _u(_param_value_as_string(el, PARAM_BTZ[3]))
        if b3:
            _append_id(by_btz3, normalize_codigo(b3), eid)
        if b4:
            _append_id(by_btz4, normalize_codigo(b4), eid)
        if b3 and b4:
            pair = normalize_codigo(b3) + u"|" + normalize_codigo(b4)
            _append_id(by_btz34, pair, eid)

    for d in (by_dedicated, by_btz3, by_btz4, by_btz34):
        for k in list(d.keys()):
            d[k] = _dedupe_ids(d[k])

    stats = {
        u"elements_scanned": scanned,
        u"skipped_no_category": skipped_no_cat,
        u"keys_dedicated": len(by_dedicated),
        u"keys_btz3": len(by_btz3),
        u"keys_btz4": len(by_btz4),
        u"keys_btz34": len(by_btz34),
    }
    log_lines.append(
        u"Índice ancestro: escaneados={0}, claves dedicated={1}, btz3={2}, btz4={3}, btz34={4}".format(
            scanned,
            len(by_dedicated),
            len(by_btz3),
            len(by_btz4),
            len(by_btz34),
        )
    )

    return {
        u"by_dedicated": by_dedicated,
        u"by_btz3": by_btz3,
        u"by_btz4": by_btz4,
        u"by_btz34": by_btz34,
        u"stats": stats,
    }


def find_elements_for_ancestor_key(maps, ancestor_key):
    """
    ancestor_key: cadena ya normalizada (NFC+trim). No vacía.
    Retorna (lista ElementId, match_via) donde match_via indica el primer criterio que resolvió.
    """
    if not ancestor_key:
        return [], u""

    by_d = maps[u"by_dedicated"]
    if ancestor_key in by_d and by_d[ancestor_key]:
        return by_d[ancestor_key], u"dedicated_param"

    by3 = maps[u"by_btz3"]
    if ancestor_key in by3 and by3[ancestor_key]:
        return by3[ancestor_key], u"BTZ_Description_03"

    by4 = maps[u"by_btz4"]
    if ancestor_key in by4 and by4[ancestor_key]:
        return by4[ancestor_key], u"BTZ_Description_04"

    by34 = maps[u"by_btz34"]
    if ancestor_key in by34 and by34[ancestor_key]:
        return by34[ancestor_key], u"BTZ_Description_03+04"

    return [], u""


def describe_ancestor_match_policy():
    return (
        u"Match por ancestro_dibujado (clave normalizada). Orden: "
        u"1) parámetros dedicados {0}; "
        u"2) BTZ_Description_03; 3) BTZ_Description_04; "
        u"4) concat BTZ_03|BTZ_04. Sin inferencias por familia/tipo."
    ).format(u", ".join(ANCESTRO_DEDICATED_PARAM_NAMES))
