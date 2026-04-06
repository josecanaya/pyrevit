# -*- coding: utf-8 -*-
"""
pyRevit — Exportar grupos Revit vs blocks (sin IA en Revit)

Recorre el modelo, agrupa por group_key, exporta a public/ y envía payload a n8n.
La aplicación de BTZ en el modelo se hace con el botón aparte «Ejecutar automático».
LEGACY/OPTIONAL: este flujo ya no es el runtime oficial.
"""
from __future__ import print_function

__title__ = "Crear grupos"
__doc__ = (
    "Exporta grupos y envía payload a n8n. Para aplicar BTZ usá el botón «Ejecutar automático»."
)
__author__ = "btz.extension"

import os
import csv
import codecs
import clr
import json
import re
import urllib2
import datetime
import hashlib
import time
import subprocess

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    ElementId,
    FilteredElementCollector,
    FamilyInstance,
    FamilySymbol,
    BuiltInParameter,
    Transaction,
    CategoryType,
    GroupTypeId,
)

from pyrevit import revit, forms

try:
    long
except NameError:
    long = int

import sys
_btz_bundle = os.path.dirname(os.path.abspath(__file__))
if _btz_bundle not in sys.path:
    sys.path.insert(0, _btz_bundle)

from btz_apply_webhook import (
    EXT_DIR,
    RESOURCES_DIR,
    SHARED_PARAMS_FILE,
    PUBLIC_DIR,
    PAYLOAD_GROUPS_JSON_PATH,
    WEBHOOK_RESPONSE_JSON_PATH,
    GROUP_KEY_ELEMENT_IDS_JSON_PATH,
    REFINED_GROUP_KEY_ELEMENT_IDS_JSON_PATH,
    REFINED_GROUPS_MANIFEST_JSON_PATH,
    GROUPING_PIPELINE_LOG_PATH,
    _BTZ_PATH_SOURCE,
    AUTO_APPLY_CONFIDENCE,
    APPLY_WEBHOOK_RESULTS,
    APPLY_ONLY_FROM_SAVED_WEBHOOK,
    EXPORT_APPLY_RESULTS_TXT,
    PARAM_BASE,
    PARAM_NUMERIC,
    ALL_BTZ_PARAMS,
    PARAM_STATUS,
    PARAM_SOURCE,
    PARAM_CONFIDENCE,
    ALL_BIND_PARAMS,
    _param_value_as_string,
    _ensure_public_dir,
    load_payload_from_json_file,
    append_run_log,
    map_group_key_to_elements,
    load_group_key_element_ids_from_json,
    try_apply_webhook_response,
    main_apply_saved_webhook_only,
)
from btz_paths import get_public_file

from btz_group_enrichment import (
    enrich_groups_with_blocks,
    split_ambiguous_groups,
    save_refined_group_key_element_ids,
    save_refined_groups_manifest,
    save_grouping_pipeline_log,
    build_enriched_revit_groups_for_payload,
)
from btz_element_metadata import SEMANTIC_CSV_COLUMNS, collect_extra_metadata_for_element
from btz_openai_grouping import (
    load_normalized_blocks_csv,
    build_grouping_scenarios,
    analyze_grouping_with_openai,
    build_refined_groups_from_ai,
)
from btz_project_config import (
    ensure_project_config_files,
    load_project_config,
    validate_project_config,
    apply_project_soft_logic_to_scenario,
    refresh_blocks_semantic_from_csv,
    build_project_rule_split_parts,
)


# =============================================================================
# CONFIGURACIÓN (editar aquí)
# =============================================================================

# Origen de la ruta a resources/ (para el log)
# Si True: no recorre Revit; lee PAYLOAD_GROUPS_JSON_PATH y hace POST al webhook
# Si False: flujo completo (export + payload + opcional webhook + aplicar)
SEND_PAYLOAD_FILE_ONLY = False

# CSV normalizado para agrupación inteligente (fuente única)
BLOCKS_CSV_FILE = get_public_file(u"blocks_normalized.csv", u"optional", fallback=True)

# Etapa IA de agrupación (OpenAI en Python, previo al webhook)
USE_OPENAI_GROUPING = True
OPENAI_GROUPING_MODEL = u"gpt-5.4"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_GROUPING_TIMEOUT_SEC = 60
OPENAI_GROUPING_MAX_ELEMENTS_PER_GROUP = 400
OPENAI_GROUPING_MAX_CANDIDATE_BLOCKS = 12
OPENAI_GROUPING_MAX_COMMENT_CHARS = 220
OPENAI_GROUPING_MAX_GROUP_SUMMARY_CHARS = 360
OPENAI_GROUPING_CACHE_PATH = get_public_file(
    u"openai_grouping_cache.json", u"legacy", fallback=False
)
OPENAI_GROUPING_AMBIGUITY_MIN = 0.35
OPENAI_GROUPING_DOMINANT_CONF_MIN = 0.75
OPENAI_GROUPING_CACHE_TTL_DAYS = 7
OPENAI_GROUPING_PROMPT_VERSION = u"v2_aggressive"
OPENAI_GROUPING_AGGRESSIVE_MODE = True
OPENAI_GROUPING_IGNORE_CACHE = True
OPENAI_GROUPING_FORCE_SPLIT_FOR_TEST = True
OPENAI_GROUPING_FORCE_SPLIT_MIN_GROUP_SIZE = 20
OPENAI_GROUPING_FORCE_SPLIT_MAX_BUCKETS = 8
OPENAI_GROUPING_USE_EXTERNAL_PYTHON = True
OPENAI_GROUPING_PYTHON_EXE = os.environ.get("BTZ_OPENAI_PYTHON_EXE", "python")
OPENAI_GROUPING_HELPER_SCRIPT = os.path.join(
    _btz_bundle, "btz_openai_grouping_worker.py"
)
OPENAI_GROUPING_WORKER_TIMEOUT_BUFFER_SEC = 20

# Webhook n8n (clasificador BTZ — payload agrupado + blocks.csv embebido)
N8N_WEBHOOK_URL = "https://jrcontrera.app.n8n.cloud/webhook/revit-btz-classifier"
# Payloads grandes o n8n lento: subir (segundos). Error 10060 = timeout de red.
N8N_TIMEOUT_SEC = 300

# Si True: solo exporta a public/ (CSV + JSON); no hace POST al webhook
EXPORT_ONLY = False

# Si True y EXPORT_ONLY es False: tras guardar payload_groups.json, envía POST
SEND_TO_WEBHOOK = True

# Máximo de elementos a procesar (None = sin límite; usar con cuidado en modelos grandes)
LIMIT_ELEMENTS = None


# --- Filtro de categorías (reduce ruido: Views, Materials, Levels, etc.) ---
# True (recomendado): solo se escanean categorías de obra listadas abajo.
# False: se escanean todas las instancias con categoría, excepto EXCLUDED_CATEGORY_NAMES.
USE_CATEGORY_WHITELIST = True

# Si USE_CATEGORY_WHITELIST y esta lista NO está vacía: solo estas categorías (sobrescribe el default).
# Si está vacía: se usan CATEGORY_TO_MACROGROUP + ADDITIONAL_INCLUDED_CATEGORIES.
TARGET_CATEGORIES = []

# Categorías extra de modelo/obra (añadir aquí si hace falta; nombres como en el explorador de Revit).
ADDITIONAL_INCLUDED_CATEGORIES = [
    u"Generic Models",
]

# Nunca exportar estos nombres de categoría (comparación sin distinguir mayúsculas).
# Si tu plantilla está en español, añade también "Vistas", "Materiales", "Niveles", etc.
EXCLUDED_CATEGORY_NAMES = [
    u"Views",
    u"Materials",
    u"Levels",
    u"RVT Links",
    u"Revit Links",
    u"Analytical Nodes",
    u"Analytical Members",
    u"Analytical Foundations",
    u"Analytical Walls",
    u"Analytical Floors",
    u"Analytical Braces",
    u"Project Information",
    u"Schedules",
    u"Sheets",
    u"Drawing Sheets",
    u"Cameras",
    u"Raster Images",
    u"Scope Boxes",
    u"Imports in DWG",
    u"Lines",
    u"Line Patterns",
    u"Fill Patterns",
    u"Text Notes",
    u"Dimensions",
    u"Grids",
    u"Reference Planes",
]

# Mapa: nombre de categoría Revit -> id de macrogrupo (reglas fijas, sin IA).
# Ajustar según el proyecto; claves en el idioma de la plantilla (p. ej. inglés).
CATEGORY_TO_MACROGROUP = {
    u"Structural Foundations": u"estructura",
    u"Structural Columns": u"estructura",
    u"Structural Framing": u"estructura",
    u"Structural Connections": u"estructura",
    u"Walls": u"obra_gris",
    u"Floors": u"obra_gris",
    u"Structural Walls": u"obra_gris",
    u"Ceilings": u"terminaciones",
    u"Doors": u"terminaciones",
    u"Windows": u"terminaciones",
    u"Pipes": u"instalaciones",
    u"Ducts": u"instalaciones",
    u"Pipe Fittings": u"instalaciones",
    u"Duct Fittings": u"instalaciones",
    u"Mechanical Equipment": u"instalaciones",
    u"Electrical Equipment": u"instalaciones",
    u"Electrical Fixtures": u"instalaciones",
    u"Plumbing Fixtures": u"instalaciones",
}

# Orden fijo de macrogrupos en el payload
MACRO_GROUPS_ORDER = [
    u"estructura",
    u"obra_gris",
    u"terminaciones",
    u"instalaciones",
    u"otros",
]

# Columnas base del CSV blocks (misma lógica que Sugerir)
CSV_CODE_COL = "code"
CSV_DESC_COL = "description"
CSV_LAST_BASE_COL = "displacement_date"

# Máx. IDs de muestra por grupo en JSON/CSV
MAX_SAMPLE_IDS = 50

# Separador interno para group_key (si un nombre contiene "|", se reemplaza)
GROUP_KEY_SEP = u"|"

# Si True: guarda la respuesta cruda del webhook en public/webhook_response.json
SAVE_WEBHOOK_RESPONSE = True


# =============================================================================
# Utilidades Revit / BTZ
# =============================================================================


def _element_id_as_int(element_id):
    try:
        return element_id.Value if hasattr(element_id, 'Value') else element_id.IntegerValue
    except AttributeError:
        return int(element_id.Value)


def _safe_type_display_name(elem):
    if elem is None:
        return u""
    try:
        n = elem.Name
        if n is not None:
            return unicode(n)
    except Exception:
        pass
    for bip in (
        BuiltInParameter.ALL_MODEL_TYPE_NAME,
        BuiltInParameter.SYMBOL_NAME_PARAM,
    ):
        try:
            p = elem.get_Parameter(bip)
            if p is not None and p.HasValue:
                s = p.AsString()
                if s:
                    return unicode(s)
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
    cat = element.Category
    return unicode(cat.Name) if cat is not None else u""


def _family_and_type_names(doc, element):
    family_name = u""
    type_name = u""
    tid = element.GetTypeId()
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
                            family_name = unicode(p.AsString() or u"")
                    except Exception:
                        pass
    return family_name, type_name


def _level_name(doc, element):
    if isinstance(element, FamilyInstance):
        lvl_id = element.LevelId
        if lvl_id and lvl_id != ElementId.InvalidElementId:
            lvl = doc.GetElement(lvl_id)
            if lvl is not None:
                return unicode(lvl.Name or u"")

    try:
        p = element.get_Parameter(BuiltInParameter.LEVEL_PARAM)
        if p is not None and p.HasValue:
            lid = p.AsElementId()
            if lid and lid != ElementId.InvalidElementId:
                lvl = doc.GetElement(lid)
                if lvl is not None:
                    return unicode(lvl.Name or u"")
    except Exception:
        pass

    for alt in (u"Nivel", u"Level", u"Reference Level", u"Nivel de referencia"):
        v = _param_value_as_string(element, alt)
        if v:
            return v
    return u""


def _element_instance_name(element):
    """Nombre visible del elemento si existe (instancia)."""
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


def _project_display_name(doc):
    try:
        t = doc.Title
        if t:
            return unicode(t)
    except Exception:
        pass
    try:
        p = doc.PathName
        if p:
            return unicode(os.path.splitext(os.path.basename(p))[0])
    except Exception:
        pass
    return u"(sin título)"


def _norm_cat_key(name):
    return (name or u"").strip()


def _build_category_lookup():
    """Índice insensible a mayúsculas para CATEGORY_TO_MACROGROUP."""
    d = {}
    for k, v in CATEGORY_TO_MACROGROUP.items():
        d[_norm_cat_key(k).lower()] = v
    return d


_CATEGORY_LOOKUP = None


def assign_macro_group(category_name):
    """
    Asigna un id de macrogrupo según el nombre de categoría Revit.
    Reglas fijas en CATEGORY_TO_MACROGROUP; si no coincide -> 'otros'.
    """
    global _CATEGORY_LOOKUP
    if _CATEGORY_LOOKUP is None:
        _CATEGORY_LOOKUP = _build_category_lookup()
    key = _norm_cat_key(category_name).lower()
    return _CATEGORY_LOOKUP.get(key, u"otros")


def _sanitize_group_field(s):
    """Evita romper group_key si el texto contiene el separador."""
    t = (s or u"").strip()
    return t.replace(GROUP_KEY_SEP, u" ")


def _slug_for_key(s):
    t = (s or u"").strip().lower()
    out = []
    for ch in t:
        if ch.isalnum() or ch in (u"-", u"_"):
            out.append(ch)
        else:
            out.append(u"_")
    t = u"".join(out)
    t = re.sub(u"_+", u"_", t).strip(u"_")
    return t or u"na"


def build_group_key(macro_group, category_name, family_name, type_name):
    """
    Clave compuesta para agrupar instancias repetidas.

    Formato: macro_group|category_name|family_name|type_name
    (campos sanitizados para no contener el separador '|').
    """
    parts = [
        _sanitize_group_field(macro_group),
        _sanitize_group_field(category_name),
        _sanitize_group_field(family_name),
        _sanitize_group_field(type_name),
    ]
    return GROUP_KEY_SEP.join(parts)


# =============================================================================
# Recolección y agrupación
# =============================================================================

_EXCLUDED_LOWER_CACHE = None
_WHITELIST_LOWER_CACHE = None


def _excluded_categories_lower():
    """Nombres de categoría excluidos (minúsculas, normalizados)."""
    global _EXCLUDED_LOWER_CACHE
    if _EXCLUDED_LOWER_CACHE is None:
        _EXCLUDED_LOWER_CACHE = set(
            _norm_cat_key(x).lower() for x in EXCLUDED_CATEGORY_NAMES
        )
    return _EXCLUDED_LOWER_CACHE


def _whitelist_allowed_lower():
    """Conjunto permitido en modo whitelist (minúsculas)."""
    global _WHITELIST_LOWER_CACHE
    if _WHITELIST_LOWER_CACHE is None:
        if TARGET_CATEGORIES:
            src = TARGET_CATEGORIES
        else:
            src = list(CATEGORY_TO_MACROGROUP.keys()) + list(
                ADDITIONAL_INCLUDED_CATEGORIES
            )
        _WHITELIST_LOWER_CACHE = set(_norm_cat_key(x).lower() for x in src)
    return _WHITELIST_LOWER_CACHE


def _category_passes_scan_filters(cat_name):
    """
    True si la categoría debe incluirse en el barrido.
    - Siempre se excluyen EXCLUDED_CATEGORY_NAMES.
    - Con USE_CATEGORY_WHITELIST: solo categorías del mapa + adicionales o TARGET_CATEGORIES.
    - Sin whitelist: todas las categorías salvo excluidas; si TARGET_CATEGORIES no vacío, solo esas.
    """
    k = _norm_cat_key(cat_name).lower()
    if k in _excluded_categories_lower():
        return False
    if USE_CATEGORY_WHITELIST:
        return k in _whitelist_allowed_lower()
    if TARGET_CATEGORIES:
        allow = set(_norm_cat_key(x).lower() for x in TARGET_CATEGORIES)
        return k in allow
    return True


def collect_revit_elements(doc, log_lines):
    """
    Recorre instancias del modelo y devuelve una lista de dicts por elemento.

    Campos: identidad (id, categoría, familia, tipo, nivel, nombre), macro_group,
    group_key, columnas semánticas (comments, mark, keynote, tipo, estructura,
    OmniClass, workset, host, … ver btz_element_metadata), BTZ_*.
    """
    if USE_CATEGORY_WHITELIST:
        log_lines.append(
            u"Filtro: whitelist ON — {0} categorías permitidas".format(
                len(_whitelist_allowed_lower())
            )
        )
    else:
        log_lines.append(
            u"Filtro: whitelist OFF — categorías según TARGET o todas; "
            u"excluidas fijas: {0}".format(len(_excluded_categories_lower()))
        )

    rows = []
    col = FilteredElementCollector(doc).WhereElementIsNotElementType()
    count = 0
    for el in col:
        if LIMIT_ELEMENTS is not None and count >= LIMIT_ELEMENTS:
            break
        cat = el.Category
        if cat is None:
            continue
        cat_name = unicode(cat.Name or u"")
        if not _category_passes_scan_filters(cat_name):
            continue

        macro = assign_macro_group(cat_name)
        fam, typ = _family_and_type_names(doc, el)
        gkey = build_group_key(macro, cat_name, fam, typ)
        lvl = _level_name(doc, el)
        ename = _element_instance_name(el)

        uid = u""
        try:
            uid = unicode(el.UniqueId or u"")
        except Exception:
            pass

        rec = {
            u"element_id": _element_id_as_int(el.Id),
            u"unique_id": uid,
            u"category_name": cat_name,
            u"family_name": fam,
            u"type_name": typ,
            u"level_name": lvl,
            u"element_name": ename,
            u"macro_group": macro,
            u"group_key": gkey,
        }
        meta = collect_extra_metadata_for_element(doc, el)
        for k in SEMANTIC_CSV_COLUMNS:
            rec[k] = meta.get(k, u"")
        for pname in ALL_BTZ_PARAMS:
            rec[pname] = _param_value_as_string(el, pname)

        rows.append(rec)
        count += 1

    log_lines.append(
        u"Elementos recolectados: {0} (límite {1})".format(
            len(rows),
            LIMIT_ELEMENTS if LIMIT_ELEMENTS is not None else u"ninguno",
        )
    )
    log_lines.append(
        u"Columnas semánticas por elemento (además de BTZ): {0}".format(
            len(SEMANTIC_CSV_COLUMNS)
        )
    )
    return rows


def group_elements(element_rows):
    """
    Agrupa filas por group_key.

    Devuelve lista de dicts: group_key, macro_group, count, category_name,
    family_name, type_name, level_names (lista), sample_element_ids (lista).
    """
    buckets = {}
    for r in element_rows:
        gk = r[u"group_key"]
        if gk not in buckets:
            buckets[gk] = {
                u"group_key": gk,
                u"macro_group": r[u"macro_group"],
                u"category_name": r[u"category_name"],
                u"family_name": r[u"family_name"],
                u"type_name": r[u"type_name"],
                u"level_names": set(),
                u"element_ids": [],
                u"count": 0,
            }
        b = buckets[gk]
        b[u"count"] += 1
        ln = (r.get(u"level_name") or u"").strip()
        if ln:
            b[u"level_names"].add(ln)
        eid = r[u"element_id"]
        if len(b[u"element_ids"]) < MAX_SAMPLE_IDS:
            b[u"element_ids"].append(eid)

    out = []
    for gk in sorted(buckets.keys()):
        b = buckets[gk]
        levels = sorted(b[u"level_names"], key=lambda x: x.lower())
        out.append({
            u"group_key": gk,
            u"macro_group": b[u"macro_group"],
            u"count": b[u"count"],
            u"category_name": b[u"category_name"],
            u"family_name": b[u"family_name"],
            u"type_name": b[u"type_name"],
            u"level_names": levels,
            u"sample_element_ids": list(b[u"element_ids"]),
        })
    return out


# =============================================================================
# CSV blocks (obra) — reutiliza lógica alineada a Sugerir
# =============================================================================


def _cell_flag_01(cell):
    v = unicode(cell or u"").strip()
    return 1 if v == u"1" else 0


def load_blocks_csv(csv_path, log_lines):
    """
    Lee blocks.csv: devuelve estructura con rows (code, description, …, flags).

    Para el payload solo se usan code, description y flags en blocks_rows.
    """
    if not csv_path or not os.path.isfile(csv_path):
        raise IOError(u"No se encontró el CSV: {0}".format(csv_path))

    encodings = [u"utf-8-sig", u"utf-8", u"cp1252", u"latin1"]
    last_error = None

    for enc in encodings:
        try:
            with codecs.open(csv_path, u"r", enc) as fp:
                sample = fp.read(4096)
                fp.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=u";,")
                    delimiter = dialect.delimiter
                except Exception:
                    delimiter = u";" if sample.count(u";") > sample.count(u",") else u","

                reader = csv.DictReader(fp, delimiter=delimiter)
                if not reader.fieldnames:
                    continue

                fields = [f.strip() for f in reader.fieldnames]
                code_field = None
                desc_field = None
                displ_field = None

                for f in fields:
                    low = f.lower().strip()
                    if low == CSV_CODE_COL:
                        code_field = f
                    if low == CSV_DESC_COL:
                        desc_field = f
                    if low == CSV_LAST_BASE_COL.lower():
                        displ_field = f

                if not desc_field:
                    raise ValueError(u"El CSV no tiene columna description")

                dd_idx = None
                for i, f in enumerate(fields):
                    if displ_field and f == displ_field:
                        dd_idx = i
                        break
                    if f.lower().strip() == CSV_LAST_BASE_COL.lower():
                        dd_idx = i
                        break

                if dd_idx is None:
                    raise ValueError(
                        u"El CSV no tiene columna {0}".format(CSV_LAST_BASE_COL)
                    )

                thematic_columns = [
                    fields[j] for j in range(dd_idx + 1, len(fields)) if fields[j]
                ]

                rows = []
                seen = set()
                for row in reader:
                    code = (row.get(code_field, u"") if code_field else u"").strip()
                    desc = (row.get(desc_field, u"") if desc_field else u"").strip()
                    if not desc:
                        continue

                    flags = {}
                    for tc in thematic_columns:
                        flags[tc] = _cell_flag_01(row.get(tc, u""))

                    key = (code, desc)
                    if key in seen:
                        continue
                    seen.add(key)

                    rows.append({
                        u"code": code,
                        u"description": desc,
                        u"flags": flags,
                    })

                rows.sort(key=lambda x: (x[u"description"] or u"").lower())
                if not rows:
                    raise ValueError(u"El CSV no tiene filas útiles")

                log_lines.append(
                    u"blocks.csv: {0} filas, {1} columnas temáticas".format(
                        len(rows), len(thematic_columns)
                    )
                )
                return {
                    u"thematic_columns": thematic_columns,
                    u"rows": rows,
                }
        except Exception as ex:
            last_error = ex
            continue

    raise ValueError(
        u"No se pudo leer blocks.csv. Error: {0}".format(last_error)
    )


def blocks_rows_for_payload(blocks_struct):
    """Lista blocks_rows para el JSON (solo code, description, flags)."""
    out = []
    for r in blocks_struct[u"rows"]:
        out.append({
            u"code": r[u"code"],
            u"description": r[u"description"],
            u"flags": dict(r[u"flags"]),
        })
    return out


def read_blocks_csv_raw(csv_path, log_lines):
    """
    Lee el CSV de resources (blocks.csv) completo como texto Unicode.
    Se envía en el payload como blocks_csv_text para n8n.
    """
    if not csv_path or not os.path.isfile(csv_path):
        raise IOError(u"No se encontró el CSV: {0}".format(csv_path))

    encodings = [u"utf-8-sig", u"utf-8", u"cp1252", u"latin1"]
    last_error = None
    for enc in encodings:
        try:
            with codecs.open(csv_path, u"r", enc) as fp:
                txt = fp.read()
            if not isinstance(txt, unicode):
                txt = unicode(txt)
            log_lines.append(
                u"blocks.csv (raw): {0} caracteres, encoding={1}".format(
                    len(txt), enc
                )
            )
            return txt
        except Exception as ex:
            last_error = ex
            continue

    raise ValueError(
        u"No se pudo leer blocks.csv como texto: {0}".format(last_error)
    )


def save_blocks_snapshot(path, blocks_csv_text, log_lines):
    """Copia el mismo contenido que se manda al webhook en public/ para inspección."""
    with codecs.open(path, u"w", u"utf-8") as fp:
        fp.write(blocks_csv_text)
    log_lines.append(u"Copia resources/blocks.csv → {0}".format(path))


# =============================================================================
# Exportación a disco
# =============================================================================




def export_revit_elements_csv(path, element_rows, log_lines):
    """Exporta revit_elements.csv (UTF-8 con BOM para Excel)."""
    if not element_rows:
        fieldnames = [
            u"element_id",
            u"unique_id",
            u"category_name",
            u"family_name",
            u"type_name",
            u"level_name",
            u"element_name",
            u"macro_group",
            u"group_key",
        ] + list(SEMANTIC_CSV_COLUMNS) + ALL_BTZ_PARAMS
    else:
        fieldnames = list(element_rows[0].keys())

    with codecs.open(path, u"w", u"utf-8-sig") as fp:
        w = csv.DictWriter(
            fp,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        w.writeheader()
        for r in element_rows:
            row = {}
            for k in fieldnames:
                v = r.get(k, u"")
                if isinstance(v, (int, long)):
                    row[k] = v
                else:
                    row[k] = v if v is not None else u""
            w.writerow(row)

    log_lines.append(u"Guardado: {0}".format(path))


def export_revit_groups_csv(path, groups, log_lines):
    """
    revit_groups.csv: group_key, macro_group, count, category, family, type,
    level_names, sample_element_ids (listas como texto separado por ;).
    """
    fieldnames = [
        u"group_key",
        u"macro_group",
        u"count",
        u"category_name",
        u"family_name",
        u"type_name",
        u"level_names",
        u"sample_element_ids",
    ]
    with codecs.open(path, u"w", u"utf-8-sig") as fp:
        w = csv.DictWriter(
            fp,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        w.writeheader()
        for g in groups:
            w.writerow({
                u"group_key": g[u"group_key"],
                u"macro_group": g[u"macro_group"],
                u"count": g[u"count"],
                u"category_name": g[u"category_name"],
                u"family_name": g[u"family_name"],
                u"type_name": g[u"type_name"],
                u"level_names": u";".join(g[u"level_names"]),
                u"sample_element_ids": u";".join(
                    unicode(x) for x in g[u"sample_element_ids"]
                ),
            })

    log_lines.append(u"Guardado: {0}".format(path))


def save_groups_summary_txt(path, groups, element_rows, log_lines):
    """
    Resumen legible: cuántos grupos (group_key), elementos por grupo, totales.
    Complementa revit_groups.csv para ver de un vistazo el agrupamiento.
    """
    lines = [
        u"=== BTZ — Resumen de agrupación (Exportar grupos) ===",
        u"Elementos exportados (instancias en el barrido): {0}".format(len(element_rows)),
        u"Grupos distintos (group_key): {0}".format(len(groups)),
        u"",
        u"Formato group_key: macro|categoría|familia|tipo (ver build_group_key en el script).",
        u"Si hay muchos grupos con count=1, el modelo fragmenta tipos/familias; n8n recibe un grupo por combinación.",
        u"",
        u"--- Lista por grupo (orden alfabético por group_key) ---",
        u"count\tmacro_group\tcategory\tfamily\ttype\tgroup_key",
    ]
    for g in groups:
        gk = g[u"group_key"].replace(u"\t", u" ")
        lines.append(
            u"{0}\t{1}\t{2}\t{3}\t{4}\t{5}".format(
                g[u"count"],
                g[u"macro_group"],
                g[u"category_name"],
                g[u"family_name"],
                g[u"type_name"],
                gk,
            )
        )
    if groups:
        counts = [int(g[u"count"]) for g in groups]
        lines.append(u"")
        lines.append(
            u"Estadísticos count por grupo: min={0} max={1} media={2:.1f}".format(
                min(counts),
                max(counts),
                float(sum(counts)) / len(counts),
            )
        )
    with codecs.open(path, u"w", u"utf-8-sig") as fp:
        fp.write(u"\n".join(lines) + u"\n")
    log_lines.append(u"Resumen de grupos (legible): {0}".format(path))


def build_group_payload(
    doc,
    groups,
    blocks_struct,
    blocks_csv_text,
    enriched_revit_groups=None,
    grouping_diagnostics=None,
):
    """
    JSON para el webhook: mode, project_name, macro_groups,
    blocks_rows, revit_groups, blocks_csv_text (sin cambios para n8n).

    Campos aditivos (v2): enriched_revit_groups, grouping_diagnostics, payload_schema_version.
    """
    revit_groups_base = []
    for g in groups:
        revit_groups_base.append({
            u"group_key": g[u"group_key"],
            u"macro_group": g[u"macro_group"],
            u"count": int(g[u"count"]),
            u"category_name": g[u"category_name"],
            u"family_name": g[u"family_name"],
            u"type_name": g[u"type_name"],
            u"level_names": list(g[u"level_names"]),
            u"sample_element_ids": [int(x) for x in g[u"sample_element_ids"]],
        })

    # n8n consume normalmente revit_groups. Si hay refinados, usarlos acá
    # para que el mapeo salga por refined_group_key (más granular).
    revit_groups = list(revit_groups_base)
    if enriched_revit_groups:
        revit_groups = []
        for rg in enriched_revit_groups:
            revit_groups.append({
                u"group_key": rg.get(u"refined_group_key") or rg.get(u"base_group_key"),
                u"base_group_key": rg.get(u"base_group_key"),
                u"group_origin": rg.get(u"group_origin") or u"base",
                u"macro_group": rg.get(u"macro_group") or u"",
                u"count": int(rg.get(u"element_count") or 0),
                u"category_name": rg.get(u"category_name") or u"",
                u"family_name": rg.get(u"family_name") or u"",
                u"type_name": rg.get(u"type_name") or u"",
                u"level_names": [],
                u"sample_element_ids": [int(x) for x in (rg.get(u"element_ids") or [])[:50]],
                u"candidate_columns": rg.get(u"candidate_columns") or [],
                u"candidate_btz": rg.get(u"candidate_btz") or [],
                u"dominant_candidate": rg.get(u"dominant_candidate"),
                u"dominant_confidence": rg.get(u"dominant_confidence"),
                u"ambiguity_score": rg.get(u"ambiguity_score"),
                u"needs_review": bool(rg.get(u"needs_review")),
                u"split_reason": rg.get(u"split_reason") or u"",
                u"blocks_supporting_rows": rg.get(u"blocks_supporting_rows") or [],
                u"semantic_field_summary": rg.get(u"semantic_field_summary") or {},
                u"group_summary": rg.get(u"group_summary") or u"",
            })

    base = os.path.basename(BLOCKS_CSV_FILE) or u"blocks.csv"

    payload = {
        u"mode": u"analyze_revit_groups_against_blocks",
        u"project_name": _project_display_name(doc),
        u"macro_groups": list(MACRO_GROUPS_ORDER),
        u"blocks_rows": blocks_rows_for_payload(blocks_struct),
        u"blocks_csv_filename": base,
        u"blocks_csv_text": blocks_csv_text,
        u"revit_groups": revit_groups,
        u"revit_groups_base": revit_groups_base,
        u"payload_schema_version": 2,
    }
    if enriched_revit_groups is not None:
        payload[u"enriched_revit_groups"] = enriched_revit_groups
    if grouping_diagnostics is not None:
        payload[u"grouping_diagnostics"] = grouping_diagnostics
    return payload


def save_payload_json(path, payload, log_lines):
    with codecs.open(path, u"w", u"utf-8") as fp:
        fp.write(
            json.dumps(payload, ensure_ascii=False, indent=2)
        )
    log_lines.append(u"Guardado: {0}".format(path))




# =============================================================================
# Shared parameters (BTZ + Status / Source / Confidence)
# =============================================================================




def save_group_key_element_ids_json(path, element_rows, log_lines):
    m = map_group_key_to_elements(element_rows)
    with codecs.open(path, u"w", u"utf-8") as fp:
        fp.write(json.dumps(m, ensure_ascii=False, indent=2))
    log_lines.append(u"Guardado mapa group_key → ids: {0}".format(path))




# =============================================================================
# Respuesta n8n (group_btz_mapping_result)
# =============================================================================




def save_webhook_response(path, raw_text, log_lines):
    with codecs.open(path, u"w", u"utf-8") as fp:
        fp.write(raw_text)
    log_lines.append(u"Guardado: {0}".format(path))


def export_elements(doc, log_lines):
    """Alias de etapa pipeline: export_elements()."""
    return collect_revit_elements(doc, log_lines)


def build_base_groups(element_rows):
    """Alias de etapa pipeline: build_base_groups()."""
    return group_elements(element_rows)


def _build_manifest_from_refined_ai(refined_list):
    manifest = {}
    for r in refined_list:
        rk = r.get(u"refined_group_key")
        if not rk:
            continue
        needs_review = bool(r.get(u"needs_review"))
        origin = r.get(u"group_origin") or u"base"
        manifest[rk] = {
            u"base_group_key": r.get(u"base_group_key"),
            u"classification_hint": r.get(u"classification_hint") or (
                u"REVIEW" if needs_review else u"AUTO"
            ),
            u"btz_status_hint": u"REVIEW" if needs_review else (
                u"SPLIT_AUTO" if origin in (u"ai_split", u"forced_test_split") else u"AUTO"
            ),
            u"btz_source_hint": u"LLM_ONLY",
            u"dominant_code": u"",
            u"group_origin": origin,
            u"needs_review": needs_review,
        }
    return manifest


def _build_forced_test_split_parts(base_key, base_group, group_rows, insight, log_lines):
    """Split determinístico de prueba para validar el flujo end-to-end."""
    rows = group_rows or []
    if not rows:
        log_lines.append(
            u"[OPENAI-TEST] sin filas para split forzado en {0}".format(base_key[:100])
        )
        return []

    buckets = {}
    for r in rows:
        try:
            eid = int(r.get(u"element_id"))
        except Exception:
            continue
        lvl = unicode(r.get(u"level_name") or u"").strip() or u"(sin_nivel)"
        mk = unicode(r.get(u"mark") or u"").strip() or u"(sin_mark)"
        buckets.setdefault((lvl, mk), []).append(eid)

    if len(buckets) <= 1:
        log_lines.append(
            u"[OPENAI-TEST] split forzado omitido en {0}: solo 1 bucket level+mark".format(
                base_key[:100]
            )
        )
        return []

    items = sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)
    max_buckets = max(2, int(OPENAI_GROUPING_FORCE_SPLIT_MAX_BUCKETS or 2))
    if len(items) > max_buckets:
        kept = items[: max_buckets - 1]
        rest_ids = []
        for _, ids in items[max_buckets - 1 :]:
            rest_ids.extend(ids)
        kept.append(((u"(otros_niveles)", u"(otros_mark)"), rest_ids))
        items = kept

    parts = []
    for (lvl, mk), ids in items:
        if not ids:
            continue
        rk = u"{0}||ref|test:{1}__{2}".format(
            base_key,
            _slug_for_key(lvl),
            _slug_for_key(mk),
        )
        parts.append({
            u"base_group_key": base_key,
            u"refined_group_key": rk,
            u"group_origin": u"forced_test_split",
            u"element_ids": ids,
            u"element_count": len(ids),
            u"macro_group": base_group.get(u"macro_group") or u"",
            u"category_name": base_group.get(u"category_name") or u"",
            u"family_name": base_group.get(u"family_name") or u"",
            u"type_name": base_group.get(u"type_name") or u"",
            u"candidate_columns": insight.get(u"candidate_columns") or [],
            u"candidate_btz": insight.get(u"candidate_btz") or [],
            u"dominant_candidate": insight.get(u"dominant_candidate"),
            u"dominant_confidence": insight.get(u"dominant_confidence"),
            u"ambiguity_score": insight.get(u"ambiguity_score"),
            u"blocks_supporting_rows": insight.get(u"blocks_supporting_rows") or [],
            u"existing_btz_values_detected": insight.get(u"existing_btz_values_detected") or [],
            u"semantic_field_summary": {},
            u"should_split": True,
            u"split_reason": u"forced_test_split para validar pipeline",
            u"split_axis": u"level+mark",
            u"split_value": u"{0}|{1}".format(lvl, mk),
            u"classification_hint": u"AUTO",
            u"needs_review": False,
            u"group_summary": u"forced_test_split level+mark | {0} elems".format(len(ids)),
        })
    return parts


def verify_openai_grouping_runtime(log_lines):
    issues = []
    if not USE_OPENAI_GROUPING:
        log_lines.append(u"[OPENAI] OpenAI grouping desactivado por configuración.")
        return True

    api_key = unicode(OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", u"")).strip()
    if not api_key:
        issues.append(u"OPENAI_API_KEY faltante o vacía")
    else:
        log_lines.append(u"[OPENAI] OPENAI_API_KEY detectada")

    model_name = unicode(OPENAI_GROUPING_MODEL or u"").strip()
    if not model_name:
        issues.append(u"OPENAI_GROUPING_MODEL vacío")
    else:
        log_lines.append(u"[OPENAI] Modelo de agrupación: {0}".format(model_name))

    if not os.path.exists(BLOCKS_CSV_FILE):
        issues.append(u"blocks_normalized.csv no encontrado: {0}".format(BLOCKS_CSV_FILE))
    else:
        log_lines.append(
            u"[OPENAI] Fuente normalizada encontrada: {0}".format(BLOCKS_CSV_FILE)
        )

    if int(OPENAI_GROUPING_MAX_ELEMENTS_PER_GROUP or 0) <= 0:
        issues.append(u"OPENAI_GROUPING_MAX_ELEMENTS_PER_GROUP debe ser > 0")
    if int(OPENAI_GROUPING_TIMEOUT_SEC or 0) <= 0:
        issues.append(u"OPENAI_GROUPING_TIMEOUT_SEC debe ser > 0")
    if int(OPENAI_GROUPING_MAX_CANDIDATE_BLOCKS or 0) <= 0:
        issues.append(u"OPENAI_GROUPING_MAX_CANDIDATE_BLOCKS debe ser > 0")
    if int(OPENAI_GROUPING_WORKER_TIMEOUT_BUFFER_SEC or 0) <= 0:
        issues.append(u"OPENAI_GROUPING_WORKER_TIMEOUT_BUFFER_SEC debe ser > 0")

    if OPENAI_GROUPING_USE_EXTERNAL_PYTHON:
        if not os.path.isfile(OPENAI_GROUPING_HELPER_SCRIPT):
            issues.append(
                u"helper script no encontrado: {0}".format(
                    OPENAI_GROUPING_HELPER_SCRIPT
                )
            )
        else:
            log_lines.append(
                u"[OPENAI] Helper script: {0}".format(OPENAI_GROUPING_HELPER_SCRIPT)
            )
        ok, msg = _run_openai_worker_self_check(log_lines)
        if not ok:
            issues.append(msg)
    else:
        try:
            import openai  # noqa: F401

            log_lines.append(u"[OPENAI] SDK import local: OK")
        except Exception as ex:
            issues.append(u"openai package no disponible (local): {0}".format(ex))

    if issues:
        log_lines.append(u"[OPENAI] Verificación runtime FAILED")
        for item in issues:
            log_lines.append(u"[OPENAI] - {0}".format(item))
        return False

    log_lines.append(u"[OPENAI] Verificación runtime OK")
    return True


def _decode_bytes_to_unicode(value):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    try:
        return value.decode("utf-8")
    except Exception:
        try:
            return value.decode("cp1252")
        except Exception:
            try:
                return unicode(value)
            except Exception:
                return u""


def _run_subprocess_with_timeout(cmd, timeout_sec, env=None):
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    deadline = time.time() + max(1.0, float(timeout_sec or 1))
    while proc.poll() is None and time.time() < deadline:
        time.sleep(0.1)
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
    stdout, stderr = proc.communicate()
    return (
        int(proc.returncode if proc.returncode is not None else -1),
        _decode_bytes_to_unicode(stdout),
        _decode_bytes_to_unicode(stderr),
    )


def _run_openai_worker_self_check(log_lines):
    if not OPENAI_GROUPING_USE_EXTERNAL_PYTHON:
        return True, u"ok"
    cmd = [
        OPENAI_GROUPING_PYTHON_EXE,
        OPENAI_GROUPING_HELPER_SCRIPT,
        "--self-check",
    ]
    env = os.environ.copy()
    if OPENAI_API_KEY:
        env["OPENAI_API_KEY"] = OPENAI_API_KEY
    rc, out, err = _run_subprocess_with_timeout(
        cmd,
        timeout_sec=float(OPENAI_GROUPING_TIMEOUT_SEC) + 10.0,
        env=env,
    )
    if rc != 0:
        return (
            False,
            u"worker self-check falló (python={0}) rc={1} err={2}".format(
                OPENAI_GROUPING_PYTHON_EXE,
                rc,
                (err or out or u"").strip()[:220],
            ),
        )
    if out.strip():
        log_lines.append(u"[OPENAI] Worker self-check: {0}".format(out.strip()[:220]))
    return True, u"ok"


def _call_openai_grouping_worker(group_scenario, log_lines):
    in_path = get_public_file(
        u"openai_grouping_worker_input.json", u"legacy", fallback=False
    )
    out_path = get_public_file(
        u"openai_grouping_worker_output.json", u"legacy", fallback=False
    )
    with codecs.open(in_path, u"w", u"utf-8") as fp:
        fp.write(json.dumps(group_scenario, ensure_ascii=False, indent=2))

    cmd = [
        OPENAI_GROUPING_PYTHON_EXE,
        OPENAI_GROUPING_HELPER_SCRIPT,
        "--input",
        in_path,
        "--output",
        out_path,
        "--model",
        unicode(OPENAI_GROUPING_MODEL),
        "--timeout",
        unicode(OPENAI_GROUPING_TIMEOUT_SEC),
    ]
    env = os.environ.copy()
    if OPENAI_API_KEY:
        env["OPENAI_API_KEY"] = OPENAI_API_KEY

    total_timeout = float(OPENAI_GROUPING_TIMEOUT_SEC) + float(
        OPENAI_GROUPING_WORKER_TIMEOUT_BUFFER_SEC
    )
    rc, out, err = _run_subprocess_with_timeout(cmd, timeout_sec=total_timeout, env=env)
    if rc != 0:
        raise RuntimeError(
            u"worker OpenAI falló rc={0} err={1}".format(
                rc, (err or out or u"").strip()[:320]
            )
        )
    if not os.path.isfile(out_path):
        raise RuntimeError(u"worker OpenAI no generó output: {0}".format(out_path))

    with codecs.open(out_path, u"r", u"utf-8-sig") as fp:
        worker_result = json.loads(fp.read())
    if not isinstance(worker_result, dict):
        raise RuntimeError(u"worker OpenAI devolvió payload inválido")
    if not worker_result.get(u"ok"):
        raise RuntimeError(
            u"worker OpenAI reportó error: {0}".format(
                worker_result.get(u"error") or u"(sin detalle)"
            )
        )
    for line in worker_result.get(u"logs") or []:
        log_lines.append(u"[OPENAI-WORKER] {0}".format(unicode(line)))
    ai_result = worker_result.get(u"ai_result")
    if not isinstance(ai_result, dict):
        raise RuntimeError(u"worker OpenAI no devolvió ai_result válido")
    return ai_result


def _load_openai_grouping_cache(path, log_lines):
    if not path or (not os.path.isfile(path)):
        return {}
    try:
        with codecs.open(path, u"r", u"utf-8-sig") as fp:
            data = json.loads(fp.read())
        if isinstance(data, dict):
            log_lines.append(u"[OPENAI] Cache cargada: {0} entradas".format(len(data)))
            return data
    except Exception as ex:
        log_lines.append(u"[OPENAI] Cache inválida ({0}); se reinicia.".format(ex))
    return {}


def _save_openai_grouping_cache(path, cache_data, log_lines):
    try:
        with codecs.open(path, u"w", u"utf-8") as fp:
            fp.write(json.dumps(cache_data, ensure_ascii=False, indent=2))
        log_lines.append(u"[OPENAI] Cache guardada: {0}".format(path))
    except Exception as ex:
        log_lines.append(u"[OPENAI] No se pudo guardar cache: {0}".format(ex))


def _norm_text(value):
    return unicode(value or u"").strip()


def _scenario_hash(scenario):
    payload = json.dumps(scenario, ensure_ascii=False, sort_keys=True)
    if isinstance(payload, unicode):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            chunk = fp.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _cache_ttl_seconds():
    try:
        days = float(OPENAI_GROUPING_CACHE_TTL_DAYS or 0)
    except Exception:
        days = 0.0
    if days <= 0:
        return 0
    return int(days * 24 * 60 * 60)


def _is_cache_entry_valid(
    cache_entry,
    expected_scenario_hash,
    expected_model,
    expected_prompt_version,
    expected_blocks_hash,
    now_epoch,
):
    if not isinstance(cache_entry, dict):
        return False, u"cache_entry_invalida"
    if cache_entry.get(u"scenario_hash") != expected_scenario_hash:
        return False, u"scenario_hash_changed"
    if _norm_text(cache_entry.get(u"model")) != _norm_text(expected_model):
        return False, u"model_changed"
    if _norm_text(cache_entry.get(u"prompt_version")) != _norm_text(
        expected_prompt_version
    ):
        return False, u"prompt_version_changed"
    if _norm_text(cache_entry.get(u"blocks_source_hash")) != _norm_text(
        expected_blocks_hash
    ):
        return False, u"blocks_source_hash_changed"
    ttl_sec = _cache_ttl_seconds()
    if ttl_sec > 0:
        try:
            ts = int(cache_entry.get(u"timestamp_epoch") or 0)
        except Exception:
            ts = 0
        if ts <= 0:
            return False, u"timestamp_missing"
        if (now_epoch - ts) > ttl_sec:
            return False, u"ttl_expired"
    if not isinstance(cache_entry.get(u"ai_result"), dict):
        return False, u"ai_result_missing"
    return True, u"ok"


def _group_rows_by_base_group(refined_rows):
    out = {}
    for r in refined_rows:
        bk = r.get(u"base_group_key") or u""
        out.setdefault(bk, []).append(r)
    return out


def should_use_openai_for_group(group_insight):
    element_count = int(group_insight.get(u"element_count", 0) or 0)
    ambiguity_score = float(group_insight.get(u"ambiguity_score", 0) or 0)
    dominant_conf = float(group_insight.get(u"dominant_confidence", 0) or 0)

    if element_count <= 1:
        return False, u"element_count<=1"
    if OPENAI_GROUPING_AGGRESSIVE_MODE:
        return True, u"aggressive_mode_all_groups"
    if element_count > OPENAI_GROUPING_MAX_ELEMENTS_PER_GROUP:
        return False, u"element_count>max_per_group"
    if ambiguity_score >= float(OPENAI_GROUPING_AMBIGUITY_MIN):
        return True, u"ambiguity_score>={0}".format(OPENAI_GROUPING_AMBIGUITY_MIN)
    if dominant_conf < float(OPENAI_GROUPING_DOMINANT_CONF_MIN):
        return True, u"dominant_conf<{0}".format(OPENAI_GROUPING_DOMINANT_CONF_MIN)
    return False, u"grupo_obvio_por_heuristico"


def _run_openai_grouping_pipeline(base_groups, revit_elements, blocks_csv_path, pipeline_log):
    """
    Pipeline:
      load_normalized_blocks_csv()
      build_grouping_scenarios()
      analyze_grouping_with_openai()
      build_refined_groups_from_ai()
    """
    normalized_blocks = load_normalized_blocks_csv(blocks_csv_path, pipeline_log)
    scenarios = build_grouping_scenarios(
        base_groups,
        revit_elements,
        normalized_blocks,
        max_elements_per_group=OPENAI_GROUPING_MAX_ELEMENTS_PER_GROUP,
        max_candidate_blocks=OPENAI_GROUPING_MAX_CANDIDATE_BLOCKS,
        max_comment_chars=OPENAI_GROUPING_MAX_COMMENT_CHARS,
        max_group_summary_chars=OPENAI_GROUPING_MAX_GROUP_SUMMARY_CHARS,
        log_lines=pipeline_log,
    )
    project_cfg = load_project_config(pipeline_log)
    cfg_issues = validate_project_config(project_cfg)
    if cfg_issues:
        for issue in cfg_issues:
            pipeline_log.append(u"[PROJECT-CONFIG] warning: {0}".format(issue))
    else:
        pipeline_log.append(
            u"[PROJECT-CONFIG] cargada. rule_mode={0}".format(
                project_cfg.get(u"rule_mode")
            )
        )
    for i, sc in enumerate(scenarios):
        scenarios[i] = apply_project_soft_logic_to_scenario(sc, project_cfg, pipeline_log)

    enriched = enrich_groups_with_blocks(
        revit_elements, base_groups, {u"rows": normalized_blocks}, ALL_BTZ_PARAMS, pipeline_log
    )
    enriched_by_key = {e[u"base_group_key"]: e for e in enriched}

    heuristic_log = []
    heuristic_refined, heuristic_manifest, _heur_diag = split_ambiguous_groups(
        enriched, revit_elements, heuristic_log
    )
    heuristic_refined_by_base = _group_rows_by_base_group(heuristic_refined)

    client = None
    if not OPENAI_GROUPING_USE_EXTERNAL_PYTHON:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=OPENAI_API_KEY, timeout=float(OPENAI_GROUPING_TIMEOUT_SEC)
            )
        except Exception as ex:
            pipeline_log.append(
                u"[IA grouping] OpenAI SDK/cliente local no disponible: {0}. Se usará fallback.".format(
                    ex
                )
            )
            client = None
        if not OPENAI_API_KEY:
            pipeline_log.append(
                u"[IA grouping] OPENAI_API_KEY no configurada en entorno; se usará fallback."
            )
            client = None

    blocks_source_hash = u""
    try:
        blocks_source_hash = _sha256_file(blocks_csv_path)
        pipeline_log.append(
            u"[OPENAI] blocks_source_hash={0}".format(blocks_source_hash[:16])
        )
    except Exception as ex:
        pipeline_log.append(u"[OPENAI] No se pudo calcular blocks_source_hash: {0}".format(ex))

    cache = _load_openai_grouping_cache(OPENAI_GROUPING_CACHE_PATH, pipeline_log)
    cache_changed = False
    groups_by_key = {g[u"group_key"]: g for g in base_groups}
    elements_by_id = {int(r[u"element_id"]): r for r in revit_elements}
    elements_by_group = {}
    for row in revit_elements:
        gk = row.get(u"group_key")
        if gk:
            elements_by_group.setdefault(gk, []).append(row)

    refined_all = []
    split_groups = 0
    fallback_groups = 0
    forced_test_split_groups = 0
    openai_groups = 0
    cache_hits = 0
    for scenario in scenarios:
        base_key = scenario.get(u"base_group_key")
        base_group = groups_by_key.get(base_key)
        if base_group is None:
            continue
        insight = enriched_by_key.get(base_key, {})
        use_ai, reason_ai = should_use_openai_for_group(insight)

        element_count = int(insight.get(u"element_count") or scenario.get(u"element_count") or 0)
        candidate_blocks_count = len(scenario.get(u"candidate_blocks") or [])
        ambiguity_score = float(insight.get(u"ambiguity_score", 0) or 0)
        dominant_conf = float(insight.get(u"dominant_confidence", 0) or 0)
        pipeline_log.append(
            u"[OPENAI] Base group {0}".format(base_key)
        )
        pipeline_log.append(
            u"[OPENAI] element_count={0} candidate_blocks={1} ambiguity_score={2:.3f} dominant_conf={3:.3f}".format(
                element_count,
                candidate_blocks_count,
                ambiguity_score,
                dominant_conf,
            )
        )
        pipeline_log.append(
            u"[OPENAI] decision use_ai={0} reason={1}".format(use_ai, reason_ai)
        )

        parts = None
        if use_ai and (OPENAI_GROUPING_USE_EXTERNAL_PYTHON or client is not None):
            openai_groups += 1
            shash = _scenario_hash(scenario)
            cache_entry = cache.get(base_key) or {}
            ai_result = None
            now_epoch = int(time.time())
            cache_ok, cache_reason = _is_cache_entry_valid(
                cache_entry=cache_entry,
                expected_scenario_hash=shash,
                expected_model=OPENAI_GROUPING_MODEL,
                expected_prompt_version=OPENAI_GROUPING_PROMPT_VERSION,
                expected_blocks_hash=blocks_source_hash,
                now_epoch=now_epoch,
            )
            if cache_ok and (not OPENAI_GROUPING_IGNORE_CACHE):
                ai_result = cache_entry.get(u"ai_result")
                cache_hits += 1
                pipeline_log.append(
                    u"[OPENAI] cache hit base_group_key={0}".format(base_key[:100])
                )
            else:
                if OPENAI_GROUPING_IGNORE_CACHE:
                    pipeline_log.append(
                        u"[OPENAI] cache omitida por OPENAI_GROUPING_IGNORE_CACHE=True"
                    )
                if cache_entry:
                    pipeline_log.append(
                        u"[OPENAI] cache invalidado {0}: {1}".format(
                            base_key[:100], cache_reason
                        )
                    )
                pipeline_log.append(
                    u"[OPENAI] scenario sent to model {0}".format(OPENAI_GROUPING_MODEL)
                )
                try:
                    if OPENAI_GROUPING_USE_EXTERNAL_PYTHON:
                        ai_result = _call_openai_grouping_worker(
                            scenario, pipeline_log
                        )
                    else:
                        ai_result = analyze_grouping_with_openai(
                            scenario,
                            client=client,
                            model=OPENAI_GROUPING_MODEL,
                            timeout_sec=OPENAI_GROUPING_TIMEOUT_SEC,
                            log_lines=pipeline_log,
                        )
                except Exception as ex:
                    pipeline_log.append(
                        u"[OPENAI] invalid response/error: {0}".format(unicode(ex))
                    )
                    scenario_ids = []
                    for _e in scenario.get(u"elements") or []:
                        _id = unicode(_e.get(u"element_id") or u"").strip()
                        if _id:
                            scenario_ids.append(_id)
                    ai_result = {
                        u"base_group_key": base_key,
                        u"should_split": False,
                        u"group_count": 1,
                        u"groups": [
                            {
                                u"refined_group_key": u"",
                                u"label": u"base",
                                u"reason": u"fallback por error worker OpenAI",
                                u"element_ids": scenario_ids,
                            }
                        ],
                        u"unassigned_element_ids": [],
                        u"confidence": 0.0,
                        u"summary": u"fallback por error worker OpenAI",
                    }
                    pipeline_log.append(
                        u"[OPENAI] fallback applied: keep base group unchanged"
                    )
                cache[base_key] = {
                    u"scenario_hash": shash,
                    u"timestamp": datetime.datetime.utcnow().isoformat() + u"Z",
                    u"timestamp_epoch": now_epoch,
                    u"model": OPENAI_GROUPING_MODEL,
                    u"prompt_version": OPENAI_GROUPING_PROMPT_VERSION,
                    u"blocks_source_hash": blocks_source_hash,
                    u"ai_result": ai_result,
                }
                cache_changed = True

            parts = build_refined_groups_from_ai(
                ai_result,
                base_group,
                elements_by_id,
                log_lines=pipeline_log,
            )
            pipeline_log.append(
                u"[OPENAI] result: should_split={0} group_count={1} confidence={2}".format(
                    bool(ai_result.get(u"should_split")),
                    int(ai_result.get(u"group_count") or len(ai_result.get(u"groups") or [])),
                    ai_result.get(u"confidence"),
                )
            )
            pipeline_log.append(
                u"[OPENAI] refined groups created: {0}".format(len(parts))
            )
            if (
                OPENAI_GROUPING_FORCE_SPLIT_FOR_TEST
                and (not bool(ai_result.get(u"should_split")))
                and len(parts) == 1
                and ((parts[0].get(u"group_origin") or u"base") == u"base")
                and element_count >= int(OPENAI_GROUPING_FORCE_SPLIT_MIN_GROUP_SIZE or 1)
            ):
                forced_parts = _build_forced_test_split_parts(
                    base_key=base_key,
                    base_group=base_group,
                    group_rows=elements_by_group.get(base_key) or [],
                    insight=insight or {},
                    log_lines=pipeline_log,
                )
                if forced_parts:
                    parts = forced_parts
                    forced_test_split_groups += 1
                    split_groups += 1
                    pipeline_log.append(
                        u"[OPENAI-TEST] forced_test_split aplicado en {0}: {1} subgrupos".format(
                            base_key[:100], len(parts)
                        )
                    )
            # Si la IA no separa y hay conflicto semantico del proyecto,
            # aplicar split deterministico por token de proyecto.
            if (
                len(parts) == 1
                and ((parts[0].get(u"group_origin") or u"base") == u"base")
            ):
                proj_parts = build_project_rule_split_parts(
                    base_key=base_key,
                    base_group=base_group,
                    group_rows=elements_by_group.get(base_key) or [],
                    scenario=scenario,
                    insight=insight or {},
                    project_cfg=project_cfg or {},
                    log_lines=pipeline_log,
                )
                if proj_parts:
                    parts = proj_parts
                    split_groups += 1
            if bool(ai_result.get(u"should_split")):
                split_groups += 1
            if any((p.get(u"group_origin") or u"") == u"base" for p in parts):
                fallback_groups += 1
        else:
            parts = heuristic_refined_by_base.get(base_key) or []
            if not parts:
                ai_result = {
                    u"base_group_key": base_key,
                    u"should_split": False,
                    u"group_count": 1,
                    u"groups": [],
                    u"confidence": 0.0,
                    u"summary": u"fallback por grupo no ambiguo o runtime no disponible",
                }
                parts = build_refined_groups_from_ai(
                    ai_result,
                    base_group,
                    elements_by_id,
                    log_lines=pipeline_log,
                )
            pipeline_log.append(
                u"[OPENAI] skip IA, usando heurístico directo ({0} refined)".format(
                    len(parts)
                )
            )
        refined_all.extend(parts)

    if cache_changed:
        _save_openai_grouping_cache(OPENAI_GROUPING_CACHE_PATH, cache, pipeline_log)

    manifest_ai = _build_manifest_from_refined_ai(refined_all)
    manifest = dict(heuristic_manifest)
    manifest.update(manifest_ai)
    diagnostics = {
        u"base_groups_count": len(base_groups),
        u"refined_groups_count": len(refined_all),
        u"pipeline_mode": u"openai_grouping",
        u"openai_model": OPENAI_GROUPING_MODEL,
        u"split_base_groups_count": split_groups,
        u"groups_with_base_fallback_count": fallback_groups,
        u"openai_groups_count": openai_groups,
        u"openai_cache_hits_count": cache_hits,
        u"forced_test_split_groups_count": forced_test_split_groups,
        u"project_config_rule_mode": project_cfg.get(u"rule_mode") if isinstance(project_cfg, dict) else u"",
        u"status_hint_counts": {
            u"AUTO": len([x for x in refined_all if not x.get(u"needs_review")]),
            u"REVIEW": len([x for x in refined_all if x.get(u"needs_review")]),
            u"SPLIT_AUTO": len(
                [
                    x
                    for x in refined_all
                    if (
                        x.get(u"group_origin") in (u"ai_split", u"forced_test_split")
                    ) and (not x.get(u"needs_review"))
                ]
            ),
        },
    }
    return refined_all, manifest, diagnostics


# =============================================================================
# Aplicación por grupo (slots libres locales; sin checklist)
# =============================================================================




# =============================================================================
# Webhook
# =============================================================================


def _format_webhook_exception(ex):
    """
    Mensaje claro para timeouts .NET (10060), n8n caído, firewall, etc.
    """
    try:
        msg = unicode(ex)
    except Exception:
        msg = u"(sin mensaje)"
    try:
        if hasattr(ex, u"InnerException") and ex.InnerException is not None:
            msg += u" | " + unicode(ex.InnerException)
    except Exception:
        pass
    low = msg.lower()
    if (
        u"10060" in msg
        or u"timed out" in low
        or u"timeout" in low
        or u"no properly respond" in low
        or u"failed to respond" in low
    ):
        return (
            u"Timeout o sin respuesta del servidor (n8n / red). "
            u"Revisá: internet, firewall, VPN, que el workflow en n8n esté ACTIVO, "
            u"y probá subir N8N_TIMEOUT_SEC (ahora {0}s). "
            u"El payload ya quedó en public/payload_groups.json para enviar a mano.\n\n"
            u"Detalle técnico: {1}"
        ).format(N8N_TIMEOUT_SEC, msg[:450])
    return u"Error al llamar al webhook:\n{0}".format(msg[:600])


def call_webhook(payload, log_lines):
    """
    POST JSON al webhook. Lanza ValueError ante timeout, HTTP != 200, vacío o JSON inválido.

    En IronPython, los timeouts suelen aparecer como System.IO.IOException (socket 10060),
    no siempre como urllib2.URLError.
    """
    url = N8N_WEBHOOK_URL
    if not url:
        raise ValueError(u"N8N_WEBHOOK_URL vacía")

    data = json.dumps(payload, ensure_ascii=False)
    if isinstance(data, unicode):
        data = data.encode(u"utf-8")

    req = urllib2.Request(
        url,
        data,
        headers={u"Content-Type": u"application/json; charset=utf-8"},
    )

    log_lines.append(
        u"Webhook: POST (timeout {0}s) → {1}".format(N8N_TIMEOUT_SEC, url)
    )
    print(u"[ExportarGrupos] POST {0}".format(url))
    try:
        resp = urllib2.urlopen(req, timeout=N8N_TIMEOUT_SEC)
    except urllib2.HTTPError as e:
        try:
            body = e.read()
            if hasattr(body, u"decode"):
                body = body.decode(u"utf-8")
        except Exception:
            body = u""
        log_lines.append(u"HTTP {0}: {1}".format(e.code, body[:500]))
        raise ValueError(u"n8n HTTP {0}".format(e.code))
    except urllib2.URLError as e:
        msg = unicode(e.reason) if e.reason else u"red"
        raise ValueError(_format_webhook_exception(e))
    except IOError as e:
        raise ValueError(_format_webhook_exception(e))
    except Exception as e:
        # IronPython: System.IO.IOException, SocketException 10060, etc.
        raise ValueError(_format_webhook_exception(e))

    raw = resp.read()
    if hasattr(raw, u"decode"):
        raw = raw.decode(u"utf-8")

    code = resp.getcode()
    if code != 200:
        raise ValueError(u"HTTP {0}".format(code))
    if not (raw or u"").strip():
        raise ValueError(u"Respuesta vacía")

    try:
        parsed = json.loads(raw)
    except ValueError as e:
        raise ValueError(u"JSON inválido: {0}".format(e))

    log_lines.append(u"Webhook OK, respuesta {0} caracteres".format(len(raw)))
    return parsed, raw


# =============================================================================
# main
# =============================================================================


def main_send_payload_file_only():
    """
    Solo envía a n8n el contenido de PAYLOAD_GROUPS_JSON_PATH (sin barrer el modelo).
    """
    log_lines = []
    log_lines.append(u"Modo: enviar JSON desde disco → n8n")
    log_lines.append(u"Archivo: {0}".format(PAYLOAD_GROUPS_JSON_PATH))
    log_lines.append(u"Webhook: {0}".format(N8N_WEBHOOK_URL))

    try:
        _ensure_public_dir()
    except Exception as ex:
        forms.alert(
            u"No se pudo crear public/: {0}".format(ex),
            title=u"Exportar grupos",
            warn_icon=True,
        )
        return

    path_log = get_public_file(u"run_log.txt", u"debug", fallback=False)
    path_webhook_resp = WEBHOOK_RESPONSE_JSON_PATH
    doc = revit.doc

    if not os.path.isfile(PAYLOAD_GROUPS_JSON_PATH):
        forms.alert(
            u"No se encontró el payload:\n{0}\n\n"
            u"Poné ahí el JSON o generá uno con SEND_PAYLOAD_FILE_ONLY = False.".format(
                PAYLOAD_GROUPS_JSON_PATH
            ),
            title=u"Exportar grupos",
            warn_icon=True,
        )
        return

    try:
        payload = load_payload_from_json_file(PAYLOAD_GROUPS_JSON_PATH, log_lines)
        if not SEND_TO_WEBHOOK:
            log_lines.append(u"SEND_TO_WEBHOOK=False: no se envía.")
            append_run_log(path_log, log_lines)
            forms.alert(
                u"Payload cargado pero SEND_TO_WEBHOOK está en False.",
                title=u"Exportar grupos",
                warn_icon=True,
            )
            print(u"\n".join(log_lines))
            return

        parsed, webhook_raw = call_webhook(payload, log_lines)
        if SAVE_WEBHOOK_RESPONSE and webhook_raw is not None:
            save_webhook_response(path_webhook_resp, webhook_raw, log_lines)

        if APPLY_WEBHOOK_RESULTS:
            try_apply_webhook_response(doc, parsed, None, log_lines)

        log_lines.append(u"Fin OK")
    except Exception as ex:
        log_lines.append(u"ERROR: {0}".format(ex))
        append_run_log(path_log, log_lines)
        forms.alert(
            u"{0}\n\nDetalle en run_log.txt".format(ex),
            title=u"Exportar grupos",
            warn_icon=True,
        )
        print(u"\n".join(log_lines))
        return

    append_run_log(path_log, log_lines)
    if not APPLY_WEBHOOK_RESULTS:
        forms.alert(
            u"Enviado a n8n.\n\nRespuesta guardada en:\n{0}".format(path_webhook_resp),
            title=u"Exportar grupos",
            warn_icon=False,
        )
    print(u"\n".join(log_lines))


def main():
    if SEND_PAYLOAD_FILE_ONLY:
        main_send_payload_file_only()
        return

    log_lines = []
    doc = revit.doc

    log_lines.append(u"Inicio ExportarGrupos (export completo)")
    log_lines.append(u"PUBLIC_DIR={0}".format(PUBLIC_DIR))
    log_lines.append(
        u"EXPORT_ONLY={0} SEND_TO_WEBHOOK={1} APPLY_WEBHOOK_RESULTS={2}".format(
            EXPORT_ONLY, SEND_TO_WEBHOOK, APPLY_WEBHOOK_RESULTS
        )
    )
    log_lines.append(
        u"USE_OPENAI_GROUPING={0} OPENAI_GROUPING_MODEL={1}".format(
            USE_OPENAI_GROUPING, OPENAI_GROUPING_MODEL
        )
    )
    log_lines.append(
        u"OPENAI_GROUPING_PROMPT_VERSION={0} CACHE_TTL_DAYS={1}".format(
            OPENAI_GROUPING_PROMPT_VERSION, OPENAI_GROUPING_CACHE_TTL_DAYS
        )
    )
    log_lines.append(
        u"OPENAI_GROUPING_AGGRESSIVE_MODE={0} IGNORE_CACHE={1} MAX_ELEMENTS_PER_GROUP={2}".format(
            OPENAI_GROUPING_AGGRESSIVE_MODE,
            OPENAI_GROUPING_IGNORE_CACHE,
            OPENAI_GROUPING_MAX_ELEMENTS_PER_GROUP,
        )
    )
    log_lines.append(
        u"OPENAI_GROUPING_FORCE_SPLIT_FOR_TEST={0} MIN_GROUP_SIZE={1} MAX_BUCKETS={2}".format(
            OPENAI_GROUPING_FORCE_SPLIT_FOR_TEST,
            OPENAI_GROUPING_FORCE_SPLIT_MIN_GROUP_SIZE,
            OPENAI_GROUPING_FORCE_SPLIT_MAX_BUCKETS,
        )
    )
    log_lines.append(
        u"OPENAI_GROUPING_USE_EXTERNAL_PYTHON={0} PYTHON_EXE={1}".format(
            OPENAI_GROUPING_USE_EXTERNAL_PYTHON, OPENAI_GROUPING_PYTHON_EXE
        )
    )
    log_lines.append(u"BLOCKS_CSV_FILE={0}".format(BLOCKS_CSV_FILE))

    try:
        _ensure_public_dir()
        ensure_project_config_files(log_lines)
        refresh_blocks_semantic_from_csv(BLOCKS_CSV_FILE, log_lines)
    except Exception as ex:
        forms.alert(
            u"No se pudo crear public/: {0}".format(ex),
            title=u"Exportar grupos",
            warn_icon=True,
        )
        return

    path_elements = get_public_file(u"revit_elements.csv", u"optional", fallback=False)
    path_groups = get_public_file(u"revit_groups.csv", u"optional", fallback=False)
    path_payload = get_public_file(u"payload_groups.json", u"legacy", fallback=False)
    path_blocks_snapshot = get_public_file(
        u"blocks_snapshot.csv", u"optional", fallback=False
    )
    path_log = get_public_file(u"run_log.txt", u"debug", fallback=False)
    path_webhook_resp = WEBHOOK_RESPONSE_JSON_PATH
    path_gk_ids = GROUP_KEY_ELEMENT_IDS_JSON_PATH

    openai_runtime_ok = verify_openai_grouping_runtime(log_lines)
    if USE_OPENAI_GROUPING and not openai_runtime_ok:
        log_lines.append(
            u"[OPENAI] Fallback a agrupación heurística porque runtime OpenAI no está listo."
        )

    try:
        element_rows = export_elements(doc, log_lines)
        groups = build_base_groups(element_rows)

        export_revit_elements_csv(path_elements, element_rows, log_lines)
        export_revit_groups_csv(path_groups, groups, log_lines)
        path_groups_summary = get_public_file(
            u"groups_summary.txt", u"optional", fallback=False
        )
        save_groups_summary_txt(path_groups_summary, groups, element_rows, log_lines)
        save_group_key_element_ids_json(path_gk_ids, element_rows, log_lines)
        log_lines.append(
            u"Agrupación: {0} elementos → {1} grupos (group_key). Detalle: groups_summary.txt y revit_groups.csv.".format(
                len(element_rows),
                len(groups),
            )
        )

        blocks_struct = load_blocks_csv(BLOCKS_CSV_FILE, log_lines)
        blocks_csv_text = read_blocks_csv_raw(BLOCKS_CSV_FILE, log_lines)
        save_blocks_snapshot(path_blocks_snapshot, blocks_csv_text, log_lines)

        # build_grouping_scenarios() + analyze_grouping_with_openai() + build_refined_groups_from_ai()
        pipeline_log = []
        if USE_OPENAI_GROUPING and openai_runtime_ok:
            refined_list, manifest, diagnostics = _run_openai_grouping_pipeline(
                groups, element_rows, BLOCKS_CSV_FILE, pipeline_log
            )
        else:
            if not USE_OPENAI_GROUPING:
                pipeline_log.append(
                    u"[IA grouping] desactivado (USE_OPENAI_GROUPING=False), se usa split heurístico."
                )
            else:
                pipeline_log.append(
                    u"[IA grouping] runtime no disponible, se usa split heurístico."
                )
            enriched = enrich_groups_with_blocks(
                element_rows, groups, blocks_struct, ALL_BTZ_PARAMS, pipeline_log
            )
            refined_list, manifest, diagnostics = split_ambiguous_groups(
                enriched, element_rows, pipeline_log
            )
        save_refined_group_key_element_ids(
            REFINED_GROUP_KEY_ELEMENT_IDS_JSON_PATH, refined_list, pipeline_log
        )
        save_refined_groups_manifest(
            REFINED_GROUPS_MANIFEST_JSON_PATH, manifest, pipeline_log
        )
        pl_header = [
            u"--- {0} (agrupación BTZ) ---".format(
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ),
            u"Grupos base: {0} | Refinados: {1}".format(
                diagnostics[u"base_groups_count"],
                diagnostics[u"refined_groups_count"],
            ),
            u"Pipeline mode: {0}".format(
                diagnostics.get(u"pipeline_mode", u"heuristic_grouping")
            ),
            u"Hints status (preflight): {0}".format(
                diagnostics.get(u"status_hint_counts", {})
            ),
        ]
        save_grouping_pipeline_log(GROUPING_PIPELINE_LOG_PATH, pl_header, pipeline_log)
        log_lines.extend(pipeline_log)

        enriched_payload = build_enriched_revit_groups_for_payload(refined_list)
        payload = build_group_payload(
            doc,
            groups,
            blocks_struct,
            blocks_csv_text,
            enriched_revit_groups=enriched_payload,
            grouping_diagnostics=diagnostics,
        )
        save_payload_json(path_payload, payload, log_lines)

        parsed = None
        webhook_raw = None
        if not EXPORT_ONLY and SEND_TO_WEBHOOK:
            try:
                parsed, webhook_raw = call_webhook(payload, log_lines)
                if SAVE_WEBHOOK_RESPONSE and webhook_raw is not None:
                    save_webhook_response(path_webhook_resp, webhook_raw, log_lines)
            except Exception as ex:
                log_lines.append(u"--- Webhook: falló (la exportación en public/ ya está guardada) ---")
                log_lines.append(unicode(ex))
                try:
                    forms.alert(
                        u"{0}\n\n"
                        u"Los CSV y payload_groups.json ya están en public/. "
                        u"Podés reenviar el JSON a n8n a mano o ejecutar de nuevo.".format(
                            unicode(ex)
                        ),
                        title=u"Exportar grupos — webhook",
                        warn_icon=True,
                    )
                except Exception:
                    pass
        elif EXPORT_ONLY:
            log_lines.append(
                u"EXPORT_ONLY=True: no se envía al webhook (payload ya en disco)."
            )
        elif not SEND_TO_WEBHOOK:
            log_lines.append(u"SEND_TO_WEBHOOK=False: no se envía al webhook.")

        parsed_apply = parsed
        if APPLY_WEBHOOK_RESULTS and parsed_apply is None and os.path.isfile(
            path_webhook_resp
        ):
            parsed_apply = load_payload_from_json_file(path_webhook_resp, log_lines)
            log_lines.append(
                u"Aplicación: usando respuesta guardada en webhook_response.json."
            )

        if APPLY_WEBHOOK_RESULTS:
            try_apply_webhook_response(doc, parsed_apply, element_rows, log_lines)

        log_lines.append(u"Fin OK")
    except Exception as ex:
        log_lines.append(u"ERROR: {0}".format(ex))
        append_run_log(path_log, log_lines)
        forms.alert(
            u"{0}\n\nDetalle en run_log.txt".format(ex),
            title=u"Exportar grupos",
            warn_icon=True,
        )
        print(u"\n".join(log_lines))
        return

    append_run_log(path_log, log_lines)

    summary = (
        u"Exportación completada.\n\n"
        u"• {0}\n"
        u"• {1}\n"
        u"• {2}\n"
        u"• {3} (copia de blocks_normalized.csv)\n"
        u"• {4}\n"
        u"• {5}\n"
        u"• {6}\n"
        u"\nElementos: {7} | Grupos base (group_key): {8}"
    ).format(
        path_elements,
        path_groups,
        path_payload,
        path_blocks_snapshot,
        REFINED_GROUP_KEY_ELEMENT_IDS_JSON_PATH,
        REFINED_GROUPS_MANIFEST_JSON_PATH,
        GROUPING_PIPELINE_LOG_PATH,
        len(element_rows),
        len(groups),
    )
    if not EXPORT_ONLY and SEND_TO_WEBHOOK:
        summary += u"\n\nRespuesta webhook: {0}".format(path_webhook_resp)
    summary += u"\n\nMapa group_key→ids: {0}".format(path_gk_ids)
    summary += u"\nResumen de grupos (conteos): {0}".format(
        get_public_file(u"groups_summary.txt", u"optional", fallback=False)
    )
    if EXPORT_APPLY_RESULTS_TXT:
        summary += u"\nResultados aplicados (si hubo): {0}".format(
            get_public_file(u"apply_results.txt", u"legacy", fallback=False)
        )

    if not APPLY_WEBHOOK_RESULTS:
        summary += (
            u"\n\nSiguiente paso: botón «Ejecutar automático» para aplicar BTZ "
            u"desde public/webhook_response.json al modelo."
        )
        forms.alert(summary, title=u"Exportar grupos", warn_icon=False)
    else:
        log_lines.append(summary)
        print(summary)

    print(u"\n".join(log_lines))


if __name__ == u"__main__":
    main()
