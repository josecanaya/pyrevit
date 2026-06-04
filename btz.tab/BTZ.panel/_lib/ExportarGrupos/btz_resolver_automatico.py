# -*- coding: utf-8 -*-
"""
OFFICIAL runtime: resolver_btz_automatico (un solo flujo determinista).

Fases A–F: anclas en Revit, CSV asociación, CSV asignación, índice codigo_activo,
herencia de paquete BTZ desde ancestro, log.
"""
from __future__ import print_function

import codecs
import csv
import os
import unicodedata
from collections import Counter

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    BuiltInParameter,
    CategoryType,
    ElementId,
    FamilyInstance,
    FilteredElementCollector,
    Transaction,
    TransactionStatus,
)

from btz_apply_webhook import (
    _ensure_public_dir,
    ensure_btz_shared_parameters,
    set_text_parameter,
    _param_value_as_string,
)
from btz_paths import PUBLIC_DIR, get_public_file

try:
    unicode
except NameError:
    unicode = str

CSV_ASOCIACION = u"asociacion_por_ancestro_dibujado.csv"
CSV_ASIGNACION = u"asignacion_automatica_sugerida.csv"
OUT_RESULTS = u"resolver_btz_automatico_results.csv"
OUT_SUMMARY = u"resolver_btz_automatico_summary.txt"

DEBUG_ANCLAS = u"debug_anclas_detectadas.csv"
DEBUG_ANCLAS_RESUMEN = u"debug_anclas_resumen.csv"
DEBUG_MATCH_ANCESTROS = u"debug_match_ancestros.csv"
DEBUG_RESOLUCION_ACTIVOS = u"debug_resolucion_activos.csv"
DEBUG_SUMMARY = u"debug_resolver_btz_summary.txt"

# --- CSV asociación
ASOCIACION_REQUIRED = [
    u"ancestro_dibujado",
    u"btz_01_sugerido",
    u"btz_02_sugerido",
    u"btz_03_sugerido",
    u"btz_04_sugerido",
    u"cantidad_activos",
    u"ejemplos_activos",
]
ASOCIACION_BTZ_KEYS = [
    u"btz_01_sugerido",
    u"btz_02_sugerido",
    u"btz_03_sugerido",
    u"btz_04_sugerido",
]

# --- CSV asignación
ASIGNACION_REQUIRED = [
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

PARAM_BTZ = [
    u"BTZ_Description_01",
    u"BTZ_Description_02",
    u"BTZ_Description_03",
    u"BTZ_Description_04",
]

# Orden FASE D: codigo_activo en elemento
CODIGO_ACTIVO_FIELDS = [
    (u"BTZ_NumeroActivo", u"shared"),
    (u"Número Activo", u"shared"),
    (u"Asset Code", u"shared"),
    (u"Número Activo Principal", u"shared"),
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


def normalize_key(value):
    s = _u(value)
    if not s:
        return u""
    return unicodedata.normalize("NFC", s).upper()


def _unicode_header(h):
    if h is None:
        return u""
    return unicodedata.normalize("NFC", _u(h))


def _normalize_row_keys(row):
    out = {}
    for k, v in row.items():
        if k is None:
            continue
        out[unicodedata.normalize("NFC", _u(k))] = v
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


def read_codigo_activo_for_element(doc, element):
    """Primer valor no vacío según CODIGO_ACTIVO_FIELDS."""
    for spec in CODIGO_ACTIVO_FIELDS:
        if spec[1] == u"shared":
            p = _lookup_named_instance_or_type(doc, element, spec[0])
            v = _param_display(p)
            if v:
                return normalize_key(v), spec[0]
        else:
            try:
                p = element.get_Parameter(spec[2])
                v = _param_display(p)
                if v:
                    return normalize_key(v), spec[0]
            except Exception:
                pass
    return u"", u""


def _element_id_str(eid):
    try:
        if hasattr(eid, u"Value"):
            return unicode(int(eid.Value))
        return unicode(int(eid.IntegerValue))
    except Exception:
        return u""


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


def build_codigo_activo_index(doc, log_lines):
    """codigo normalizado -> [ElementId]"""
    idx = {}
    model_n = 0
    col = FilteredElementCollector(doc).WhereElementIsNotElementType()
    for el in col:
        try:
            cat = el.Category
            if cat is None or cat.CategoryType != CategoryType.Model:
                continue
        except Exception:
            continue
        model_n += 1
        code, _src = read_codigo_activo_for_element(doc, el)
        if not code:
            continue
        if code not in idx:
            idx[code] = []
        idx[code].append(el.Id)
    for k in list(idx.keys()):
        idx[k] = _dedupe_ids(idx[k])
    log_lines.append(u"Índice codigo_activo: elementos modelo={0}, claves distintas={1}".format(model_n, len(idx)))
    return idx, {u"model_elements": model_n, u"distinct_codes": len(idx)}


def derive_anchor_key(b1, b2, b3, b4):
    """
    Clave de ancestro desde BTZ ya cargado:
    1) BTZ_04 si no vacío (unidad)
    2) BTZ_03 si no vacío (subsector)
    Requiere BTZ_02 no vacío y (BTZ_03 o BTZ_04 no vacío).
    """
    n2 = normalize_key(b2)
    n3 = normalize_key(b3)
    n4 = normalize_key(b4)
    if not n2:
        return u""
    if not n3 and not n4:
        return u""
    if n4:
        return n4
    return n3


def build_anchor_map_from_revit(doc, log_lines):
    """
    ancestro_key -> (b1,b2,b3,b4) desde elementos que ya son nodos clasificados.
    """
    anchor_map = {}
    conflicts = 0
    col = FilteredElementCollector(doc).WhereElementIsNotElementType()
    for el in col:
        try:
            cat = el.Category
            if cat is None or cat.CategoryType != CategoryType.Model:
                continue
        except Exception:
            continue
        b1 = _u(_param_value_as_string(el, PARAM_BTZ[0]))
        b2 = _u(_param_value_as_string(el, PARAM_BTZ[1]))
        b3 = _u(_param_value_as_string(el, PARAM_BTZ[2]))
        b4 = _u(_param_value_as_string(el, PARAM_BTZ[3]))
        if not normalize_key(b2):
            continue
        if not normalize_key(b3) and not normalize_key(b4):
            continue
        key = derive_anchor_key(b1, b2, b3, b4)
        if not key:
            continue
        pkg = (b1, b2, b3, b4)
        if key not in anchor_map:
            anchor_map[key] = pkg
        else:
            if anchor_map[key] != pkg:
                conflicts += 1
    log_lines.append(
        u"Anclas Revit: {0} claves, conflictos de paquete distinto: {1}".format(len(anchor_map), conflicts)
    )
    return anchor_map, conflicts


def _validate_headers(fieldnames, required):
    fn = [_unicode_header(x) for x in (fieldnames or [])]
    missing = [c for c in required if c not in fn]
    if missing:
        return u"Faltan columnas: {0}".format(u", ".join(missing))
    return u""


def load_asociacion_csv(path):
    rows = {}
    with codecs.open(path, u"r", encoding=u"utf-8-sig") as fp:
        r = csv.DictReader(fp)
        err = _validate_headers(r.fieldnames, ASOCIACION_REQUIRED)
        if err:
            raise ValueError(err)
        for raw in r:
            row = _normalize_row_keys(raw)
            ak = normalize_key(row.get(u"ancestro_dibujado", u""))
            if not ak:
                continue
            tup = tuple(_u(row.get(k, u"")) for k in ASOCIACION_BTZ_KEYS)
            rows[ak] = tup
    return rows


def load_asignacion_csv(path):
    out = []
    with codecs.open(path, u"r", encoding=u"utf-8-sig") as fp:
        r = csv.DictReader(fp)
        err = _validate_headers(r.fieldnames, ASIGNACION_REQUIRED)
        if err:
            raise ValueError(err)
        for raw in r:
            out.append(_normalize_row_keys(raw))
    return out


def merge_packages(rev_pkg, csv_pkg):
    """Rellena vacíos del paquete Revit con CSV."""
    a = []
    for i in range(4):
        rv = _u(rev_pkg[i]) if rev_pkg else u""
        cv = _u(csv_pkg[i]) if csv_pkg else u""
        a.append(rv if rv else cv)
    return tuple(a)


def resolve_btz_package(ancestor_key, anchor_map, asociacion_map):
    """
    Retorna (tuple4, anchor_status) o (None, 'unresolved_anchor').
    anchor_status: resolved_from_model | resolved_from_csv | merged
    """
    rev = anchor_map.get(ancestor_key)
    csv = asociacion_map.get(ancestor_key)
    if rev and csv:
        return merge_packages(rev, csv), u"merged"
    if rev:
        return rev, u"resolved_from_model"
    if csv:
        return csv, u"resolved_from_csv"
    return None, u"unresolved_anchor"


def _element_category_family_type(doc, el):
    """Nombres legibles para diagnóstico."""
    catn = u""
    famn = u""
    typn = u""
    try:
        c = el.Category
        if c is not None:
            catn = _u(c.Name)
    except Exception:
        pass
    try:
        if isinstance(el, FamilyInstance):
            sym = el.Symbol
            if sym is not None:
                typn = _u(sym.Name)
                if sym.Family is not None:
                    famn = _u(sym.Family.Name)
    except Exception:
        pass
    if not typn:
        try:
            tid = el.GetTypeId()
            if tid is not None and tid != ElementId.InvalidElementId:
                t = doc.GetElement(tid)
                if t is not None:
                    typn = _u(t.Name)
                    fn = getattr(t, u"FamilyName", None)
                    if fn is not None and _u(fn):
                        famn = _u(fn)
        except Exception:
            pass
    return catn, famn, typn


def collect_valid_anchor_records(doc):
    """
    Elementos modelo que cumplen regla de ancla (misma que build_anchor_map_from_revit).
    Retorna lista de dicts con datos para CSV debug.
    """
    rows = []
    col = FilteredElementCollector(doc).WhereElementIsNotElementType()
    for el in col:
        try:
            cat = el.Category
            if cat is None or cat.CategoryType != CategoryType.Model:
                continue
        except Exception:
            continue
        b1 = _u(_param_value_as_string(el, PARAM_BTZ[0]))
        b2 = _u(_param_value_as_string(el, PARAM_BTZ[1]))
        b3 = _u(_param_value_as_string(el, PARAM_BTZ[2]))
        b4 = _u(_param_value_as_string(el, PARAM_BTZ[3]))
        if not normalize_key(b2):
            continue
        if not normalize_key(b3) and not normalize_key(b4):
            continue
        key = derive_anchor_key(b1, b2, b3, b4)
        if not key:
            continue
        cn, fn, tn = _element_category_family_type(doc, el)
        rows.append(
            {
                u"element_id": _element_id_str(el.Id),
                u"category": cn,
                u"family": fn,
                u"type": tn,
                u"btz_01": b1,
                u"btz_02": b2,
                u"btz_03": b3,
                u"btz_04": b4,
                u"anchor_key_resuelta": key,
            }
        )
    return rows


def load_asociacion_csv_all_rows(path):
    """Una fila por línea del CSV (sin deduplicar por ancestro)."""
    out = []
    with codecs.open(path, u"r", encoding=u"utf-8-sig") as fp:
        r = csv.DictReader(fp)
        err = _validate_headers(r.fieldnames, ASOCIACION_REQUIRED)
        if err:
            raise ValueError(err)
        for raw in r:
            out.append(_normalize_row_keys(raw))
    return out


def _diagnostico_fila_asignacion(doc, row, anchor_map, asociacion_map, codigo_index):
    """
    Replica la misma lógica de decisión que el bucle de aplicación (sin escribir).
    Retorna dict con columnas para debug_resolucion_activos.
    """
    raw_code = _u(row.get(u"codigo_activo", u""))
    raw_anc = _u(row.get(u"ancestro_dibujado", u""))
    ck = normalize_key(raw_code)
    ak = normalize_key(raw_anc)

    if not ck:
        return {
            u"codigo_activo": raw_code,
            u"ancestro_dibujado": raw_anc,
            u"ancestro_resuelto": u"n/a",
            u"codigo_activo_encontrado": u"n/a",
            u"match_status": u"sin_match",
            u"mensaje": u"fila sin codigo_activo",
        }

    if not ak:
        return {
            u"codigo_activo": raw_code,
            u"ancestro_dibujado": raw_anc,
            u"ancestro_resuelto": u"no",
            u"codigo_activo_encontrado": u"n/a",
            u"match_status": u"unresolved_anchor",
            u"mensaje": u"fila sin ancestro_dibujado",
        }

    ids = codigo_index.get(ck, [])
    if not ids:
        pkg, _st = resolve_btz_package(ak, anchor_map, asociacion_map)
        ar = u"sí" if pkg is not None else u"no"
        return {
            u"codigo_activo": raw_code,
            u"ancestro_dibujado": raw_anc,
            u"ancestro_resuelto": ar,
            u"codigo_activo_encontrado": u"no",
            u"match_status": u"sin_match",
            u"mensaje": u"codigo_activo no encontrado en modelo",
        }

    if len(ids) > 1:
        pkg, _st = resolve_btz_package(ak, anchor_map, asociacion_map)
        ar = u"sí" if pkg is not None else u"no"
        return {
            u"codigo_activo": raw_code,
            u"ancestro_dibujado": raw_anc,
            u"ancestro_resuelto": ar,
            u"codigo_activo_encontrado": u"multiple",
            u"match_status": u"multiple_match",
            u"mensaje": u"varios elementos con mismo codigo_activo; no se aplica",
        }

    eid = ids[0]
    el = doc.GetElement(eid)
    if el is None:
        return {
            u"codigo_activo": raw_code,
            u"ancestro_dibujado": raw_anc,
            u"ancestro_resuelto": u"n/a",
            u"codigo_activo_encontrado": u"no",
            u"match_status": u"sin_match",
            u"mensaje": u"ElementId inválido",
        }

    pkg, _st = resolve_btz_package(ak, anchor_map, asociacion_map)
    if pkg is None:
        return {
            u"codigo_activo": raw_code,
            u"ancestro_dibujado": raw_anc,
            u"ancestro_resuelto": u"no",
            u"codigo_activo_encontrado": u"sí",
            u"match_status": u"unresolved_anchor",
            u"mensaje": u"ancestro no resuelto (ni ancla Revit ni CSV asociación)",
        }

    return {
        u"codigo_activo": raw_code,
        u"ancestro_dibujado": raw_anc,
        u"ancestro_resuelto": u"sí",
        u"codigo_activo_encontrado": u"sí",
        u"match_status": u"ok",
        u"mensaje": u"listo para aplicar (misma lógica que aplicación)",
    }


def write_resolver_debug_artifacts(
    doc,
    p_asoc,
    asociacion_map,
    assign_rows,
    anchor_map,
    codigo_index,
    log_lines,
):
    """
    Genera CSV/TXT de diagnóstico sin tocar la lógica de aplicación.
    """
    p_anclas = get_public_file(DEBUG_ANCLAS, u"debug", fallback=False)
    p_resumen = get_public_file(DEBUG_ANCLAS_RESUMEN, u"debug", fallback=False)
    p_match = get_public_file(DEBUG_MATCH_ANCESTROS, u"debug", fallback=False)
    p_resol = get_public_file(DEBUG_RESOLUCION_ACTIVOS, u"debug", fallback=False)
    p_dbg_sum = get_public_file(DEBUG_SUMMARY, u"debug", fallback=False)

    anchor_records = collect_valid_anchor_records(doc)
    fields_anclas = [
        u"element_id",
        u"category",
        u"family",
        u"type",
        u"btz_01",
        u"btz_02",
        u"btz_03",
        u"btz_04",
        u"anchor_key_resuelta",
    ]
    with codecs.open(p_anclas, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=fields_anclas, lineterminator=u"\n")
        w.writeheader()
        for r in anchor_records:
            w.writerow(r)

    cnt_by_key = Counter()
    for r in anchor_records:
        cnt_by_key[r[u"anchor_key_resuelta"]] += 1
    fields_res = [u"anchor_key_resuelta", u"cantidad_elementos"]
    with codecs.open(p_resumen, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=fields_res, lineterminator=u"\n")
        w.writeheader()
        for k in sorted(cnt_by_key.keys()):
            w.writerow(
                {u"anchor_key_resuelta": k, u"cantidad_elementos": cnt_by_key[k]}
            )

    anchor_keys = set(anchor_map.keys())
    asoc_rows = load_asociacion_csv_all_rows(p_asoc)
    fields_match = [
        u"ancestro_dibujado",
        u"existe_en_modelo",
        u"cantidad_anclas_encontradas",
        u"btz_01_sugerido",
        u"btz_02_sugerido",
        u"btz_03_sugerido",
        u"btz_04_sugerido",
    ]
    with codecs.open(p_match, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=fields_match, lineterminator=u"\n")
        w.writeheader()
        for row in asoc_rows:
            raw_ad = _u(row.get(u"ancestro_dibujado", u""))
            ak = normalize_key(raw_ad)
            if ak:
                ex = u"sí" if ak in anchor_keys else u"no"
                nanch = cnt_by_key.get(ak, 0)
            else:
                ex = u"no"
                nanch = 0
            w.writerow(
                {
                    u"ancestro_dibujado": raw_ad,
                    u"existe_en_modelo": ex,
                    u"cantidad_anclas_encontradas": nanch,
                    u"btz_01_sugerido": _u(row.get(u"btz_01_sugerido", u"")),
                    u"btz_02_sugerido": _u(row.get(u"btz_02_sugerido", u"")),
                    u"btz_03_sugerido": _u(row.get(u"btz_03_sugerido", u"")),
                    u"btz_04_sugerido": _u(row.get(u"btz_04_sugerido", u"")),
                }
            )

    fields_diag = [
        u"codigo_activo",
        u"ancestro_dibujado",
        u"ancestro_resuelto",
        u"codigo_activo_encontrado",
        u"match_status",
        u"mensaje",
    ]
    diag_rows = []
    for row in assign_rows:
        diag_rows.append(
            _diagnostico_fila_asignacion(
                doc, row, anchor_map, asociacion_map, codigo_index
            )
        )
    with codecs.open(p_resol, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=fields_diag, lineterminator=u"\n")
        w.writeheader()
        for r in diag_rows:
            w.writerow(r)

    total_anclas = len(anchor_records)
    ancestros_csv_en_modelo = 0
    claves_asoc_en_modelo = set()
    for row in asoc_rows:
        ak = normalize_key(_u(row.get(u"ancestro_dibujado", u"")))
        if ak and ak in anchor_keys:
            ancestros_csv_en_modelo += 1
            claves_asoc_en_modelo.add(ak)

    filas_ancestro_resuelto = sum(
        1
        for r in diag_rows
        if r.get(u"ancestro_resuelto") == u"sí"
    )
    codigos_encontrados = sum(
        1 for r in diag_rows if r.get(u"codigo_activo_encontrado") == u"sí"
    )
    motivos = Counter()
    for r in diag_rows:
        motivos[r.get(u"mensaje", u"")] += 1
    top_motivos = motivos.most_common(12)

    lines = [
        u"DEBUG Resolver BTZ (diagnóstico; no modifica lógica de aplicación)",
        u"",
        u"Total elementos ancla válidos (regla BTZ_02 + BTZ_03/04): {0}".format(
            total_anclas
        ),
        u"Claves anchor_key distintas en modelo: {0}".format(len(anchor_keys)),
        u"",
        u"Filas en CSV asociación (por línea): {0}".format(len(asoc_rows)),
        u"Filas CSV asociación con ancestro_dibujado presente en modelo (clave): {0}".format(
            ancestros_csv_en_modelo
        ),
        u"Ancestros distintos (CSV) que aparecen en modelo: {0}".format(
            len(claves_asoc_en_modelo)
        ),
        u"",
        u"Filas en CSV asignación: {0}".format(len(assign_rows)),
        u"Filas con ancestro resuelto (resolve_btz_package): {0}".format(
            filas_ancestro_resuelto
        ),
        u"Filas con codigo_activo encontrado 1:1 en Revit: {0}".format(
            codigos_encontrados
        ),
        u"",
        u"Principales motivos (mensaje) en debug_resolucion_activos:",
    ]
    for m, c in top_motivos:
        lines.append(u"  {0} x{1}".format(m, c))
    lines.extend(
        [
            u"",
            u"Archivos:",
            u"  {0}".format(p_anclas),
            u"  {0}".format(p_resumen),
            u"  {0}".format(p_match),
            u"  {0}".format(p_resol),
            u"  {0}".format(p_dbg_sum),
        ]
    )

    with codecs.open(p_dbg_sum, u"w", encoding=u"utf-8-sig") as fp:
        fp.write(u"\n".join(lines) + u"\n")

    log_lines.append(u"Diagnóstico debug escrito en public/:")
    log_lines.append(u"  {0}".format(DEBUG_ANCLAS))
    log_lines.append(u"  {0}".format(DEBUG_ANCLAS_RESUMEN))
    log_lines.append(u"  {0}".format(DEBUG_MATCH_ANCESTROS))
    log_lines.append(u"  {0}".format(DEBUG_RESOLUCION_ACTIVOS))
    log_lines.append(u"  {0}".format(DEBUG_SUMMARY))


def element_has_any_btz(el):
    return any(_u(_param_value_as_string(el, p)) for p in PARAM_BTZ)


def apply_btz_four(el, vals):
    errs = []
    for i, pname in enumerate(PARAM_BTZ):
        ok, err = set_text_parameter(el, pname, vals[i])
        if not ok:
            errs.append(u"{0}: {1}".format(pname, err or u"?"))
    return len(errs) == 0, errs


def run_resolver_btz_automatico(doc, log_lines=None):
    if log_lines is None:
        log_lines = []

    _ensure_public_dir()
    p_asoc = os.path.join(PUBLIC_DIR, CSV_ASOCIACION)
    p_asig = os.path.join(PUBLIC_DIR, CSV_ASIGNACION)
    p_out = os.path.join(PUBLIC_DIR, OUT_RESULTS)
    p_sum = os.path.join(PUBLIC_DIR, OUT_SUMMARY)

    if not os.path.isfile(p_asoc):
        raise IOError(u"No existe: {0}".format(p_asoc))
    if not os.path.isfile(p_asig):
        raise IOError(u"No existe: {0}".format(p_asig))

    ensure_btz_shared_parameters(doc, log_lines)

    asociacion_map = load_asociacion_csv(p_asoc)
    assign_rows = load_asignacion_csv(p_asig)
    if not assign_rows:
        log_lines.append(
            u"AVISO: asignacion_automatica_sugerida.csv no tiene filas de datos "
            u"(solo cabecera o archivo vacío). No se aplicará BTZ a ningún activo."
        )

    anchor_map, anchor_conflicts = build_anchor_map_from_revit(doc, log_lines)
    codigo_index, idx_stats = build_codigo_activo_index(doc, log_lines)

    if idx_stats.get(u"model_elements", 0) == 0:
        raise ValueError(u"No hay elementos de modelo para indexar.")

    write_resolver_debug_artifacts(
        doc,
        p_asoc,
        asociacion_map,
        assign_rows,
        anchor_map,
        codigo_index,
        log_lines,
    )

    asociacion_keys = set(asociacion_map.keys())
    anchor_keys = set(anchor_map.keys())
    csv_asociacion_sin_ancla = sorted(asociacion_keys - anchor_keys)

    result_rows = []
    total_filas = len(assign_rows)
    activos_encontrados = 0
    activos_actualizados = 0
    activos_sin_match = 0
    multiple_match = 0
    unresolved_anchor = 0
    errores_escritura = 0
    sobrescritos = 0

    tx = Transaction(doc, u"BTZ | Resolver automático")
    tx.Start()
    try:
        for row in assign_rows:
            raw_code = _u(row.get(u"codigo_activo", u""))
            raw_anc = _u(row.get(u"ancestro_dibujado", u""))
            ck = normalize_key(raw_code)
            ak = normalize_key(raw_anc)

            if not ck:
                result_rows.append(
                    {
                        u"codigo_activo": raw_code,
                        u"element_id": u"",
                        u"ancestro_dibujado": raw_anc,
                        u"match_status": u"sin_match",
                        u"anchor_status": u"n/a",
                        u"btz_01": u"",
                        u"btz_02": u"",
                        u"btz_03": u"",
                        u"btz_04": u"",
                        u"mensaje": u"fila sin codigo_activo",
                    }
                )
                activos_sin_match += 1
                continue

            if not ak:
                unresolved_anchor += 1
                result_rows.append(
                    {
                        u"codigo_activo": raw_code,
                        u"element_id": u"",
                        u"ancestro_dibujado": raw_anc,
                        u"match_status": u"unresolved_anchor",
                        u"anchor_status": u"unresolved_anchor",
                        u"btz_01": u"",
                        u"btz_02": u"",
                        u"btz_03": u"",
                        u"btz_04": u"",
                        u"mensaje": u"fila sin ancestro_dibujado",
                    }
                )
                continue

            ids = codigo_index.get(ck, [])
            if not ids:
                result_rows.append(
                    {
                        u"codigo_activo": raw_code,
                        u"element_id": u"",
                        u"ancestro_dibujado": raw_anc,
                        u"match_status": u"sin_match",
                        u"anchor_status": u"n/a",
                        u"btz_01": u"",
                        u"btz_02": u"",
                        u"btz_03": u"",
                        u"btz_04": u"",
                        u"mensaje": u"codigo_activo no encontrado en modelo",
                    }
                )
                activos_sin_match += 1
                continue

            if len(ids) > 1:
                multiple_match += 1
                eid_str = u";".join(_element_id_str(i) for i in ids[:25])
                result_rows.append(
                    {
                        u"codigo_activo": raw_code,
                        u"element_id": eid_str,
                        u"ancestro_dibujado": raw_anc,
                        u"match_status": u"multiple_match",
                        u"anchor_status": u"n/a",
                        u"btz_01": u"",
                        u"btz_02": u"",
                        u"btz_03": u"",
                        u"btz_04": u"",
                        u"mensaje": u"varios elementos con mismo codigo_activo; no se aplica",
                    }
                )
                continue

            eid = ids[0]
            el = doc.GetElement(eid)
            if el is None:
                activos_sin_match += 1
                result_rows.append(
                    {
                        u"codigo_activo": raw_code,
                        u"element_id": u"",
                        u"ancestro_dibujado": raw_anc,
                        u"match_status": u"sin_match",
                        u"anchor_status": u"n/a",
                        u"btz_01": u"",
                        u"btz_02": u"",
                        u"btz_03": u"",
                        u"btz_04": u"",
                        u"mensaje": u"ElementId inválido",
                    }
                )
                continue

            activos_encontrados += 1

            pkg, ast = resolve_btz_package(ak, anchor_map, asociacion_map)
            if pkg is None:
                unresolved_anchor += 1
                result_rows.append(
                    {
                        u"codigo_activo": raw_code,
                        u"element_id": _element_id_str(eid),
                        u"ancestro_dibujado": raw_anc,
                        u"match_status": u"unresolved_anchor",
                        u"anchor_status": u"unresolved_anchor",
                        u"btz_01": u"",
                        u"btz_02": u"",
                        u"btz_03": u"",
                        u"btz_04": u"",
                        u"mensaje": u"ancestro no resuelto (ni ancla Revit ni CSV asociación)",
                    }
                )
                continue

            prev = element_has_any_btz(el)
            ok, errs = apply_btz_four(el, list(pkg))
            msg_parts = []
            if prev:
                sobrescritos += 1
                msg_parts.append(u"sobrescrito_BTZ_previo")
            if not ok:
                errores_escritura += 1
                msg_parts.append(u" | ".join(errs))
                mst = u"error_escritura"
            else:
                activos_actualizados += 1
                mst = u"ok"

            result_rows.append(
                {
                    u"codigo_activo": raw_code,
                    u"element_id": _element_id_str(eid),
                    u"ancestro_dibujado": raw_anc,
                    u"match_status": mst,
                    u"anchor_status": ast,
                    u"btz_01": pkg[0],
                    u"btz_02": pkg[1],
                    u"btz_03": pkg[2],
                    u"btz_04": pkg[3],
                    u"mensaje": u"; ".join(msg_parts) if msg_parts else u"",
                }
            )

        tx.Commit()
    except Exception:
        if tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
        raise

    fields = [
        u"codigo_activo",
        u"element_id",
        u"ancestro_dibujado",
        u"match_status",
        u"anchor_status",
        u"btz_01",
        u"btz_02",
        u"btz_03",
        u"btz_04",
        u"mensaje",
    ]
    with codecs.open(p_out, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=fields, lineterminator=u"\n")
        w.writeheader()
        for r in result_rows:
            w.writerow(r)

    summary = [
        u"Resolver BTZ automático",
        u"Asociación: {0}".format(p_asoc),
        u"Asignación: {0}".format(p_asig),
        u"",
    ]
    if total_filas == 0:
        summary.append(
            u"AVISO: CSV de asignación sin filas — rellenar codigo_activo y ancestro_dibujado, etc."
        )
        summary.append(u"")
    summary.extend(
        [
        u"Total filas CSV asignación: {0}".format(total_filas),
        u"Activos encontrados en Revit (match 1:1): {0}".format(activos_encontrados),
        u"Activos actualizados (escritura OK): {0}".format(activos_actualizados),
        u"Activos sin match (sin codigo / sin elemento / error): {0}".format(activos_sin_match),
        u"Filas multiple_match (no aplicado): {0}".format(multiple_match),
        u"Filas unresolved_anchor o sin ancestro: {0}".format(unresolved_anchor),
        u"Anclas detectadas en modelo (claves): {0}".format(len(anchor_keys)),
        u"Anclas CSV asociación sin geometría ancla en modelo: {0}".format(len(csv_asociacion_sin_ancla)),
        u"Conflictos paquete ancla duplicado: {0}".format(anchor_conflicts),
        u"Sobrescrituras BTZ previo: {0}".format(sobrescritos),
        u"Errores escritura: {0}".format(errores_escritura),
        u"",
        u"Resultados: {0}".format(p_out),
        ]
    )

    with codecs.open(p_sum, u"w", encoding=u"utf-8-sig") as fp:
        fp.write(u"\n".join(summary) + u"\n")

    log_lines.extend(summary)

    return {
        u"path_results": p_out,
        u"path_summary": p_sum,
        u"total_filas": total_filas,
        u"activos_encontrados": activos_encontrados,
        u"activos_actualizados": activos_actualizados,
        u"activos_sin_match": activos_sin_match,
        u"multiple_match": multiple_match,
        u"unresolved_anchor": unresolved_anchor,
        u"ancestros_modelo": len(anchor_keys),
        u"csv_asociacion_sin_ancla": len(csv_asociacion_sin_ancla),
    }
