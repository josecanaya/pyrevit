# -*- coding: utf-8 -*-
"""
Aplicación BTZ agrupada por ancestro_dibujado (determinista, sin IA).
LEGACY: flujo alternativo al resolver oficial.

Lee public/asignacion_automatica_sugerida.csv, agrupa por ancestro_dibujado,
busca el/los elemento(s) Revit que representan ese nodo y escribe el mismo
paquete BTZ (btz_01..04 sugeridos) en ese elemento.

Salidas:
- public/_legacy/apply_from_ancestor_report.csv  (una fila por ancestro)
- public/_legacy/apply_from_ancestor_summary.txt
"""
from __future__ import print_function

import codecs
import csv
import os

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import Transaction, TransactionStatus

from btz_apply_webhook import (
    _ensure_public_dir,
    ensure_btz_shared_parameters,
)
from btz_paths import get_public_file
from btz_apply_from_csv import (
    CSV_IN_NAME,
    BTZ_KEYS,
    load_asignacion_csv,
    apply_btz_tuple,
    element_has_any_btz,
)
from btz_revit_code_index import normalize_codigo
from btz_ancestor_index import (
    build_ancestor_maps,
    find_elements_for_ancestor_key,
    describe_ancestor_match_policy,
)

try:
    unicode
except NameError:
    unicode = str

REPORT_CSV = u"apply_from_ancestor_report.csv"
SUMMARY_TXT = u"apply_from_ancestor_summary.txt"


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


def _consolidate_btz_for_group(rows):
    """
    rows: lista de dicts normalizados del CSV.
    Retorna (tuple 4 btz, mensaje_conflictos o u"").
    """
    tuples = []
    for row in rows:
        t = tuple(_u(row.get(k, u"")) for k in BTZ_KEYS)
        tuples.append(t)
    unique = []
    for t in tuples:
        if t not in unique:
            unique.append(t)
    if len(unique) == 1:
        return unique[0], u""
    return tuples[0], u"conflicto: distintos btz_* sugeridos entre filas del mismo ancestro; se usa la primera fila"


def run_apply_from_ancestor(doc, log_lines=None):
    if log_lines is None:
        log_lines = []

    _ensure_public_dir()
    csv_in = get_public_file(CSV_IN_NAME, u"core", fallback=True)
    csv_report = get_public_file(REPORT_CSV, u"legacy", fallback=False)
    txt_summary = get_public_file(SUMMARY_TXT, u"legacy", fallback=False)

    if not os.path.isfile(csv_in):
        raise IOError(
            u"No existe el archivo:\n{0}\n\n"
            u"Colocá ahí asignacion_automatica_sugerida.csv".format(csv_in)
        )

    ensure_btz_shared_parameters(doc, log_lines)

    try:
        rows = load_asignacion_csv(csv_in)
    except Exception as ex:
        raise ValueError(unicode(ex))

    maps_bundle = build_ancestor_maps(doc, log_lines)
    maps = {
        u"by_dedicated": maps_bundle[u"by_dedicated"],
        u"by_btz3": maps_bundle[u"by_btz3"],
        u"by_btz4": maps_bundle[u"by_btz4"],
        u"by_btz34": maps_bundle[u"by_btz34"],
    }
    idx_stats = maps_bundle[u"stats"]
    log_lines.append(describe_ancestor_match_policy())

    # Agrupar por ancestro_dibujado normalizado
    groups = {}
    order_keys = []
    filas_sin_ancestro = 0
    for row in rows:
        raw_a = _u(row.get(u"ancestro_dibujado", u""))
        nk = normalize_codigo(raw_a)
        if not nk:
            filas_sin_ancestro += 1
            continue
        if nk not in groups:
            groups[nk] = []
            order_keys.append(nk)
        groups[nk].append(row)

    report_rows = []
    aplicados = 0
    sin_match = 0
    multiples = 0
    errores_escritura = 0
    sobrescritos = 0

    tx = Transaction(doc, u"BTZ | Aplicar por ancestro_dibujado (CSV)")
    tx.Start()
    try:
        for nk in order_keys:
            group_rows = groups[nk]
            raw_display = _u(group_rows[0].get(u"ancestro_dibujado", u""))
            activos_excel = len(group_rows)

            btz_vals, conflict_msg = _consolidate_btz_for_group(group_rows)

            ids, match_via = find_elements_for_ancestor_key(maps, nk)

            if not ids:
                sin_match += 1
                report_rows.append(
                    {
                        u"ancestro_dibujado": raw_display,
                        u"activos_excel": activos_excel,
                        u"elementos_revit": 0,
                        u"match_status": u"sin_match",
                        u"match_via": u"",
                        u"btz_01": btz_vals[0],
                        u"btz_02": btz_vals[1],
                        u"btz_03": btz_vals[2],
                        u"btz_04": btz_vals[3],
                        u"element_id": u"",
                        u"mensaje": conflict_msg
                        or u"ningún elemento con esa clave en índice (dedicated / BTZ_03 / BTZ_04 / BTZ_03+04)",
                    }
                )
                continue

            if len(ids) > 1:
                multiples += 1
                eid_str = u";".join(_element_id_str(i) for i in ids[:30])
                if len(ids) > 30:
                    eid_str += u";..."
                report_rows.append(
                    {
                        u"ancestro_dibujado": raw_display,
                        u"activos_excel": activos_excel,
                        u"elementos_revit": len(ids),
                        u"match_status": u"multiple_match",
                        u"match_via": match_via,
                        u"btz_01": btz_vals[0],
                        u"btz_02": btz_vals[1],
                        u"btz_03": btz_vals[2],
                        u"btz_04": btz_vals[3],
                        u"element_id": eid_str,
                        u"mensaje": u"; ".join(
                            [
                                x
                                for x in (
                                    conflict_msg,
                                    u"varios elementos: {0}".format(eid_str),
                                )
                                if x
                            ]
                        ),
                    }
                )
                continue

            eid = ids[0]
            el = doc.GetElement(eid)
            if el is None:
                sin_match += 1
                report_rows.append(
                    {
                        u"ancestro_dibujado": raw_display,
                        u"activos_excel": activos_excel,
                        u"elementos_revit": 0,
                        u"match_status": u"sin_match",
                        u"match_via": match_via,
                        u"btz_01": btz_vals[0],
                        u"btz_02": btz_vals[1],
                        u"btz_03": btz_vals[2],
                        u"btz_04": btz_vals[3],
                        u"element_id": _element_id_str(eid),
                        u"mensaje": conflict_msg or u"ElementId inválido",
                    }
                )
                continue

            prev = element_has_any_btz(el)
            ok, errs = apply_btz_tuple(doc, el, list(btz_vals))
            msg_parts = []
            if conflict_msg:
                msg_parts.append(conflict_msg)
            if prev:
                sobrescritos += 1
                msg_parts.append(u"sobrescrito_BTZ_previo")
            if not ok:
                errores_escritura += 1
                msg_parts.append(u"error: " + u" | ".join(errs))
                st = u"error_escritura"
            else:
                aplicados += 1
                st = u"match_ok"

            report_rows.append(
                {
                    u"ancestro_dibujado": raw_display,
                    u"activos_excel": activos_excel,
                    u"elementos_revit": 1,
                    u"match_status": st,
                    u"match_via": match_via,
                    u"btz_01": btz_vals[0],
                    u"btz_02": btz_vals[1],
                    u"btz_03": btz_vals[2],
                    u"btz_04": btz_vals[3],
                    u"element_id": _element_id_str(eid),
                    u"mensaje": u"; ".join(msg_parts) if msg_parts else u"",
                }
            )

        tx.Commit()
    except Exception:
        if tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
        raise

    report_fields = [
        u"ancestro_dibujado",
        u"activos_excel",
        u"elementos_revit",
        u"match_status",
        u"match_via",
        u"btz_01",
        u"btz_02",
        u"btz_03",
        u"btz_04",
        u"element_id",
        u"mensaje",
    ]

    with codecs.open(csv_report, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=report_fields, lineterminator=u"\n")
        w.writeheader()
        for r in report_rows:
            w.writerow(r)

    summary_lines = [
        u"BTZ aplicar por ancestro_dibujado (CSV)",
        u"Entrada: {0}".format(csv_in),
        u"Política: {0}".format(describe_ancestor_match_policy()),
        u"",
        u"Filas CSV leídas: {0}".format(len(rows)),
        u"Filas sin ancestro_dibujado: {0}".format(filas_sin_ancestro),
        u"Grupos distintos por ancestro: {0}".format(len(order_keys)),
        u"Elementos escaneados (índice): {0}".format(idx_stats.get(u"elements_scanned", 0)),
        u"",
        u"Ancestros aplicados OK (match_ok): {0}".format(aplicados),
        u"Ancestros sin_match: {0}".format(sin_match),
        u"Ancestros multiple_match: {0}".format(multiples),
        u"Errores de escritura: {0}".format(errores_escritura),
        u"BTZ previo sobrescrito: {0}".format(sobrescritos),
        u"",
        u"Informe CSV: {0}".format(csv_report),
    ]

    with codecs.open(txt_summary, u"w", encoding=u"utf-8-sig") as fp:
        fp.write(u"\n".join(summary_lines) + u"\n")

    log_lines.extend(summary_lines)

    return {
        u"csv_in": csv_in,
        u"csv_report": csv_report,
        u"txt_summary": txt_summary,
        u"filas_leidas": len(rows),
        u"filas_sin_ancestro": filas_sin_ancestro,
        u"grupos_ancestro": len(order_keys),
        u"aplicados": aplicados,
        u"sin_match": sin_match,
        u"multiple_match": multiples,
        u"errores_escritura": errores_escritura,
        u"sobrescritos": sobrescritos,
        u"stats_index": idx_stats,
    }
