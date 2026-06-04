# -*- coding: utf-8 -*-
"""Append manual BTZ codes to BTZ_Description_05..80 only (no overwrite)."""
from __future__ import print_function

import codecs
import csv
import os

try:
    unicode
except NameError:
    unicode = str


def _u(v):
    if v is None:
        return u""
    try:
        return unicode(v).strip()
    except Exception:
        try:
            return unicode(str(v)).strip()
        except Exception:
            return u""


# Índices en PARAM_NUMERIC (0 = BTZ_Description_01)
_CHILD_SLICE_START = 4
_CHILD_SLICE_END = 80


def child_slot_param_names(param_numeric):
    """BTZ_Description_05 .. BTZ_Description_80."""
    return list(param_numeric[_CHILD_SLICE_START:_CHILD_SLICE_END])


def get_btz_slots(element, get_param_value, param_numeric):
    """Lista (nombre_param, valor_actual) para BTZ_Description_01..80."""
    out = []
    for pname in param_numeric:
        out.append((pname, _u(get_param_value(element, pname))))
    return out


def find_first_free_btz_slot(element, get_param_value, param_numeric, start=5, end=80):
    """
    Primer BTZ_Description_N vacío entre start y end (inclusive).
    start/end 1-based slot numbers (5 => BTZ_Description_05).
    """
    if start < 1 or end > 80 or start > end:
        return None
    for idx in range(start - 1, end):
        pname = param_numeric[idx]
        if not _u(get_param_value(element, pname)):
            return pname
    return None


def count_free_child_slots(element, get_param_value, param_numeric):
    n = 0
    for pname in child_slot_param_names(param_numeric):
        if not _u(get_param_value(element, pname)):
            n += 1
    return n


def normalize_pasted_codes(text):
    if not text:
        return []
    raw = text.replace(u"\r\n", u"\n").replace(u"\r", u"\n")
    out = []
    for line in raw.split(u"\n"):
        c = _u(line)
        if c:
            out.append(c)
    return out


def build_existing_keys_all_slots(element, get_param_value, param_numeric):
    keys = set()
    for pname in param_numeric:
        v = _u(get_param_value(element, pname))
        if v:
            keys.add(v.upper())
    return keys


LOG_FIELDS = [
    u"fecha",
    u"element_id",
    u"codigo",
    u"accion",
    u"slot",
    u"mensaje",
]


def append_manual_slots_log(log_path, rows):
    if not rows:
        return
    parent = os.path.dirname(os.path.abspath(log_path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    exists = os.path.isfile(log_path)
    with codecs.open(log_path, u"a", encoding=u"utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=LOG_FIELDS, lineterminator=u"\n")
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, u"") for k in LOG_FIELDS})


def append_codes_to_btz_slots(
    element,
    codes,
    set_text_parameter,
    get_param_value,
    param_numeric,
    fecha,
    element_id,
    log_path,
):
    """
    Escribe códigos solo en slots 05..80 libres. No modifica 01..04 ni NumeroActivo.
    Retorna dict con contadores, slots_usados, log_rows, errors.
    """
    result = {
        u"total_recibidos": len(codes),
        u"agregados": 0,
        u"duplicados_omitidos": 0,
        u"sin_slot": 0,
        u"errores_escritura": 0,
        u"slots_usados": [],
        u"log_rows": [],
        u"errors": [],
    }
    existing = build_existing_keys_all_slots(element, get_param_value, param_numeric)
    child_names = child_slot_param_names(param_numeric)

    next_child_idx = 0

    for code in codes:
        key = code.upper()
        log_base = {
            u"fecha": fecha,
            u"element_id": element_id,
            u"codigo": code,
            u"accion": u"",
            u"slot": u"",
            u"mensaje": u"",
        }
        if key in existing:
            result[u"duplicados_omitidos"] += 1
            lr = dict(log_base)
            lr[u"accion"] = u"duplicado_omitido"
            lr[u"mensaje"] = u"El código ya existe en BTZ_Description_01..80"
            result[u"log_rows"].append(lr)
            continue

        slot_name = u""
        while next_child_idx < len(child_names):
            cand = child_names[next_child_idx]
            if not _u(get_param_value(element, cand)):
                slot_name = cand
                break
            next_child_idx += 1

        if not slot_name:
            result[u"sin_slot"] += 1
            lr = dict(log_base)
            lr[u"accion"] = u"sin_slot"
            lr[u"mensaje"] = u"No hay slots BTZ libres entre 05 y 80"
            result[u"log_rows"].append(lr)
            continue

        ok, err = set_text_parameter(element, slot_name, code)
        if ok:
            result[u"agregados"] += 1
            existing.add(key)
            result[u"slots_usados"].append(slot_name)
            next_child_idx += 1
            lr = dict(log_base)
            lr[u"accion"] = u"agregado"
            lr[u"slot"] = slot_name
            lr[u"mensaje"] = u"OK"
            result[u"log_rows"].append(lr)
        else:
            result[u"errores_escritura"] += 1
            msg = _u(err) or u"error"
            result[u"errors"].append(u"{0}: {1}".format(slot_name, msg))
            lr = dict(log_base)
            lr[u"accion"] = u"error_escritura"
            lr[u"slot"] = slot_name
            lr[u"mensaje"] = msg
            result[u"log_rows"].append(lr)
            next_child_idx += 1

    if log_path:
        append_manual_slots_log(log_path, result[u"log_rows"])
    return result
