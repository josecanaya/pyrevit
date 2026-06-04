# -*- coding: utf-8 -*-
"""
Metadatos adicionales por elemento (CSV + enriquecimiento blocks / LLM).

Objetivo: más señal semántica por instancia (comentarios, marcas, uso estructural,
OmniClass, workset, host, etc.) sin cambiar group_key ni romper exports existentes:
solo se agregan columnas nuevas al final del bloque base (antes de BTZ_*).
"""
from __future__ import print_function

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    ElementId,
    FamilyInstance,
    BuiltInParameter,
    WorksetId,
)

try:
    unicode
except NameError:
    unicode = str

# Parámetros extra por nombre (compartidos o de proyecto). Añadir aquí según el modelo.
EXTRA_PARAM_NAMES_BY_NAME = (
    # u"Ejemplo_Parametro_Proyecto",
)


def _first_bip(*candidates):
    """Revit: algunos BuiltInParameter cambian nombre entre versiones."""
    for name in candidates:
        bip = getattr(BuiltInParameter, name, None)
        if bip is not None:
            return bip
    return None


# (columna_csv, BuiltInParameter o None, modo) — None = rellenar con lógica aparte (workset/host)
_RAW_BIP_FIELD_SPECS = [
    (u"comments", _first_bip(u"ALL_MODEL_INSTANCE_COMMENTS"), u"instance"),
    (u"mark", _first_bip(u"ALL_MODEL_MARK"), u"instance"),
    (u"keynote", _first_bip(u"KEYNOTE_PARAM"), u"merged"),
    (u"type_comments", _first_bip(u"ALL_MODEL_TYPE_COMMENTS"), u"type"),
    (u"type_description", _first_bip(u"ALL_MODEL_DESCRIPTION"), u"type"),
    (u"type_mark", _first_bip(u"ALL_MODEL_TYPE_MARK"), u"type"),
    (u"structural_usage", _first_bip(u"STRUCTURAL_USAGE_PARAM"), u"merged"),
    (u"structural_material", _first_bip(u"STRUCTURAL_MATERIAL_PARAM"), u"merged"),
    (u"uniformat_code", _first_bip(u"UNIFORMAT_CODE"), u"merged"),
    (
        u"uniformat_description",
        _first_bip(u"UNIFORMAT_DESCRIPTION", u"UNIFORMAT_DESCRIPTION_KEY"),
        u"merged",
    ),
]

# Solo entradas con parámetro resuelto (evita fallos entre versiones).
ELEMENT_EXTRA_BIP_FIELDS = [
    (col, bip, mode) for col, bip, mode in _RAW_BIP_FIELD_SPECS if bip is not None
]

# Columnas base exportadas (orden estable) + parámetros por nombre de proyecto.
SEMANTIC_BASE_COLUMNS = (
    u"comments",
    u"mark",
    u"keynote",
    u"type_comments",
    u"type_description",
    u"type_mark",
    u"structural_usage",
    u"structural_material",
    u"uniformat_code",
    u"uniformat_description",
    u"workset",
    u"host_category",
)

SEMANTIC_CSV_COLUMNS = SEMANTIC_BASE_COLUMNS + EXTRA_PARAM_NAMES_BY_NAME


def _parameter_value_display(param):
    if param is None or not param.HasValue:
        return u""
    try:
        st = param.AsString()
        if st is not None and unicode(st).strip():
            return unicode(st)
    except Exception:
        pass
    try:
        vs = param.AsValueString()
        if vs is not None and unicode(vs).strip():
            return unicode(vs)
    except Exception:
        pass
    return u""


def _builtin_on_element(el, bip):
    if el is None or bip is None:
        return u""
    try:
        p = el.get_Parameter(bip)
        return _parameter_value_display(p)
    except Exception:
        return u""


def _workset_name(doc, el):
    try:
        ws_id = el.WorksetId
        if ws_id is None or ws_id == WorksetId.InvalidWorksetId:
            return u""
        wst = doc.GetWorksetTable()
        ws = wst.GetWorkset(ws_id)
        if ws is not None:
            return unicode(ws.Name or u"")
    except Exception:
        pass
    return u""


def _host_category_name(el):
    if not isinstance(el, FamilyInstance):
        return u""
    try:
        h = el.Host
        if h is not None and h.Category is not None:
            return unicode(h.Category.Name or u"")
    except Exception:
        pass
    return u""


def _param_by_name(el, name):
    if not el or not name:
        return u""
    try:
        p = el.LookupParameter(name)
        return _parameter_value_display(p)
    except Exception:
        return u""


def collect_extra_metadata_for_element(doc, el):
    """
    Devuelve dict con claves en SEMANTIC_CSV_COLUMNS (vacío si el BIP no aplica a la categoría).
    """
    tid = el.GetTypeId()
    et = None
    if tid and tid != ElementId.InvalidElementId:
        et = doc.GetElement(tid)

    out = {k: u"" for k in SEMANTIC_CSV_COLUMNS}

    for col, bip, mode in ELEMENT_EXTRA_BIP_FIELDS:
        val = u""
        if mode == u"instance":
            val = _builtin_on_element(el, bip)
        elif mode == u"type":
            val = _builtin_on_element(et, bip) if et is not None else u""
        elif mode == u"merged":
            val = _builtin_on_element(el, bip)
            if not val and et is not None:
                val = _builtin_on_element(et, bip)
        if col in out:
            out[col] = val

    out[u"workset"] = _workset_name(doc, el)
    out[u"host_category"] = _host_category_name(el)

    for pname in EXTRA_PARAM_NAMES_BY_NAME:
        pn = unicode(pname).strip()
        if not pn:
            continue
        v = _param_by_name(el, pn)
        if not v and et is not None:
            v = _param_by_name(et, pn)
        out[pn] = v

    return out


def semantic_keys_for_blob():
    """Claves que entran en el texto agregado para blocks (sin duplicar BTZ)."""
    return list(SEMANTIC_CSV_COLUMNS)


def aggregate_semantic_text(element_rows_subset, keys):
    """Un valor distinto por campo, concatenados — refuerza el match con blocks."""
    parts = []
    seen = set()
    for r in element_rows_subset:
        for k in keys:
            v = (r.get(k) or u"").strip()
            if not v:
                continue
            key = (k, v)
            if key in seen:
                continue
            seen.add(key)
            parts.append(v)
    return u" ".join(parts)


def unique_values_by_column(element_rows_subset, keys, max_per_col=25):
    """Resumen para payload enriquecido (valores distintos por columna)."""
    out = {}
    for k in keys:
        vals = set()
        for r in element_rows_subset:
            v = (r.get(k) or u"").strip()
            if v:
                vals.add(v)
        if vals:
            out[k] = sorted(vals, key=lambda x: x.lower())[:max_per_col]
    return out
