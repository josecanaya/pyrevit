# -*- coding: utf-8 -*-
"""
Aplicación BTZ por nodo (asociacion_por_ancestro_dibujado.csv).
LEGACY: flujo alternativo al resolver oficial.

Match determinista: clave CSV vs campos del elemento en orden de prioridad
(BTZ_NodoDibujado primero, luego BTZ_03/04, activos, Mark, Comments).
Sin IA, sin codigo_activo como clave.
"""
from __future__ import print_function

import codecs
import csv
import os
import unicodedata

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    CategoryType,
    ElementId,
    FilteredElementCollector,
    Transaction,
    TransactionStatus,
)

from btz_apply_webhook import (
    _ensure_public_dir,
    ensure_btz_shared_parameters,
    set_text_parameter,
)
from btz_paths import get_public_file

try:
    unicode
except NameError:
    unicode = str

CSV_NAME = u"asociacion_por_ancestro_dibujado.csv"
RESULTS_CSV = u"apply_by_ancestro_results.csv"
SUMMARY_TXT = u"apply_by_ancestro_summary.txt"

# Cabeceras obligatorias (archivo completo)
REQUIRED_COLUMNS = [
    u"ancestro_dibujado",
    u"btz_01_sugerido",
    u"btz_02_sugerido",
    u"btz_03_sugerido",
    u"btz_04_sugerido",
    u"cantidad_activos",
    u"ejemplos_activos",
]

BTZ_KEYS = [
    u"btz_01_sugerido",
    u"btz_02_sugerido",
    u"btz_03_sugerido",
    u"btz_04_sugerido",
]

PARAM_BTZ = [
    u"BTZ_Description_01",
    u"BTZ_Description_02",
    u"BTZ_Description_03",
    u"BTZ_Description_04",
]

# Parámetro dedicado (misma tupla que en MATCH_FIELDS[0]) — lectura previa al apply
SPEC_BTZ_NODO_DIBUJADO = (u"BTZ_NodoDibujado", u"shared", u"BTZ_NodoDibujado")

# Orden de prioridad para encontrar elementos por clave = ancestro_dibujado (CSV)
MATCH_FIELDS = [
    SPEC_BTZ_NODO_DIBUJADO,
    (u"BTZ_Description_03", u"shared", u"BTZ_Description_03"),
    (u"BTZ_Description_04", u"shared", u"BTZ_Description_04"),
    (u"BTZ_NumeroActivo", u"shared", u"BTZ_NumeroActivo"),
    (u"Número Activo Principal", u"shared", u"Número Activo Principal"),
    (u"Mark", u"builtin", BuiltInParameter.ALL_MODEL_MARK),
    (u"Comments", u"builtin", BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS),
]


def _u(v):
    if v is None:
        return u""
    try:
        return unicode(v).strip()
    except Exception:
        return u""


def normalize_match_key(value):
    """Trim + NFC + uppercase (comparación exacta entre CSV y Revit)."""
    s = _u(value)
    if not s:
        return u""
    s = unicodedata.normalize("NFC", s)
    return s.upper()


def _unicode_header(h):
    if h is None:
        return u""
    return unicodedata.normalize("NFC", _u(h))


def _validate_headers(fieldnames):
    if not fieldnames:
        return u"El CSV no tiene cabecera o está vacío."
    fn = [_unicode_header(x) for x in fieldnames]
    missing = [c for c in REQUIRED_COLUMNS if c not in fn]
    if missing:
        return u"Faltan columnas obligatorias: {0}".format(u", ".join(missing))
    return u""


def _normalize_row_keys(row):
    out = {}
    for k, v in row.items():
        if k is None:
            continue
        nk = unicodedata.normalize("NFC", _u(k))
        out[nk] = v
    return out


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


def _read_field_value(doc, element, field_spec):
    kind = field_spec[1]
    if kind == u"shared":
        p = _lookup_named_instance_or_type(doc, element, field_spec[2])
        return _param_display(p)
    if kind == u"builtin":
        try:
            p = element.get_Parameter(field_spec[2])
            return _param_display(p)
        except Exception:
            return u""
    return u""


def _append_bucket(buckets, field_key, norm_val, eid):
    if not norm_val:
        return
    if field_key not in buckets:
        buckets[field_key] = {}
    d = buckets[field_key]
    if norm_val not in d:
        d[norm_val] = []
    ids = d[norm_val]
    sid = _element_id_str(eid)
    for existing in ids:
        if _element_id_str(existing) == sid:
            return
    ids.append(eid)


def _element_id_str(eid):
    try:
        if hasattr(eid, u"Value"):
            return unicode(int(eid.Value))
        return unicode(int(eid.IntegerValue))
    except Exception:
        return u""


def build_match_buckets(doc, log_lines=None):
    """
    buckets[field_key][normalized_value] = [ElementId, ...]
    Solo elementos de categoría Model, no tipos.
    """
    if log_lines is None:
        log_lines = []

    buckets = {}
    for spec in MATCH_FIELDS:
        fk = spec[0]
        buckets[fk] = {}

    scanned = 0
    model_count = 0

    col = FilteredElementCollector(doc).WhereElementIsNotElementType()
    for el in col:
        scanned += 1
        try:
            cat = el.Category
            if cat is None:
                continue
            if cat.CategoryType != CategoryType.Model:
                continue
        except Exception:
            continue

        model_count += 1
        for spec in MATCH_FIELDS:
            fk = spec[0]
            raw = _read_field_value(doc, el, spec)
            nk = normalize_match_key(raw)
            if nk:
                _append_bucket(buckets, fk, nk, el.Id)

    log_lines.append(
        u"Buckets ancestro: escaneados={0}, elementos_modelo={1}".format(scanned, model_count)
    )
    return buckets, {u"scanned": scanned, u"model_elements": model_count}


def _has_nonempty_nodo_dibujado(doc, element):
    """True si BTZ_NodoDibujado tiene texto no vacío (instancia o tipo)."""
    raw = _read_field_value(doc, element, SPEC_BTZ_NODO_DIBUJADO)
    return bool(normalize_match_key(raw))


def find_elements_for_key(buckets, ancestor_key_norm):
    """
    Devuelve (lista ElementId, nombre_campo_que_matcheó) o ([], u"").
    Orden MATCH_FIELDS: primer bucket no vacío gana.
    """
    if not ancestor_key_norm:
        return [], u""

    for spec in MATCH_FIELDS:
        fk = spec[0]
        d = buckets.get(fk) or {}
        ids = d.get(ancestor_key_norm)
        if ids:
            return list(ids), fk
    return [], u""


def _load_csv_rows(path):
    rows = []
    with codecs.open(path, u"r", encoding=u"utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        err = _validate_headers(reader.fieldnames)
        if err:
            raise ValueError(err)
        for raw in reader:
            rows.append(_normalize_row_keys(raw))
    return rows


def _apply_btz(doc, element, vals):
    errs = []
    for i, pname in enumerate(PARAM_BTZ):
        ok, err = set_text_parameter(element, pname, vals[i])
        if not ok:
            errs.append(u"{0}: {1}".format(pname, err or u"error"))
    return len(errs) == 0, errs


def run_apply_by_ancestro_csv(doc, log_lines=None):
    if log_lines is None:
        log_lines = []

    _ensure_public_dir()
    path_in = get_public_file(CSV_NAME, u"core", fallback=True)
    path_out = get_public_file(RESULTS_CSV, u"legacy", fallback=False)
    path_sum = get_public_file(SUMMARY_TXT, u"legacy", fallback=False)

    if not os.path.isfile(path_in):
        raise IOError(
            u"No existe el archivo requerido:\n{0}\n\n"
            u"Colocá ahí asociacion_por_ancestro_dibujado.csv".format(path_in)
        )

    ensure_btz_shared_parameters(doc, log_lines)

    rows = _load_csv_rows(path_in)

    buckets, scan_stats = build_match_buckets(doc, log_lines)

    if scan_stats.get(u"model_elements", 0) == 0:
        raise ValueError(
            u"No hay elementos de categoría Model en el documento; no se puede aplicar BTZ."
        )

    result_rows = []
    nodos_procesados = 0
    filas_sin_ancestro = 0
    nodos_match = 0
    nodos_sin_match = 0
    nodos_multiple = 0
    elementos_escritos = 0
    errores = 0

    tx = Transaction(doc, u"BTZ | Aplicar por asociacion_por_ancestro_dibujado.csv")
    tx.Start()
    try:
        for row in rows:
            raw_a = _u(row.get(u"ancestro_dibujado", u""))
            akey = normalize_match_key(raw_a)
            vals = [_u(row.get(k, u"")) for k in BTZ_KEYS]

            if not akey:
                filas_sin_ancestro += 1
                result_rows.append(
                    {
                        u"ancestro_dibujado": raw_a,
                        u"element_id": u"",
                        u"match_status": u"sin_match",
                        u"btz_01": vals[0],
                        u"btz_02": vals[1],
                        u"btz_03": vals[2],
                        u"btz_04": vals[3],
                        u"mensaje": u"fila sin ancestro_dibujado",
                    }
                )
                continue

            nodos_procesados += 1
            ids, matched_field = find_elements_for_key(buckets, akey)

            if not ids:
                nodos_sin_match += 1
                result_rows.append(
                    {
                        u"ancestro_dibujado": raw_a,
                        u"element_id": u"",
                        u"match_status": u"sin_match",
                        u"btz_01": vals[0],
                        u"btz_02": vals[1],
                        u"btz_03": vals[2],
                        u"btz_04": vals[3],
                        u"mensaje": u"sin elemento con esa clave en {0}".format(
                            u", ".join(x[0] for x in MATCH_FIELDS)
                        ),
                    }
                )
                continue

            if len(ids) == 1:
                st = u"ok"
                nodos_match += 1
            else:
                st = u"multiple"
                nodos_multiple += 1

            for eid in ids:
                el = doc.GetElement(eid)
                if el is None:
                    errores += 1
                    result_rows.append(
                        {
                            u"ancestro_dibujado": raw_a,
                            u"element_id": _element_id_str(eid),
                            u"match_status": st,
                            u"btz_01": vals[0],
                            u"btz_02": vals[1],
                            u"btz_03": vals[2],
                            u"btz_04": vals[3],
                            u"mensaje": u"ElementId inválido; match_via={0}".format(matched_field),
                        }
                    )
                    continue

                sin_nodo_dedicado = matched_field != u"BTZ_NodoDibujado" and not _has_nonempty_nodo_dibujado(
                    doc, el
                )
                ok, errs = _apply_btz(doc, el, vals)
                msg = u"match_via={0}".format(matched_field)
                if sin_nodo_dedicado:
                    msg += u"; sin_nodo_dedicado"
                if not ok:
                    errores += 1
                    msg += u"; " + u" | ".join(errs)
                else:
                    elementos_escritos += 1

                result_rows.append(
                    {
                        u"ancestro_dibujado": raw_a,
                        u"element_id": _element_id_str(eid),
                        u"match_status": st,
                        u"btz_01": vals[0],
                        u"btz_02": vals[1],
                        u"btz_03": vals[2],
                        u"btz_04": vals[3],
                        u"mensaje": msg,
                    }
                )

        tx.Commit()
    except Exception:
        if tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
        raise

    out_fields = [
        u"ancestro_dibujado",
        u"element_id",
        u"match_status",
        u"btz_01",
        u"btz_02",
        u"btz_03",
        u"btz_04",
        u"mensaje",
    ]
    with codecs.open(path_out, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=out_fields, lineterminator=u"\n")
        w.writeheader()
        for r in result_rows:
            w.writerow(r)

    summary = [
        u"BTZ por asociacion_por_ancestro_dibujado.csv",
        u"Entrada: {0}".format(path_in),
        u"",
        u"Prioridad de match (primera coincidencia no vacía): {0}".format(
            u" → ".join(x[0] for x in MATCH_FIELDS)
        ),
        u"Normalización: trim + NFC + uppercase",
        u"",
        u"Filas sin ancestro_dibujado: {0}".format(filas_sin_ancestro),
        u"Nodos (filas con ancestro no vacío) procesados: {0}".format(nodos_procesados),
        u"Nodos con al menos un elemento encontrado: {0}".format(nodos_match + nodos_multiple),
        u"Nodos sin match en modelo: {0}".format(nodos_sin_match),
        u"Nodos con múltiples elementos: {0}".format(nodos_multiple),
        u"Elementos con BTZ escrito OK: {0}".format(elementos_escritos),
        u"Filas con error de escritura: {0}".format(errores),
        u"",
        u"Resultados: {0}".format(path_out),
    ]

    with codecs.open(path_sum, u"w", encoding=u"utf-8-sig") as fp:
        fp.write(u"\n".join(summary) + u"\n")

    log_lines.extend(summary)

    return {
        u"path_in": path_in,
        u"path_out": path_out,
        u"path_sum": path_sum,
        u"nodos_procesados": nodos_procesados,
        u"filas_sin_ancestro": filas_sin_ancestro,
        u"nodos_con_match": nodos_match + nodos_multiple,
        u"nodos_sin_match": nodos_sin_match,
        u"nodos_multiple": nodos_multiple,
        u"elementos_escritos": elementos_escritos,
        u"errores": errores,
    }
