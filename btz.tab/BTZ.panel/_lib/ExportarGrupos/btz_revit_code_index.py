# -*- coding: utf-8 -*-
"""
Índice codigo_activo (texto) -> lista de ElementId en el documento.
Solo lectura de parámetros; sin inferencias semánticas.

Criterio de lectura del código en Revit (orden estricto, primer valor no vacío):
1) Parámetros compartidos / de proyecto por nombre (dedicados a activo o equivalentes).
2) BuiltIn Mark (marca de instancia).
3) BuiltIn Comments (comentarios de instancia).

Si varios elementos comparten el mismo código normalizado, el índice guarda todos los IDs
para que el aplicador pueda marcar match_multiple.
"""
from __future__ import print_function

import unicodedata

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    CategoryType,
    ElementId,
    FilteredElementCollector,
)

try:
    unicode
except NameError:
    unicode = str

# Prioridad 1: nombres explícitos de “código de activo” (mismo criterio que columnas de gestión).
ACTIVO_PARAM_NAMES = [
    u"BTZ_NumeroActivo",
    u"Número Activo Principal",
    u"Número Activo",
    u"Asset Code",
    u"Codigo Activo",
    u"Código Activo",
]

# Prioridad 2: built-ins estables (solo si no hubo match por nombre).
# No se usa familia/tipo como identificador.
BUILT_IN_FALLBACK = (
    BuiltInParameter.ALL_MODEL_MARK,
    BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,
)


def _u(v):
    if v is None:
        return u""
    try:
        return unicode(v).strip()
    except Exception:
        return u""


def normalize_codigo(value):
    """Normalización mínima para comparación exacta CSV ↔ Revit."""
    s = _u(value)
    if not s:
        return u""
    s = unicodedata.normalize("NFC", s)
    return s


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


def read_activo_code_for_element(doc, element):
    """
    Devuelve (codigo_normalizado, fuente) o (u"", u"") si no hay código utilizable.
    fuente: nombre del parámetro o 'BUILTIN:Mark' / 'BUILTIN:Comments'.
    """
    for name in ACTIVO_PARAM_NAMES:
        p = _lookup_named_instance_or_type(doc, element, name)
        v = _param_display(p)
        if v:
            return normalize_codigo(v), name

    for bip in BUILT_IN_FALLBACK:
        try:
            p = element.get_Parameter(bip)
            v = _param_display(p)
            if v:
                label = u"BUILTIN:Mark" if bip == BuiltInParameter.ALL_MODEL_MARK else u"BUILTIN:Comments"
                return normalize_codigo(v), label
        except Exception:
            continue

    return u"", u""


def build_codigo_to_elements_map(doc, log_lines=None):
    """
    Recorre elementos del modelo (no tipos) con categoría de modelo.
    Retorna:
      - index: dict codigo_norm -> list[ElementId]
      - stats: dict con conteos y notas
    """
    if log_lines is None:
        log_lines = []

    index = {}
    scanned = 0
    skipped_no_cat = 0
    skipped_no_code = 0

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

        code, _src = read_activo_code_for_element(doc, el)
        if not code:
            skipped_no_code += 1
            continue

        if code not in index:
            index[code] = []
        index[code].append(el.Id)

    stats = {
        u"elements_scanned": scanned,
        u"skipped_no_category": skipped_no_cat,
        u"skipped_no_code": skipped_no_code,
        u"distinct_codes": len(index),
        u"total_indexed_ids": sum(len(v) for v in index.values()),
    }
    log_lines.append(
        u"Índice activo: escaneados={0}, sin_cat={1}, sin_código={2}, códigos_distintos={3}".format(
            scanned,
            skipped_no_cat,
            skipped_no_code,
            len(index),
        )
    )
    return index, stats


def describe_match_policy():
    """Texto fijo para documentación / resúmenes."""
    return (
        u"Match por código: se compara codigo_activo (CSV) con el primer valor no vacío obtenido "
        u"en Revit según prioridad: "
        + u", ".join(ACTIVO_PARAM_NAMES)
        + u"; si ninguno existe o está vacío: Mark; luego Comments. "
        u"Sin coincidencia por familia ni tipo."
    )
