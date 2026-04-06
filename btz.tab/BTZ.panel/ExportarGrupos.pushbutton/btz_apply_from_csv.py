# -*- coding: utf-8 -*-
"""
Aplicación determinista de BTZ desde CSV (sin IA, sin webhook).

LEGACY: flujo alternativo al resolver oficial.
Entrada: public/asignacion_automatica_sugerida.csv
Salida: public/_legacy/apply_from_csv_results.csv, public/_legacy/apply_from_csv_summary.txt
"""
from __future__ import print_function

import codecs
import csv
import os
import unicodedata

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import Transaction, TransactionStatus

from btz_apply_webhook import (
    _ensure_public_dir,
    ensure_btz_shared_parameters,
    set_text_parameter,
    _param_value_as_string,
)
from btz_paths import get_public_file
from btz_revit_code_index import (
    build_codigo_to_elements_map,
    normalize_codigo,
    describe_match_policy,
)

try:
    unicode
except NameError:
    unicode = str

CSV_IN_NAME = u"asignacion_automatica_sugerida.csv"
CSV_OUT_NAME = u"apply_from_csv_results.csv"
TXT_SUMMARY_NAME = u"apply_from_csv_summary.txt"

# Columnas obligatorias (cabecera exacta del CSV)
REQUIRED_COLUMNS = [
    u"codigo_activo",
    u"Número Activo Principal",
    u"Grupo Activos",
    u"Descripción",
    u"ancestro_dibujado",
    u"btz_01_sugerido",
    u"btz_02_sugerido",
    u"btz_03_sugerido",
    u"btz_04_sugerido",
]

BTZ_KEYS = (
    u"btz_01_sugerido",
    u"btz_02_sugerido",
    u"btz_03_sugerido",
    u"btz_04_sugerido",
)

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


def _element_id_str(eid):
    try:
        if hasattr(eid, u"Value"):
            return unicode(int(eid.Value))
        return unicode(int(eid.IntegerValue))
    except Exception:
        return u""


def _btz_values_tuple(element):
    return tuple(_u(_param_value_as_string(element, p)) for p in PARAM_BTZ)


def _had_any_btz(element):
    return any(_u(_param_value_as_string(element, p)) for p in PARAM_BTZ)


def _validate_csv_headers(fieldnames):
    if not fieldnames:
        return u"El CSV no tiene cabecera o está vacío."
    fn = [_unicode_header(x) for x in fieldnames]
    missing = [c for c in REQUIRED_COLUMNS if c not in fn]
    if missing:
        return u"Faltan columnas obligatorias: {0}".format(u", ".join(missing))
    return u""


def _unicode_header(h):
    if h is None:
        return u""
    s = _u(h)
    return unicodedata.normalize("NFC", s)


def _normalize_row_keys(row):
    """Claves NFC para alinear con REQUIRED_COLUMNS."""
    out = {}
    for k, v in row.items():
        if k is None:
            continue
        nk = unicodedata.normalize("NFC", _u(k))
        out[nk] = v
    return out


def _load_assignment_rows(path):
    rows = []
    with codecs.open(path, u"r", encoding=u"utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        err = _validate_csv_headers(reader.fieldnames)
        if err:
            raise ValueError(err)
        for raw in reader:
            rows.append(_normalize_row_keys(raw))
    return rows


def _apply_btz_to_element(doc, element, btz_vals):
    """
    btz_vals: 4 strings para 01..04 (ya normalizadas).
    Retorna (ok_bool, lista_errores).
    """
    errors = []
    for i, pname in enumerate(PARAM_BTZ):
        val = btz_vals[i]
        ok, err = set_text_parameter(element, pname, val)
        if not ok:
            errors.append(u"{0}: {1}".format(pname, err or u"error"))
    return (len(errors) == 0, errors)


def run_apply_from_csv(doc, log_lines=None):
    """
    Ejecuta el flujo completo (transacción de escritura BTZ).
    Devuelve dict con rutas, contadores y líneas de log.
    """
    if log_lines is None:
        log_lines = []

    _ensure_public_dir()
    csv_in = get_public_file(CSV_IN_NAME, u"core", fallback=True)
    csv_out = get_public_file(CSV_OUT_NAME, u"legacy", fallback=False)
    txt_out = get_public_file(TXT_SUMMARY_NAME, u"legacy", fallback=False)

    if not os.path.isfile(csv_in):
        raise IOError(
            u"No existe el archivo de asignación:\n{0}\n\n"
            u"Colocá ahí el CSV resuelto (asignacion_automatica_sugerida.csv).".format(csv_in)
        )

    ensure_btz_shared_parameters(doc, log_lines)

    try:
        rows = _load_assignment_rows(csv_in)
    except Exception as ex:
        raise ValueError(unicode(ex))

    index, stats = build_codigo_to_elements_map(doc, log_lines)
    log_lines.append(describe_match_policy())

    result_rows = []
    filas_leidas = len(rows)
    filas_sin_codigo = 0
    actualizados = 0
    sin_match = 0
    multiples = 0
    errores_escritura = 0
    sobrescritos = 0

    tx = Transaction(doc, u"BTZ | Aplicar desde CSV (asignacion_automatica_sugerida)")
    tx.Start()
    try:
        for row in rows:
            code_raw = _u(row.get(u"codigo_activo", u""))
            code = normalize_codigo(code_raw)
            btz_vals = []
            for k in BTZ_KEYS:
                btz_vals.append(_u(row.get(k, u"")))

            if not code:
                filas_sin_codigo += 1
                result_rows.append(
                    {
                        u"codigo_activo": code_raw,
                        u"element_id": u"",
                        u"match_status": u"fila_sin_codigo",
                        u"btz_01": btz_vals[0],
                        u"btz_02": btz_vals[1],
                        u"btz_03": btz_vals[2],
                        u"btz_04": btz_vals[3],
                        u"mensaje": u"codigo_activo vacío en la fila",
                    }
                )
                continue

            ids = index.get(code)
            if not ids:
                sin_match += 1
                result_rows.append(
                    {
                        u"codigo_activo": code_raw,
                        u"element_id": u"",
                        u"match_status": u"sin_match",
                        u"btz_01": btz_vals[0],
                        u"btz_02": btz_vals[1],
                        u"btz_03": btz_vals[2],
                        u"btz_04": btz_vals[3],
                        u"mensaje": u"ningún elemento con ese código en el índice",
                    }
                )
                continue

            if len(ids) > 1:
                multiples += 1
                eid_str = u";".join(_element_id_str(i) for i in ids[:20])
                if len(ids) > 20:
                    eid_str += u";..."
                result_rows.append(
                    {
                        u"codigo_activo": code_raw,
                        u"element_id": eid_str,
                        u"match_status": u"match_multiple",
                        u"btz_01": btz_vals[0],
                        u"btz_02": btz_vals[1],
                        u"btz_03": btz_vals[2],
                        u"btz_04": btz_vals[3],
                        u"mensaje": u"varios elementos comparten el código; no se aplica automáticamente",
                    }
                )
                continue

            eid = ids[0]
            el = doc.GetElement(eid)
            if el is None:
                sin_match += 1
                result_rows.append(
                    {
                        u"codigo_activo": code_raw,
                        u"element_id": _element_id_str(eid),
                        u"match_status": u"sin_match",
                        u"btz_01": btz_vals[0],
                        u"btz_02": btz_vals[1],
                        u"btz_03": btz_vals[2],
                        u"btz_04": btz_vals[3],
                        u"mensaje": u"ElementId no resuelto en el documento",
                    }
                )
                continue

            prev = _had_any_btz(el)
            ok, errs = _apply_btz_to_element(doc, el, btz_vals)
            msg_parts = []
            if prev:
                sobrescritos += 1
                msg_parts.append(u"sobrescrito_BTZ_previo")
            if not ok:
                errores_escritura += 1
                msg_parts.append(u"error: " + u" | ".join(errs))
                st = u"error_escritura"
            else:
                actualizados += 1
                st = u"aplicado_sobrescrito" if prev else u"aplicado"

            result_rows.append(
                {
                    u"codigo_activo": code_raw,
                    u"element_id": _element_id_str(eid),
                    u"match_status": st,
                    u"btz_01": btz_vals[0],
                    u"btz_02": btz_vals[1],
                    u"btz_03": btz_vals[2],
                    u"btz_04": btz_vals[3],
                    u"mensaje": u"; ".join(msg_parts) if msg_parts else u"",
                }
            )

        tx.Commit()
    except Exception:
        if tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
        raise

    # Escribir CSV de resultados
    out_fields = [
        u"codigo_activo",
        u"element_id",
        u"match_status",
        u"btz_01",
        u"btz_02",
        u"btz_03",
        u"btz_04",
        u"mensaje",
    ]
    with codecs.open(csv_out, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=out_fields, lineterminator=u"\n")
        w.writeheader()
        for r in result_rows:
            w.writerow(r)

    summary_lines = [
        u"BTZ aplicar desde CSV (determinista)",
        u"Entrada: {0}".format(csv_in),
        u"Política de match: {0}".format(describe_match_policy()),
        u"",
        u"Filas leídas (datos): {0}".format(filas_leidas),
        u"Filas sin codigo_activo: {0}".format(filas_sin_codigo),
        u"Elementos en índice (total IDs con código): {0}".format(stats.get(u"total_indexed_ids", 0)),
        u"Códigos distintos en modelo: {0}".format(stats.get(u"distinct_codes", 0)),
        u"Elementos actualizados (BTZ escrito sin error): {0}".format(actualizados),
        u"Filas sin match (código no en modelo): {0}".format(sin_match),
        u"Filas match_multiple (no aplicado): {0}".format(multiples),
        u"Filas con error de escritura: {0}".format(errores_escritura),
        u"Elementos con BTZ previo sobrescrito: {0}".format(sobrescritos),
        u"",
        u"Salida CSV: {0}".format(csv_out),
    ]

    with codecs.open(txt_out, u"w", encoding=u"utf-8-sig") as fp:
        fp.write(u"\n".join(summary_lines) + u"\n")

    log_lines.extend(summary_lines)

    return {
        u"csv_in": csv_in,
        u"csv_out": csv_out,
        u"txt_out": txt_out,
        u"filas_leidas": filas_leidas,
        u"filas_sin_codigo": filas_sin_codigo,
        u"actualizados": actualizados,
        u"sin_match": sin_match,
        u"match_multiple": multiples,
        u"errores_escritura": errores_escritura,
        u"sobrescritos": sobrescritos,
        u"stats_index": stats,
    }


def load_asignacion_csv(path):
    """API pública para otros flujos (p. ej. aplicación por ancestro_dibujado)."""
    return _load_assignment_rows(path)


def apply_btz_tuple(doc, element, btz_vals):
    """Escribe BTZ_Description_01..04 en un elemento."""
    return _apply_btz_to_element(doc, element, btz_vals)


def element_has_any_btz(element):
    return _had_any_btz(element)
