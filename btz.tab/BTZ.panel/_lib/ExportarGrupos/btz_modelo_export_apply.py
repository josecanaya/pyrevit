# -*- coding: utf-8 -*-
"""
Exportación de modelo BTZ a CSV (solo lectura) y aplicación desde CSV confirmado.
"""
from __future__ import print_function

import codecs
import csv
import datetime
import os
import re
import shutil
import unicodedata
from collections import OrderedDict

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    ElementId,
    FamilySymbol,
    FilteredElementCollector,
    BuiltInParameter,
    CategoryType,
    Transaction,
    TransactionStatus,
)
from System import Int64

from btz_apply_webhook import (
    PARAM_NUMERIC,
    PARAM_NUMERO_ACTIVO,
    PARAM_ESTADO_ASOCIACION,
    PARAM_ORIGEN_ASOCIACION,
    PARAM_FECHA_ASOCIACION,
    set_text_parameter,
    ensure_btz_shared_parameters,
)
from btz_paths import PUBLIC_DIR, ensure_public_layout

try:
    unicode
except NameError:
    unicode = str

CSV_EXPORT_NAME = u"modelo_btz_export.csv"
CSV_EXPORT_ACTIVOS_NAME = u"modelo_btz_export_activos.csv"
CSV_EXPORT_TODO_MODELO_NAME = u"modelo_btz_export_todo_modelo.csv"
CSV_EXPORT_P10_NAME = u"modelo_btz_export_p10.csv"
CSV_EXPORT_CON_BTZ_NAME = u"modelo_btz_export_con_btz.csv"
CSV_EXPORT_INCONSISTENCIAS_NAME = u"modelo_btz_export_inconsistencias.csv"
CSV_EXPORT_POR_PLANTA_NAME = u"modelo_btz_export_por_planta.csv"
SUMMARY_EXPORT_NAME = u"modelo_btz_export_summary.txt"
CSV_CONFIRMADO_NAME = u"match_project_revit_confirmado.csv"
RESULTS_APPLY_NAME = u"aplicar_btz_confirmado_results.csv"
SUMMARY_APPLY_NAME = u"aplicar_btz_confirmado_summary.txt"
ORIGEN_CSV_LITERAL = u"match_project_revit_confirmado.csv"
CSV_CORREGIR_IN_NAME = u"asociacion_contenedor_hijos_final_p10.csv"
RESULTS_CORREGIR_NAME = u"corregir_btz_confirmado_results.csv"
SUMMARY_CORREGIR_NAME = u"corregir_btz_confirmado_summary.txt"
POR_CONTENEDOR_CORREGIR_NAME = u"corregir_btz_confirmado_por_contenedor.csv"
DEBUG_CORREGIR_FUENTE_NAME = u"debug_corregir_btz_fuente.csv"
DEBUG_CORREGIR_POR_CONTENEDOR_FUENTE_NAME = u"debug_corregir_btz_por_contenedor_fuente.csv"
DEBUG_SECTORES_NO_ASOCIADOS_NAME = u"debug_sectores_no_asociados_p10.csv"
ORIGEN_CORREGIR_LITERAL = u"asociacion_contenedor_hijos_final_p10.csv"
DRY_RUN_CORREGIR = False

CORREGIR_CODE_KEYS = (u"codigo_project", u"codigo", u"task_name", u"Task/Name")
CORREGIR_EID_KEYS = (
    u"element_id_contenedor",
    u"contenedor_sugerido_element_id",
    u"element_id_revit",
    u"element_id",
)
CORREGIR_UID_KEYS = (
    u"unique_id_contenedor",
    u"contenedor_sugerido_unique_id",
    u"unique_id_revit",
    u"unique_id",
)
CORREGIR_PATH_KEYS = (
    u"btz_path_contenedor",
    u"contenedor_sugerido_path",
    u"btz_path_actual",
    u"btz_path_detectado",
)
DEBUG_SECTOR_TERMS = (
    u"PRL",
    u"PRELIMPIEZA",
    u"IZAJE",
    u"SEGURIDAD",
    u"SEG",
    u"HRN-ENF-EG01",
    u"LAMINADORES",
    u"EXPANDIDO",
)

_ESTADOS_APLICABLES = frozenset([u"confirmado", u"match_ok"])
_EXCLUDED_CATEGORY_NAMES = frozenset(
    [
        u"<sketch>",
        u"phases",
        u"project information",
        u"project phase information",
        u"views",
        u"levels",
        u"grids",
        u"sheets",
        u"rvt links",
        u"revit links",
        u"cad links",
        u"cad imports",
        u"imports in families",
        u"legend components",
        u"material assets",
        u"materials",
        u"sun path",
        u"internal origin",
        u"project base point",
        u"survey point",
        u"hvac zones",
        u"primary contours",
    ]
)
_ASSET_CATEGORY_ALLOWLIST = frozenset(
    [
        u"generic models",
        u"modelos genéricos",
        u"modelos genericos",
        u"walls",
        u"muros",
        u"floors",
        u"suelos",
        u"pisos",
        u"roofs",
        u"cubiertas",
        u"tejados",
    ]
)
_PLANTAS_EXPORT_PROJECT = (u"P10", u"PP", u"TE", u"PR")
_PLANTAS_APLICAR_CONFIRMADO = (u"P10", u"TE", u"PP", u"PR")
_PLANTAS_VALIDAS = frozenset(list(_PLANTAS_EXPORT_PROJECT) + [u"SL", u"AV", u"RC"])


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


def _norm_key_csv(h):
    if h is None:
        return u""
    return unicodedata.normalize("NFC", _u(h)).lower()


def _norm_cell_csv(val):
    s = _u(val)
    if not s:
        return u""
    s = s.replace(u"\r\n", u" ").replace(u"\n", u" ").replace(u"\r", u" ")
    while u"  " in s:
        s = s.replace(u"  ", u" ")
    return s.strip()


def _norm_name_key(val):
    return _u(val).lower()


def _contains_p10(val):
    return u"P10" in _u(val).upper()


def _is_p10_element(btz_numero_activo, desc_vals, path_det):
    desc_01 = _u(desc_vals[0]).upper() if desc_vals else u""
    if desc_01 == u"P10":
        return True
    if _u(btz_numero_activo).upper().startswith(u"P10-"):
        return True
    if any(u"P10-" in _u(x).upper() for x in desc_vals):
        return True
    if u"P10-" in _u(path_det).upper():
        return True
    return False


def _contains_plant(val, plant):
    s = _u(val).upper()
    if not s:
        return False
    pattern = r"(^|[^A-Z0-9]){0}($|[^A-Z0-9])".format(re.escape(plant))
    return re.search(pattern, s) is not None


def _has_btz(desc_vals):
    return any(_u(x) for x in desc_vals)


def _has_btz_or_numero_activo(desc_vals, btz_numero_activo):
    return _has_btz(desc_vals) or bool(_u(btz_numero_activo))


def _has_btz_raw_issue(raw_vals):
    for raw in raw_vals:
        s = _u(raw)
        if not s:
            continue
        if u"\r" in s or u"\n" in s or u"  " in s:
            return True
        if u">" in s and u" > " not in s:
            return True
        if u"|" in s or u";" in s:
            return True
    return False


def _is_generic_model(cat_name):
    nk = _norm_name_key(cat_name)
    return nk in (u"generic models", u"modelos genéricos", u"modelos genericos")


def _is_model_category_element(element):
    try:
        cat = element.Category
    except Exception:
        cat = None
    if cat is None:
        return False
    try:
        if cat.CategoryType != CategoryType.Model:
            return False
    except Exception:
        return False
    return True


def _is_hard_excluded_category(cat_name):
    cat_key = _norm_name_key(cat_name)
    if cat_key in _EXCLUDED_CATEGORY_NAMES:
        return True
    if (u"revit link" in cat_key or u"rvt link" in cat_key):
        return True
    return False


def _should_export_todo_modelo(element, cat_name):
    """Export amplio de diagnóstico: instancias con categoría Model, sin categorías internas obvias."""
    if not _is_model_category_element(element):
        return False
    if _is_hard_excluded_category(cat_name):
        return False
    return True


def _should_export_activo(element, cat_name, desc_vals, btz_numero_activo):
    """Solo categorías útiles para asociación de activos Project/Revit."""
    if not _should_export_todo_modelo(element, cat_name):
        return False

    cat_key = _norm_name_key(cat_name)
    has_btz_info = _has_btz_or_numero_activo(desc_vals, btz_numero_activo)

    if cat_key in _ASSET_CATEGORY_ALLOWLIST:
        return True
    if cat_key == u"cameras":
        return has_btz_info
    if cat_key == u"pipe segments":
        return has_btz_info
    if (u"cad" in cat_key or u"import" in cat_key) and not (
        _is_generic_model(cat_name) and has_btz_info
    ):
        return False
    return has_btz_info


def _planta_para_conteo(desc_vals, btz_numero_activo, path_det):
    d1 = _u(desc_vals[0]).upper() if desc_vals else u""
    if d1 in _PLANTAS_VALIDAS:
        return d1
    if d1:
        return u"INVALIDO: {0}".format(desc_vals[0])
    scan_vals = [btz_numero_activo, path_det] + list(desc_vals)
    for planta in sorted(_PLANTAS_VALIDAS):
        if any(_contains_plant(v, planta) for v in scan_vals):
            return planta
    return u"(sin planta)"


def _increment_por_planta(stats, planta, has_btz):
    rec = stats.setdefault(
        planta,
        {u"cantidad_elementos": 0, u"cantidad_con_btz": 0, u"cantidad_sin_btz": 0},
    )
    rec[u"cantidad_elementos"] += 1
    if has_btz:
        rec[u"cantidad_con_btz"] += 1
    else:
        rec[u"cantidad_sin_btz"] += 1


def _detect_inconsistencias(row_dict, desc_vals, raw_vals):
    issues = []
    d1 = _u(desc_vals[0]).upper() if desc_vals else u""
    rest = desc_vals[1:]

    if d1 and d1 not in _PLANTAS_VALIDAS:
        issues.append(
            u"BTZ_Description_01 no es planta válida ({0})".format(desc_vals[0])
        )

    if not d1 and any(_u(x) for x in rest):
        issues.append(u"BTZ_Description_01 vacío con otros BTZ cargados")

    if d1 == u"TE" and any(_contains_plant(x, u"P10") for x in rest):
        issues.append(u"BTZ_Description_01=TE pero otro BTZ contiene P10")
    if d1 == u"PP" and any(_contains_plant(x, u"P10") for x in rest):
        issues.append(u"BTZ_Description_01=PP pero otro BTZ contiene P10")
    if d1 == u"P10" and any(
        _contains_plant(x, u"TE") or _contains_plant(x, u"PP") for x in rest
    ):
        issues.append(u"BTZ_Description_01=P10 pero otro BTZ contiene TE o PP")

    plants = set()
    for v in desc_vals:
        for plant in (u"P10", u"TE", u"PP"):
            if _contains_plant(v, plant):
                plants.add(plant)
    if len(plants) > 1:
        issues.append(u"btz_path_detectado mezcla plantas: {0}".format(u", ".join(sorted(plants))))

    all_raw = list(raw_vals) + [row_dict.get(u"btz_path_detectado", u"")]
    if _has_btz_raw_issue(all_raw):
        issues.append(u"valores BTZ con saltos, espacios dobles o separadores inconsistentes")

    return issues


def _write_csv(path, header, rows):
    with codecs.open(path, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=header, lineterminator=u"\n")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _element_id_str(eid):
    try:
        if hasattr(eid, u"Value"):
            return unicode(int(eid.Value))
        return unicode(int(eid.IntegerValue))
    except Exception:
        return u""


def _element_id_from_int(value):
    """Evita ambigüedad entre sobrecargas ElementId(enum/int) en pyRevit."""
    return ElementId(Int64(int(value)))


def _param_display(param):
    if param is None or not param.HasValue:
        return u""
    try:
        s = param.AsString()
        if s is not None and _u(s):
            return _u(s)
    except Exception:
        pass
    try:
        vs = param.AsValueString()
        if vs is not None and _u(vs):
            return _u(vs)
    except Exception:
        pass
    return u""


def _get_param_instance_or_type(doc, element, param_name):
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


def _safe_type_display_name(elem_type):
    if elem_type is None:
        return u""
    for bip in (
        BuiltInParameter.SYMBOL_NAME_PARAM,
        BuiltInParameter.ALL_MODEL_TYPE_NAME,
    ):
        try:
            p = elem_type.get_Parameter(bip)
            if p is not None and p.HasValue:
                s = p.AsString()
                if s:
                    return unicode(s)
        except Exception:
            pass
    try:
        n = elem_type.Name
        if n is not None:
            return unicode(n)
    except Exception:
        pass
    return u""


def _safe_family_display_name(fam):
    if fam is None:
        return u""
    try:
        n = fam.Name
        if n is not None:
            return unicode(n)
    except Exception:
        pass
    try:
        p = fam.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
        if p is not None and p.HasValue:
            s = p.AsString()
            if s:
                return unicode(s)
    except Exception:
        pass
    return u""


def _safe_category_name(element):
    try:
        cat = element.Category
        return unicode(cat.Name) if cat is not None else u""
    except Exception:
        return u""


def _family_and_type_names(doc, element):
    family_name = u""
    type_name = u""
    try:
        tid = element.GetTypeId()
    except Exception:
        tid = None
    if tid and tid != ElementId.InvalidElementId:
        et = doc.GetElement(tid)
        if et is not None:
            type_name = _safe_type_display_name(et)
            if isinstance(et, FamilySymbol):
                fam = et.Family
                family_name = _safe_family_display_name(fam)
                if not family_name:
                    try:
                        p = et.get_Parameter(
                            BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM
                        )
                        if p is not None and p.HasValue:
                            family_name = _u(p.AsString() or u"")
                    except Exception:
                        pass
    return family_name, type_name


def _element_instance_name(element):
    try:
        n = element.Name
        if n:
            return unicode(n)
    except Exception:
        pass
    try:
        p = element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_NAME)
        if p is not None and p.HasValue:
            s = p.AsString()
            if s:
                return unicode(s)
    except Exception:
        pass
    return u""


def _builtin_instance_then_type(doc, element, bip):
    if bip is None:
        return u""
    try:
        p = element.get_Parameter(bip)
        v = _param_display(p)
        if v:
            return v
    except Exception:
        pass
    try:
        tid = element.GetTypeId()
        if tid and tid != ElementId.InvalidElementId:
            t = doc.GetElement(tid)
            if t is not None:
                p = t.get_Parameter(bip)
                return _param_display(p)
    except Exception:
        pass
    return u""


def _export_csv_header():
    h = [
        u"element_id",
        u"unique_id",
        u"category",
        u"family",
        u"type",
        u"name",
        u"mark",
        u"comments",
        u"btz_numero_activo",
    ]
    for i in range(1, 81):
        h.append(u"btz_description_{:02d}".format(i))
    h.extend([u"btz_path_detectado", u"cantidad_btz_description_con_valor"])
    return h


def run_export_modelo_btz(doc, log_lines=None):
    """Recorre instancias del documento y escribe public/modelo_btz_export.csv (solo lectura)."""
    if log_lines is None:
        log_lines = []

    ensure_public_layout()
    out_csv = os.path.join(PUBLIC_DIR, CSV_EXPORT_NAME)
    out_activos_csv = os.path.join(PUBLIC_DIR, CSV_EXPORT_ACTIVOS_NAME)
    out_todo_modelo_csv = os.path.join(PUBLIC_DIR, CSV_EXPORT_TODO_MODELO_NAME)
    out_p10_csv = os.path.join(PUBLIC_DIR, CSV_EXPORT_P10_NAME)
    out_por_planta_project = dict(
        (planta, os.path.join(PUBLIC_DIR, u"modelo_btz_export_{0}.csv".format(planta.lower())))
        for planta in _PLANTAS_EXPORT_PROJECT
    )
    out_con_btz_csv = os.path.join(PUBLIC_DIR, CSV_EXPORT_CON_BTZ_NAME)
    out_inconsistencias_csv = os.path.join(PUBLIC_DIR, CSV_EXPORT_INCONSISTENCIAS_NAME)
    out_por_planta_csv = os.path.join(PUBLIC_DIR, CSV_EXPORT_POR_PLANTA_NAME)
    out_txt = os.path.join(PUBLIC_DIR, SUMMARY_EXPORT_NAME)

    header = _export_csv_header()
    btz_col_keys = [u"btz_description_{:02d}".format(i) for i in range(1, 81)]

    rows_activos = []
    rows_todo_modelo = []
    rows_p10 = []
    rows_por_planta_project = dict((planta, []) for planta in _PLANTAS_EXPORT_PROJECT)
    rows_con_btz = []
    rows_inconsistencias = []
    rows_por_planta = []
    total_before_filters = 0
    total_todo_modelo = 0
    total_activos = 0
    con_alguno = 0
    p10_todo_modelo = 0
    p10_activos = 0
    por_slot = {p: 0 for p in PARAM_NUMERIC}
    por_btz_01 = {}
    por_categoria = {}
    por_planta = {}

    collector = FilteredElementCollector(doc).WhereElementIsNotElementType()

    for el in collector:
        try:
            total_before_filters += 1
            eid = _element_id_str(el.Id)
            try:
                uid = _u(el.UniqueId)
            except Exception:
                uid = u""

            cat = _safe_category_name(el)
            desc_vals = []
            desc_raw_vals = []
            for i, pname in enumerate(PARAM_NUMERIC):
                p = _get_param_instance_or_type(doc, el, pname)
                raw = _param_display(p)
                norm = _norm_cell_csv(raw)
                desc_vals.append(norm)

                try:
                    desc_raw_vals.append(unicode(raw or u""))
                except Exception:
                    desc_raw_vals.append(u"")

            if not _should_export_todo_modelo(el, cat):
                continue

            fam, typ = _family_and_type_names(doc, el)
            name = _element_instance_name(el)
            mark = _norm_cell_csv(
                _builtin_instance_then_type(doc, el, BuiltInParameter.ALL_MODEL_MARK)
            )
            comments = _norm_cell_csv(
                _builtin_instance_then_type(
                    doc, el, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS
                )
            )

            p_na = _get_param_instance_or_type(doc, el, PARAM_NUMERO_ACTIVO)
            btz_num = _norm_cell_csv(_param_display(p_na))

            cantidad = sum(1 for x in desc_vals if x)

            partes_path = [x for x in desc_vals if x]
            path_det = u" > ".join(partes_path)

            row = {
                u"element_id": eid,
                u"unique_id": uid,
                u"category": cat,
                u"family": fam,
                u"type": typ,
                u"name": _norm_cell_csv(name),
                u"mark": mark,
                u"comments": comments,
                u"btz_numero_activo": btz_num,
                u"btz_path_detectado": path_det,
                u"cantidad_btz_description_con_valor": unicode(cantidad),
            }
            for i, key in enumerate(btz_col_keys):
                row[key] = desc_vals[i]

            total_todo_modelo += 1
            rows_todo_modelo.append(row)

            is_p10 = _is_p10_element(btz_num, desc_vals, path_det)
            if is_p10:
                p10_todo_modelo += 1

            if not _should_export_activo(el, cat, desc_vals, btz_num):
                continue

            total_activos += 1
            rows_activos.append(row)

            cat_key = cat or u"(sin categoría)"
            por_categoria[cat_key] = por_categoria.get(cat_key, 0) + 1
            btz01_key = desc_vals[0] or u"(vacío)"
            por_btz_01[btz01_key] = por_btz_01.get(btz01_key, 0) + 1
            for i, val in enumerate(desc_vals):
                if val:
                    por_slot[PARAM_NUMERIC[i]] += 1

            planta_conteo = _planta_para_conteo(desc_vals, btz_num, path_det)
            _increment_por_planta(por_planta, planta_conteo, cantidad > 0)
            if planta_conteo in rows_por_planta_project:
                rows_por_planta_project[planta_conteo].append(row)

            if is_p10:
                p10_activos += 1
                rows_p10.append(row)
            if cantidad > 0:
                con_alguno += 1
                rows_con_btz.append(row)

            issues = _detect_inconsistencias(row, desc_vals, desc_raw_vals)
            if issues:
                inc_row = dict(row)
                inc_row[u"inconsistencia_tipo"] = u" | ".join(issues)
                inc_row[u"inconsistencia_mensaje"] = u"Revisar clasificación BTZ plana del elemento"
                rows_inconsistencias.append(inc_row)
        except Exception:
            continue

    for planta in sorted(por_planta.keys()):
        rec = por_planta[planta]
        rows_por_planta.append(
            {
                u"planta": planta,
                u"cantidad_elementos": rec[u"cantidad_elementos"],
                u"cantidad_con_btz": rec[u"cantidad_con_btz"],
                u"cantidad_sin_btz": rec[u"cantidad_sin_btz"],
            }
        )

    # Backcompat: el CSV histórico queda como export de activos.
    _write_csv(out_csv, header, rows_activos)
    _write_csv(out_activos_csv, header, rows_activos)
    _write_csv(out_todo_modelo_csv, header, rows_todo_modelo)
    _write_csv(out_p10_csv, header, rows_p10)
    for planta in _PLANTAS_EXPORT_PROJECT:
        _write_csv(out_por_planta_project[planta], header, rows_por_planta_project[planta])
    _write_csv(out_con_btz_csv, header, rows_con_btz)
    _write_csv(
        out_inconsistencias_csv,
        header + [u"inconsistencia_tipo", u"inconsistencia_mensaje"],
        rows_inconsistencias,
    )
    _write_csv(
        out_por_planta_csv,
        [u"planta", u"cantidad_elementos", u"cantidad_con_btz", u"cantidad_sin_btz"],
        rows_por_planta,
    )

    lines_sum = [
        u"Exportar Modelo BTZ",
        u"fecha: {0}".format(
            datetime.datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")
        ),
        u"",
        u"total elementos escaneados antes de filtros: {0}".format(total_before_filters),
        u"total elementos exportados en todo_modelo: {0}".format(total_todo_modelo),
        u"total elementos exportados en activos: {0}".format(total_activos),
        u"total elementos con BTZ en activos: {0}".format(con_alguno),
        u"total elementos P10 en activos: {0}".format(p10_activos),
        u"total elementos P10 en todo_modelo: {0}".format(p10_todo_modelo),
        u"total inconsistencias detectadas: {0}".format(len(rows_inconsistencias)),
        u"",
        u"conteo por BTZ_Description_01:",
    ]
    for key in sorted(por_btz_01.keys()):
        lines_sum.append(u"  {0}: {1}".format(key, por_btz_01[key]))
    lines_sum.extend(
        [
            u"",
            u"conteo por categoría:",
        ]
    )
    for key in sorted(por_categoria.keys()):
        lines_sum.append(u"  {0}: {1}".format(key, por_categoria[key]))
    lines_sum.extend(
        [
            u"",
            u"conteo por cada BTZ_Description_01..80:",
        ]
    )
    for pname in PARAM_NUMERIC:
        lines_sum.append(u"  {0}: {1}".format(pname, por_slot[pname]))
    lines_sum.extend(
        [
            u"",
            u"rutas CSV generadas:",
            u"  activos/backcompat: {0}".format(out_csv),
            u"  activos: {0}".format(out_activos_csv),
            u"  todo_modelo: {0}".format(out_todo_modelo_csv),
            u"  P10 activos: {0}".format(out_p10_csv),
            u"  PP activos: {0}".format(out_por_planta_project[u"PP"]),
            u"  TE activos: {0}".format(out_por_planta_project[u"TE"]),
            u"  PR activos: {0}".format(out_por_planta_project[u"PR"]),
            u"  con BTZ activos: {0}".format(out_con_btz_csv),
            u"  inconsistencias activos: {0}".format(out_inconsistencias_csv),
            u"  por planta activos: {0}".format(out_por_planta_csv),
        ]
    )

    with codecs.open(out_txt, u"w", encoding=u"utf-8") as fp:
        fp.write(u"\n".join(lines_sum) + u"\n")

    log_lines.append(u"Export BTZ activos: {0} filas -> {1}".format(len(rows_activos), out_csv))
    return {
        u"csv_out": out_csv,
        u"csv_activos_out": out_activos_csv,
        u"csv_todo_modelo_out": out_todo_modelo_csv,
        u"csv_p10_out": out_p10_csv,
        u"csv_pp_out": out_por_planta_project[u"PP"],
        u"csv_te_out": out_por_planta_project[u"TE"],
        u"csv_pr_out": out_por_planta_project[u"PR"],
        u"csv_con_btz_out": out_con_btz_csv,
        u"csv_inconsistencias_out": out_inconsistencias_csv,
        u"csv_por_planta_out": out_por_planta_csv,
        u"summary_out": out_txt,
        u"total_before_filters": total_before_filters,
        u"total_todo_modelo": total_todo_modelo,
        u"total_activos": total_activos,
        u"con_btz": con_alguno,
        u"p10": p10_activos,
        u"pp": len(rows_por_planta_project[u"PP"]),
        u"te": len(rows_por_planta_project[u"TE"]),
        u"pr": len(rows_por_planta_project[u"PR"]),
        u"p10_todo_modelo": p10_todo_modelo,
        u"inconsistencias": len(rows_inconsistencias),
    }


def _row_norm_map(raw_row):
    return {_norm_key_csv(k): v for k, v in raw_row.items() if k is not None}


def _row_get(norm_row, *keys):
    for k in keys:
        nk = _norm_key_csv(k)
        if nk in norm_row:
            return norm_row[nk]
    return u""


def _row_has_any(norm_row, keys):
    for k in keys:
        if _norm_key_csv(k) in norm_row:
            return True
    return False


def _detected_columns(norm_row, aliases_by_label):
    labels = []
    for label, keys in aliases_by_label:
        if _row_has_any(norm_row, keys):
            labels.append(label)
    return u";".join(labels)


def _write_dict_csv(path, fields, rows):
    with codecs.open(path, u"w", encoding=u"utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields, lineterminator=u"\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, u"") for f in fields})


def _parse_element_id_from_row(norm_row):
    s = _u(_row_get(norm_row, u"element_id", u"elementid"))
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return None


def _bool_limpiar(norm_row):
    v = _u(_row_get(norm_row, u"limpiar_valores")).lower()
    return v == u"si"


def _current_btz_values(element):
    values = OrderedDict()
    for pname in PARAM_NUMERIC:
        try:
            p = element.LookupParameter(pname)
        except Exception:
            p = None
        values[pname] = _norm_cell_csv(_param_display(p))
    return values


def _write_corregir_rows(csv_out, result_rows):
    fields = [
        u"element_id",
        u"unique_id",
        u"btz_path_contenedor",
        u"codigo_project",
        u"estado_correccion",
        u"btz_description_slot_usado",
        u"mensaje",
    ]
    with codecs.open(csv_out, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=fields, lineterminator=u"\n")
        w.writeheader()
        for row in result_rows:
            w.writerow(row)


def _write_corregir_por_contenedor(csv_out, rows):
    fields = [
        u"element_id",
        u"unique_id",
        u"btz_path_contenedor",
        u"cantidad_codigos_asociados",
        u"cantidad_ya_existian",
        u"cantidad_escritos",
        u"cantidad_omitidos_sin_slot",
        u"slots_libres_iniciales",
        u"slots_libres_finales",
    ]
    with codecs.open(csv_out, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=fields, lineterminator=u"\n")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _debug_source_status(norm):
    has_code_col = _row_has_any(norm, CORREGIR_CODE_KEYS)
    has_eid_col = _row_has_any(norm, CORREGIR_EID_KEYS)
    has_uid_col = _row_has_any(norm, CORREGIR_UID_KEYS)
    code = _norm_cell_csv(_row_get(norm, *CORREGIR_CODE_KEYS))
    eid = _norm_cell_csv(_row_get(norm, *CORREGIR_EID_KEYS))
    uid = _norm_cell_csv(_row_get(norm, *CORREGIR_UID_KEYS))
    if not has_code_col or not has_eid_col:
        return u"columna_no_detectada", u"Falta columna equivalente a codigo_project o element_id_contenedor"
    if not code and not eid:
        return u"fila_invalida", u"Sin código ni element_id"
    if not code:
        return u"sin_codigo_project", u"No se detectó codigo_project"
    if not eid:
        return u"sin_element_id_contenedor", u"No se detectó element_id de contenedor"
    if not has_uid_col or not uid:
        return u"sin_unique_id", u"No se detectó unique_id; se intentará por element_id"
    return u"ok", u""


def _build_debug_fuente_rows(raw_rows):
    out = []
    aliases = (
        (u"codigo", CORREGIR_CODE_KEYS),
        (u"element_id", CORREGIR_EID_KEYS),
        (u"unique_id", CORREGIR_UID_KEYS),
        (u"path", CORREGIR_PATH_KEYS),
    )
    for norm in raw_rows:
        code = _norm_cell_csv(_row_get(norm, *CORREGIR_CODE_KEYS))
        eid = _norm_cell_csv(_row_get(norm, *CORREGIR_EID_KEYS))
        uid = _norm_cell_csv(_row_get(norm, *CORREGIR_UID_KEYS))
        path = _norm_cell_csv(_row_get(norm, *CORREGIR_PATH_KEYS))
        status, reason = _debug_source_status(norm)
        out.append(
            {
                u"codigo_project": code,
                u"element_id_contenedor_detectado": eid,
                u"unique_id_contenedor_detectado": uid,
                u"btz_path_contenedor": path,
                u"estado_lectura": status,
                u"motivo": reason,
                u"columnas_detectadas": _detected_columns(norm, aliases),
            }
        )
    return out


def _write_debug_fuente(path, rows):
    _write_dict_csv(
        path,
        [
            u"codigo_project",
            u"element_id_contenedor_detectado",
            u"unique_id_contenedor_detectado",
            u"btz_path_contenedor",
            u"estado_lectura",
            u"motivo",
            u"columnas_detectadas",
        ],
        rows,
    )


def _write_debug_por_contenedor(path, rows):
    _write_dict_csv(
        path,
        [
            u"element_id_contenedor",
            u"unique_id_contenedor",
            u"btz_path_contenedor",
            u"cantidad_codigos_en_csv_fuente",
            u"ejemplo_codigos",
            u"existe_en_revit",
            u"unique_id_coincide",
            u"cantidad_btz_ocupados_actuales",
            u"cantidad_slots_libres_actuales",
            u"cantidad_a_escribir",
            u"cantidad_ya_existia",
            u"cantidad_sin_slot",
            u"motivo_si_no_escribe",
        ],
        rows,
    )


def _debug_terms_match(row):
    vals = [
        row.get(u"codigo_project"),
        row.get(u"descripcion_project"),
        row.get(u"project_path"),
        row.get(u"ancestor_names_project"),
        row.get(u"btz_path_contenedor"),
        row.get(u"btz_path_actual"),
    ]
    hay = u" | ".join(_u(v).upper() for v in vals)
    return any(term in hay for term in DEBUG_SECTOR_TERMS)


def _load_debug_csv_rows(path):
    if not os.path.isfile(path):
        return []
    rows = []
    with codecs.open(path, u"r", encoding=u"utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        for raw in reader:
            rows.append(_row_norm_map(raw))
    return rows


def _debug_get(norm, *keys):
    return _norm_cell_csv(_row_get(norm, *keys))


def _build_debug_sector_row(source_name, norm):
    return {
        u"origen_archivo": source_name,
        u"codigo_project": _debug_get(norm, u"codigo_project", u"codigo", u"task_name", u"Task/Name"),
        u"descripcion_project": _debug_get(norm, u"descripcion_project", u"descripcion", u"descripción"),
        u"estado_match": _debug_get(norm, u"estado_match"),
        u"tipo_asociacion": _debug_get(norm, u"tipo_asociacion"),
        u"element_id_revit": _debug_get(norm, u"element_id_revit", u"element_id"),
        u"contenedor_sugerido_element_id": _debug_get(
            norm, u"contenedor_sugerido_element_id", u"element_id_contenedor"
        ),
        u"btz_path_actual": _debug_get(norm, u"btz_path_actual", u"btz_path_detectado"),
        u"btz_path_contenedor": _debug_get(norm, u"btz_path_contenedor", u"contenedor_sugerido_path"),
        u"project_path": _debug_get(norm, u"project_path"),
        u"ancestor_codes_project": _debug_get(norm, u"ancestor_codes_project"),
        u"ancestor_names_project": _debug_get(norm, u"ancestor_names_project"),
        u"motivo_revision": _debug_get(norm, u"motivo_revision"),
        u"observacion": _debug_get(norm, u"observacion"),
    }


def write_debug_sectores_no_asociados(path):
    sources = [
        (u"match_project_revit_preparacion.csv", os.path.join(PUBLIC_DIR, u"match_project_revit_preparacion.csv")),
        (u"match_project_revit_revision.csv", os.path.join(PUBLIC_DIR, u"match_project_revit_revision.csv")),
        (u"asociacion_contenedor_hijos_final_p10.csv", os.path.join(PUBLIC_DIR, u"asociacion_contenedor_hijos_final_p10.csv")),
        (u"contenedores_revit_p10.csv", os.path.join(PUBLIC_DIR, u"contenedores_revit_p10.csv")),
    ]
    final_source_name = u"asociacion_contenedor_hijos_final_p10.csv"
    final_source_rows = _load_debug_csv_rows(os.path.join(PUBLIC_DIR, final_source_name))
    final_codes = set()
    for norm in final_source_rows:
        code = _debug_get(norm, u"codigo_project", u"codigo", u"task_name", u"Task/Name")
        if code:
            final_codes.add(code.upper())

    rows = []
    for source_name, source_path in sources:
        source_rows = final_source_rows if source_name == final_source_name else _load_debug_csv_rows(source_path)
        for norm in source_rows:
            dbg = _build_debug_sector_row(source_name, norm)
            if _debug_terms_match(dbg):
                code_key = _u(dbg.get(u"codigo_project")).upper()
                if source_name != final_source_name and code_key and code_key not in final_codes:
                    obs = _u(dbg.get(u"observacion"))
                    extra = u"no aparece en asociacion_contenedor_hijos_final_p10.csv"
                    dbg[u"observacion"] = (obs + u" | " + extra) if obs else extra
                rows.append(dbg)
    _write_dict_csv(
        path,
        [
            u"origen_archivo",
            u"codigo_project",
            u"descripcion_project",
            u"estado_match",
            u"tipo_asociacion",
            u"element_id_revit",
            u"contenedor_sugerido_element_id",
            u"btz_path_actual",
            u"btz_path_contenedor",
            u"project_path",
            u"ancestor_codes_project",
            u"ancestor_names_project",
            u"motivo_revision",
            u"observacion",
        ],
        rows,
    )
    return len(rows)


def run_corregir_btz_confirmado(doc, log_lines=None, dry_run=DRY_RUN_CORREGIR):
    """
    Completa slots BTZ_Description_01..80 vacíos desde la asociación externa.
    No borra ni sobrescribe valores existentes.
    """
    if log_lines is None:
        log_lines = []

    ensure_public_layout()
    csv_in = os.path.join(PUBLIC_DIR, CSV_CORREGIR_IN_NAME)
    csv_out = os.path.join(PUBLIC_DIR, RESULTS_CORREGIR_NAME)
    txt_out = os.path.join(PUBLIC_DIR, SUMMARY_CORREGIR_NAME)
    por_contenedor_out = os.path.join(PUBLIC_DIR, POR_CONTENEDOR_CORREGIR_NAME)
    debug_fuente_out = os.path.join(PUBLIC_DIR, DEBUG_CORREGIR_FUENTE_NAME)
    debug_por_contenedor_out = os.path.join(PUBLIC_DIR, DEBUG_CORREGIR_POR_CONTENEDOR_FUENTE_NAME)
    debug_sectores_out = os.path.join(PUBLIC_DIR, DEBUG_SECTORES_NO_ASOCIADOS_NAME)

    if not os.path.isfile(csv_in):
        raise IOError(u"No existe el CSV de asociación:\n{0}".format(csv_in))

    ensure_btz_shared_parameters(doc, log_lines)

    raw_norm_rows = []
    with codecs.open(csv_in, u"r", encoding=u"utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        for raw in reader:
            raw_norm_rows.append(_row_norm_map(raw))

    debug_source_rows = _build_debug_fuente_rows(raw_norm_rows)
    _write_debug_fuente(debug_fuente_out, debug_source_rows)
    debug_sector_count = write_debug_sectores_no_asociados(debug_sectores_out)
    debug_status_counts = OrderedDict()
    for dbg in debug_source_rows:
        status = dbg.get(u"estado_lectura", u"")
        debug_status_counts[status] = debug_status_counts.get(status, 0) + 1

    grouped = OrderedDict()
    total_codes = 0
    for norm in raw_norm_rows:
        status, _reason = _debug_source_status(norm)
        if status not in (u"ok", u"sin_unique_id"):
            continue
        eid = _norm_cell_csv(_row_get(norm, *CORREGIR_EID_KEYS))
        code = _norm_cell_csv(_row_get(norm, *CORREGIR_CODE_KEYS))
        if not eid or not code:
            continue
        grouped.setdefault(eid, []).append(norm)
        total_codes += 1

    debug_container_rows = []
    for eid_text, rows in grouped.items():
        uid_csv_dbg = _norm_cell_csv(_row_get(rows[0], *CORREGIR_UID_KEYS))
        path_dbg = _norm_cell_csv(_row_get(rows[0], *CORREGIR_PATH_KEYS))
        codes_dbg = [_norm_cell_csv(_row_get(r, *CORREGIR_CODE_KEYS)) for r in rows]
        exists = u"NO"
        uid_match = u""
        occupied = 0
        free = 0
        to_write = 0
        already = 0
        no_slot = 0
        reason = u""
        try:
            el_dbg = doc.GetElement(_element_id_from_int(int(eid_text)))
        except Exception:
            el_dbg = None
        if el_dbg is None:
            reason = u"elemento_no_encontrado"
        else:
            exists = u"SI"
            uid_rev_dbg = _norm_cell_csv(getattr(el_dbg, u"UniqueId", u""))
            if uid_csv_dbg:
                uid_match = u"SI" if uid_rev_dbg.lower() == uid_csv_dbg.lower() else u"NO"
            else:
                uid_match = u"SIN_UNIQUE_ID"
            if uid_match == u"NO":
                reason = u"unique_id_no_coincide"
            current_dbg = _current_btz_values(el_dbg)
            occupied = len([v for v in current_dbg.values() if v])
            free = len([v for v in current_dbg.values() if not v])
            existing_codes = set(v.upper() for v in current_dbg.values() if v)
            slots_left = free
            for code in codes_dbg:
                if not code:
                    continue
                if code.upper() in existing_codes:
                    already += 1
                elif slots_left > 0:
                    to_write += 1
                    slots_left -= 1
                    existing_codes.add(code.upper())
                else:
                    no_slot += 1
            if not reason:
                if to_write == 0 and already == len([c for c in codes_dbg if c]):
                    reason = u"todos_ya_existian"
                elif to_write == 0 and no_slot:
                    reason = u"sin_slots_libres"
                else:
                    reason = u"ok"
        debug_container_rows.append(
            {
                u"element_id_contenedor": eid_text,
                u"unique_id_contenedor": uid_csv_dbg,
                u"btz_path_contenedor": path_dbg,
                u"cantidad_codigos_en_csv_fuente": len([c for c in codes_dbg if c]),
                u"ejemplo_codigos": u"; ".join([c for c in codes_dbg if c][:8]),
                u"existe_en_revit": exists,
                u"unique_id_coincide": uid_match,
                u"cantidad_btz_ocupados_actuales": occupied,
                u"cantidad_slots_libres_actuales": free,
                u"cantidad_a_escribir": to_write,
                u"cantidad_ya_existia": already,
                u"cantidad_sin_slot": no_slot,
                u"motivo_si_no_escribe": reason,
            }
        )
    _write_debug_por_contenedor(debug_por_contenedor_out, debug_container_rows)

    result_rows = []
    per_container_rows = []
    cont_found = 0
    total_existing = 0
    total_written = 0
    total_omitted = 0
    total_errors = 0
    modified_elements = set()
    fecha_now = datetime.datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")

    tx = Transaction(doc, u"BTZ | Corregir confirmado desde CSV externo")
    tx.Start()
    try:
        for eid_text, rows in grouped.items():
            try:
                eid_int = int(eid_text)
            except Exception:
                eid_int = None
            uid_csv = _norm_cell_csv(_row_get(rows[0], *CORREGIR_UID_KEYS))
            path = _norm_cell_csv(_row_get(rows[0], *CORREGIR_PATH_KEYS))

            def _append_result(code, status, slot, msg, uid=uid_csv):
                result_rows.append(
                    {
                        u"element_id": eid_text,
                        u"unique_id": uid,
                        u"btz_path_contenedor": path,
                        u"codigo_project": code,
                        u"estado_correccion": status,
                        u"btz_description_slot_usado": slot,
                        u"mensaje": msg,
                    }
                )

            if eid_int is None:
                total_errors += len(rows)
                for r in rows:
                    _append_result(
                        _norm_cell_csv(_row_get(r, *CORREGIR_CODE_KEYS)),
                        u"elemento_no_encontrado",
                        u"",
                        u"element_id_contenedor inválido",
                    )
                continue

            el = doc.GetElement(_element_id_from_int(eid_int))
            if el is None:
                total_errors += len(rows)
                for r in rows:
                    _append_result(
                        _norm_cell_csv(_row_get(r, *CORREGIR_CODE_KEYS)),
                        u"elemento_no_encontrado",
                        u"",
                        u"No existe elemento con ese ElementId",
                    )
                continue

            try:
                uid_rev = _norm_cell_csv(el.UniqueId)
            except Exception:
                uid_rev = u""
            if uid_csv and uid_rev and uid_csv.lower() != uid_rev.lower():
                total_errors += len(rows)
                for r in rows:
                    _append_result(
                        _norm_cell_csv(_row_get(r, *CORREGIR_CODE_KEYS)),
                        u"unique_id_no_coincide",
                        u"",
                        u"unique_id CSV={0} Revit={1}".format(uid_csv, uid_rev),
                        uid=uid_csv,
                    )
                continue

            cont_found += 1
            current = _current_btz_values(el)
            slots_free = [p for p, v in current.items() if not v]
            slots_initial = len(slots_free)
            existing_by_code = dict((v.upper(), p) for p, v in current.items() if v)
            c_existing = 0
            c_written = 0
            c_omitted = 0
            element_modified = False

            for r in rows:
                code = _norm_cell_csv(_row_get(r, *CORREGIR_CODE_KEYS))
                if not code:
                    continue
                code_key = code.upper()
                if code_key in existing_by_code:
                    c_existing += 1
                    total_existing += 1
                    _append_result(
                        code,
                        u"ya_existia",
                        existing_by_code[code_key],
                        u"El código ya estaba escrito en el elemento",
                        uid=uid_rev or uid_csv,
                    )
                    continue
                if not slots_free:
                    c_omitted += 1
                    total_omitted += 1
                    _append_result(
                        code,
                        u"omitido_sin_slot",
                        u"",
                        u"No quedan slots BTZ_Description disponibles",
                        uid=uid_rev or uid_csv,
                    )
                    continue

                slot = slots_free.pop(0)
                if dry_run:
                    ok, err = True, None
                else:
                    ok, err = set_text_parameter(el, slot, code)
                if ok:
                    c_written += 1
                    total_written += 1
                    element_modified = True
                    current[slot] = code
                    existing_by_code[code_key] = slot
                    _append_result(
                        code,
                        u"escrito",
                        slot,
                        u"DRY_RUN: se escribiría" if dry_run else u"Escrito en slot vacío",
                        uid=uid_rev or uid_csv,
                    )
                else:
                    total_errors += 1
                    _append_result(
                        code,
                        u"error_escritura",
                        slot,
                        err or u"error",
                        uid=uid_rev or uid_csv,
                    )

            if element_modified:
                modified_elements.add(eid_text)
                if not dry_run:
                    for pname, val in (
                        (PARAM_ESTADO_ASOCIACION, u"corregido_confirmado"),
                        (PARAM_ORIGEN_ASOCIACION, ORIGEN_CORREGIR_LITERAL),
                        (PARAM_FECHA_ASOCIACION, fecha_now),
                    ):
                        ok, err = set_text_parameter(el, pname, val)
                        if not ok:
                            total_errors += 1
                            result_rows.append(
                                {
                                    u"element_id": eid_text,
                                    u"unique_id": uid_rev or uid_csv,
                                    u"btz_path_contenedor": path,
                                    u"codigo_project": u"",
                                    u"estado_correccion": u"error_escritura",
                                    u"btz_description_slot_usado": pname,
                                    u"mensaje": err or u"error metadato",
                                }
                            )

            per_container_rows.append(
                {
                    u"element_id": eid_text,
                    u"unique_id": uid_rev or uid_csv,
                    u"btz_path_contenedor": path,
                    u"cantidad_codigos_asociados": len(rows),
                    u"cantidad_ya_existian": c_existing,
                    u"cantidad_escritos": c_written,
                    u"cantidad_omitidos_sin_slot": c_omitted,
                    u"slots_libres_iniciales": slots_initial,
                    u"slots_libres_finales": len([p for p, v in current.items() if not v]),
                }
            )

        if dry_run:
            tx.RollBack()
        else:
            tx.Commit()
    except Exception:
        if tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
        raise

    _write_corregir_rows(csv_out, result_rows)
    _write_corregir_por_contenedor(por_contenedor_out, per_container_rows)

    lines = [
        u"Corregir BTZ confirmado",
        u"fecha: {0}".format(fecha_now),
        u"dry_run: {0}".format(u"SI" if dry_run else u"NO"),
        u"",
        u"total_contenedores_leidos: {0}".format(len(grouped)),
        u"total_contenedores_encontrados_en_revit: {0}".format(cont_found),
        u"total_codigos_asociados_leidos: {0}".format(total_codes),
        u"total_filas_fuente_leidas: {0}".format(len(debug_source_rows)),
        u"estado_lectura_fuente: {0}".format(
            u"; ".join([u"{0}={1}".format(k, v) for k, v in debug_status_counts.items()])
        ),
        u"total_codigos_ya_existian: {0}".format(total_existing),
        u"total_codigos_escritos: {0}".format(total_written),
        u"total_codigos_omitidos_sin_slot: {0}".format(total_omitted),
        u"total_elementos_modificados: {0}".format(len(modified_elements)),
        u"total_errores: {0}".format(total_errors),
        u"ruta results CSV: {0}".format(csv_out),
        u"ruta por contenedor CSV: {0}".format(por_contenedor_out),
        u"ruta debug fuente CSV: {0}".format(debug_fuente_out),
        u"ruta debug por contenedor fuente CSV: {0}".format(debug_por_contenedor_out),
        u"ruta debug sectores no asociados CSV: {0}".format(debug_sectores_out),
        u"filas debug sectores no asociados: {0}".format(debug_sector_count),
    ]
    with codecs.open(txt_out, u"w", encoding=u"utf-8") as fp:
        fp.write(u"\n".join(lines) + u"\n")

    return {
        u"csv_in": csv_in,
        u"csv_out": csv_out,
        u"txt_out": txt_out,
        u"por_contenedor_out": por_contenedor_out,
        u"debug_fuente_out": debug_fuente_out,
        u"debug_por_contenedor_out": debug_por_contenedor_out,
        u"debug_sectores_out": debug_sectores_out,
        u"debug_sectores_rows": debug_sector_count,
        u"total_contenedores_leidos": len(grouped),
        u"total_contenedores_encontrados": cont_found,
        u"total_codigos_asociados": total_codes,
        u"total_filas_fuente_leidas": len(debug_source_rows),
        u"total_ya_existian": total_existing,
        u"total_escritos": total_written,
        u"total_omitidos_sin_slot": total_omitted,
        u"total_elementos_modificados": len(modified_elements),
        u"total_errores": total_errors,
        u"dry_run": dry_run,
    }


def _result_fieldnames():
    fn = [
        u"element_id",
        u"unique_id",
        u"estado_aplicacion",
        u"mensaje",
        u"btz_numero_activo",
    ]
    for i in range(1, 81):
        fn.append(u"btz_description_{:02d}".format(i))
    return fn


def _planta_normalizada(planta):
    plant = _u(planta).upper()
    if not plant:
        return u""
    if plant not in _PLANTAS_APLICAR_CONFIRMADO:
        raise ValueError(u"Planta no válida para aplicar BTZ confirmado: {0}".format(plant))
    return plant


def confirmado_csv_path_for_planta(planta):
    plant = _planta_normalizada(planta)
    return os.path.join(PUBLIC_DIR, u"output", plant, CSV_CONFIRMADO_NAME)


def discover_confirmados_por_planta():
    ensure_public_layout()
    out = []
    for plant in _PLANTAS_APLICAR_CONFIRMADO:
        path = confirmado_csv_path_for_planta(plant)
        out.append(
            {
                u"planta": plant,
                u"path": path,
                u"exists": os.path.isfile(path),
            }
        )
    return out


def summarize_confirmado_csv(csv_in):
    if not os.path.isfile(csv_in):
        raise IOError(u"No existe el CSV confirmado:\n{0}".format(csv_in))

    filas_leidas = 0
    element_ids = set()
    estados_aplicables = 0
    filas_omitidas = 0
    filas_confirmado = 0
    filas_match_ok = 0
    with codecs.open(csv_in, u"r", encoding=u"utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        for raw in reader:
            filas_leidas += 1
            norm = _row_norm_map(raw)
            eid = _u(_row_get(norm, u"element_id", u"elementid"))
            if eid:
                element_ids.add(eid)
            estado = _u(_row_get(norm, u"estado_match")).lower()
            if estado in _ESTADOS_APLICABLES:
                estados_aplicables += 1
                if estado == u"confirmado":
                    filas_confirmado += 1
                elif estado == u"match_ok":
                    filas_match_ok += 1
            else:
                filas_omitidas += 1

    return {
        u"csv_in": csv_in,
        u"filas_leidas": filas_leidas,
        u"element_ids_unicos": len(element_ids),
        u"estados_aplicables": estados_aplicables,
        u"filas_confirmado": filas_confirmado,
        u"filas_match_ok": filas_match_ok,
        u"filas_omitidas": filas_omitidas,
    }


def _copy_file_utf8sig(src, dst):
    parent = os.path.dirname(dst)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    shutil.copyfile(src, dst)


def run_aplicar_btz_confirmado(doc, log_lines=None, csv_in=None, planta=None, copy_compat=True):
    """Lee un CSV confirmado y escribe parámetros BTZ (transacción única)."""
    if log_lines is None:
        log_lines = []

    ensure_public_layout()
    plant = _planta_normalizada(planta) if planta else u""
    if csv_in:
        csv_in = os.path.normpath(csv_in)
    elif plant:
        csv_in = confirmado_csv_path_for_planta(plant)
    else:
        csv_in = os.path.join(PUBLIC_DIR, CSV_CONFIRMADO_NAME)

    if plant:
        out_dir = os.path.join(PUBLIC_DIR, u"output", plant)
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        csv_out = os.path.join(out_dir, RESULTS_APPLY_NAME)
        txt_out = os.path.join(out_dir, SUMMARY_APPLY_NAME)
    else:
        csv_out = os.path.join(PUBLIC_DIR, RESULTS_APPLY_NAME)
        txt_out = os.path.join(PUBLIC_DIR, SUMMARY_APPLY_NAME)

    if not os.path.isfile(csv_in):
        if plant:
            raise IOError(
                u"No existe archivo confirmado para {0}. Primero ejecute preparar_match_project_revit.py para {0}.".format(
                    plant
                )
            )
        raise IOError(u"No existe el CSV confirmado:\n{0}".format(csv_in))

    ensure_btz_shared_parameters(doc, log_lines)

    filas = []
    with codecs.open(csv_in, u"r", encoding=u"utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        for raw in reader:
            filas.append(_row_norm_map(raw))

    filas_leidas = len(filas)
    filas_aplicadas = 0
    filas_omitidas = 0
    errores = 0
    no_encontrados = 0
    conflictos_uid = 0

    fecha_now = datetime.datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")
    result_rows = []

    tx = Transaction(doc, u"BTZ | Aplicar confirmado (CSV)")
    tx.Start()
    try:
        for norm in filas:
            estado_raw = _u(_row_get(norm, u"estado_match"))
            estado_cmp = estado_raw.lower()
            out_base = {
                u"element_id": u"",
                u"unique_id": u"",
                u"estado_aplicacion": u"",
                u"mensaje": u"",
                u"btz_numero_activo": u"",
            }
            for i in range(1, 81):
                out_base[u"btz_description_{:02d}".format(i)] = u""

            if estado_cmp not in _ESTADOS_APLICABLES:
                filas_omitidas += 1
                eid_guess = _parse_element_id_from_row(norm)
                uid_csv = _norm_cell_csv(_row_get(norm, u"unique_id"))
                out_base[u"element_id"] = unicode(eid_guess) if eid_guess else u""
                out_base[u"unique_id"] = uid_csv
                out_base[u"estado_aplicacion"] = u"omitido"
                out_base[u"mensaje"] = (
                    u"estado_match no aplicable ({0}); se requiere confirmado o match_ok".format(
                        estado_raw or u"(vacío)"
                    )
                )
                result_rows.append(out_base)
                continue

            eid_int = _parse_element_id_from_row(norm)
            uid_csv = _norm_cell_csv(_row_get(norm, u"unique_id"))

            num_val = _norm_cell_csv(_row_get(norm, u"btz_numero_activo"))
            desc_csv = []
            for i in range(1, 81):
                desc_csv.append(
                    _norm_cell_csv(
                        _row_get(norm, u"btz_description_{:02d}".format(i))
                    )
                )

            for i in range(1, 81):
                out_base[u"btz_description_{:02d}".format(i)] = desc_csv[i - 1]
            out_base[u"btz_numero_activo"] = num_val

            if eid_int is None:
                errores += 1
                out_base[u"element_id"] = u""
                out_base[u"unique_id"] = uid_csv
                out_base[u"estado_aplicacion"] = u"error"
                out_base[u"mensaje"] = u"element_id inválido o vacío"
                result_rows.append(out_base)
                continue

            out_base[u"element_id"] = unicode(eid_int)
            out_base[u"unique_id"] = uid_csv

            el = doc.GetElement(_element_id_from_int(eid_int))
            if el is None:
                no_encontrados += 1
                errores += 1
                out_base[u"estado_aplicacion"] = u"no_encontrado"
                out_base[u"mensaje"] = u"No existe elemento con ese ElementId"
                result_rows.append(out_base)
                continue

            try:
                uid_rev = _norm_cell_csv(el.UniqueId)
            except Exception:
                uid_rev = u""

            if (
                uid_csv
                and uid_rev
                and uid_csv.lower() != uid_rev.lower()
            ):
                conflictos_uid += 1
                errores += 1
                out_base[u"unique_id"] = uid_csv
                out_base[u"estado_aplicacion"] = u"conflicto_unique_id"
                out_base[u"mensaje"] = (
                    u"unique_id no coincide (CSV={0} vs Revit={1})".format(
                        uid_csv, uid_rev
                    )
                )
                result_rows.append(out_base)
                continue

            limpiar = _bool_limpiar(norm)
            errs = []

            def _apply_one(pname, val, allow_clear):
                if not val and not allow_clear:
                    return
                if not val and allow_clear:
                    val_write = u""
                else:
                    val_write = val
                ok, err = set_text_parameter(el, pname, val_write)
                if not ok:
                    errs.append(u"{0}: {1}".format(pname, err or u"error"))

            _apply_one(PARAM_NUMERO_ACTIVO, num_val, limpiar)
            for idx, pname in enumerate(PARAM_NUMERIC):
                _apply_one(pname, desc_csv[idx], limpiar)

            ok_meta, err_meta = set_text_parameter(
                el, PARAM_ESTADO_ASOCIACION, estado_raw
            )
            if not ok_meta:
                errs.append(
                    u"{0}: {1}".format(PARAM_ESTADO_ASOCIACION, err_meta or u"error")
                )

            ok_o, err_o = set_text_parameter(
                el, PARAM_ORIGEN_ASOCIACION, ORIGEN_CSV_LITERAL
            )
            if not ok_o:
                errs.append(
                    u"{0}: {1}".format(PARAM_ORIGEN_ASOCIACION, err_o or u"error")
                )

            ok_f, err_f = set_text_parameter(el, PARAM_FECHA_ASOCIACION, fecha_now)
            if not ok_f:
                errs.append(
                    u"{0}: {1}".format(PARAM_FECHA_ASOCIACION, err_f or u"error")
                )

            if errs:
                errores += 1
                out_base[u"estado_aplicacion"] = u"error_escritura"
                out_base[u"mensaje"] = u" | ".join(errs)
            else:
                filas_aplicadas += 1
                out_base[u"estado_aplicacion"] = u"aplicado"
                out_base[u"mensaje"] = u"OK"
            result_rows.append(out_base)

        tx.Commit()
    except Exception:
        if tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
        raise

    fields = _result_fieldnames()
    with codecs.open(csv_out, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=fields, lineterminator=u"\n")
        w.writeheader()
        for r in result_rows:
            w.writerow(r)

    txt_body = [
        u"Aplicar BTZ confirmado",
        u"fecha: {0}".format(
            datetime.datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")
        ),
        u"",
        u"planta: {0}".format(plant or u"(sin planta seleccionada / legacy)"),
        u"entrada: {0}".format(csv_in),
        u"resultados CSV: {0}".format(csv_out),
        u"",
        u"filas leídas: {0}".format(filas_leidas),
        u"filas aplicadas: {0}".format(filas_aplicadas),
        u"filas omitidas (estado): {0}".format(filas_omitidas),
        u"errores (incluye no encontrado y conflicto): {0}".format(errores),
        u"elementos no encontrados: {0}".format(no_encontrados),
        u"conflictos unique_id: {0}".format(conflictos_uid),
    ]
    with codecs.open(txt_out, u"w", encoding=u"utf-8") as fp:
        fp.write(u"\n".join(txt_body) + u"\n")

    compat_csv_out = u""
    compat_txt_out = u""
    if plant and copy_compat:
        compat_csv_out = os.path.join(PUBLIC_DIR, RESULTS_APPLY_NAME)
        compat_txt_out = os.path.join(PUBLIC_DIR, SUMMARY_APPLY_NAME)
        _copy_file_utf8sig(csv_out, compat_csv_out)
        _copy_file_utf8sig(txt_out, compat_txt_out)

    log_lines.append(
        u"Aplicar confirmado: leídas={0} aplicadas={1} -> {2}".format(
            filas_leidas, filas_aplicadas, csv_out
        )
    )

    return {
        u"planta": plant,
        u"csv_in": csv_in,
        u"csv_out": csv_out,
        u"txt_out": txt_out,
        u"compat_csv_out": compat_csv_out,
        u"compat_txt_out": compat_txt_out,
        u"filas_leidas": filas_leidas,
        u"filas_aplicadas": filas_aplicadas,
        u"filas_omitidas": filas_omitidas,
        u"errores": errores,
        u"no_encontrados": no_encontrados,
        u"conflictos_uid": conflictos_uid,
    }
