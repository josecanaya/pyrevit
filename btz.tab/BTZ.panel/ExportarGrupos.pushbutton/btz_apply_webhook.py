# -*- coding: utf-8 -*-
"""
Aplicacion BTZ desde respuesta n8n (webhook). Modulo importado de forma normal;
evita exec_module/importlib sobre script.py completo (podia cerrar Revit).
"""
from __future__ import print_function

import os
import codecs
import clr
import json
import re
import datetime

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    ElementId,
    FamilyInstance,
    FamilySymbol,
    BuiltInParameter,
    Transaction,
    TransactionStatus,
    CategoryType,
    GroupTypeId,
)

from pyrevit import revit, forms
from btz_paths import (
    EXT_DIR,
    RESOURCES_DIR,
    SHARED_PARAMS_FILE,
    PUBLIC_DIR,
    PUBLIC_DEBUG_DIR,
    PUBLIC_OPTIONAL_DIR,
    PUBLIC_LEGACY_DIR,
    PATH_SOURCE,
    ensure_public_layout,
    get_public_file,
)

try:
    unicode
except NameError:
    unicode = str

try:
    long
except NameError:
    long = int

_BTZ_PATH_SOURCE = PATH_SOURCE

# Resolver oficial: core en raiz, paralelos en _legacy/_optional/_debug.
PAYLOAD_GROUPS_JSON_PATH = get_public_file(u"payload_groups.json", u"legacy", fallback=False)
WEBHOOK_RESPONSE_JSON_PATH = get_public_file(u"webhook_response.json", u"legacy", fallback=False)
GROUP_KEY_ELEMENT_IDS_JSON_PATH = get_public_file(
    u"group_key_element_ids.json", u"legacy", fallback=False
)
REFINED_GROUP_KEY_ELEMENT_IDS_JSON_PATH = get_public_file(
    u"refined_group_key_element_ids.json", u"legacy", fallback=False
)
REFINED_GROUPS_MANIFEST_JSON_PATH = get_public_file(
    u"refined_groups_manifest.json", u"legacy", fallback=False
)
GROUPING_PIPELINE_LOG_PATH = get_public_file(
    u"grouping_pipeline.log", u"legacy", fallback=False
)

# --- Respuesta n8n (group_btz_mapping_result) → aplicación en Revit ---
# Mínimo de confianza para escribir un candidate_btz en un slot libre (0.0–1.0).
# 0.75 deja fuera muchas sugerencias; 0.60–0.65 suele aplicar más descripciones (revisar calidad).
AUTO_APPLY_CONFIDENCE = 0.65
# Objetivo operativo:
# - mínimo 3 descripciones por elemento
# - deseable 5 descripciones por elemento
MIN_BTZ_PER_ELEMENT = 3
DESIRED_BTZ_PER_ELEMENT = 5

# Si True: el botón «Exportar grupos» también aplicaría BTZ al terminar (desaconsejado: usá «Ejecutar automático»).
APPLY_WEBHOOK_RESULTS = False

# Obsoleto: usar el botón «Ejecutar automático» en el panel.
APPLY_ONLY_FROM_SAVED_WEBHOOK = False

# Si True: guarda la respuesta cruda del webhook en public/webhook_response.json
SAVE_WEBHOOK_RESPONSE = True

# Opcional: exporta public/apply_results.txt con filas aplicadas
EXPORT_APPLY_RESULTS_TXT = True
# Parámetros BTZ (igual que el resto de herramientas BTZ)
PARAM_BASE = u"BTZ_Description"
PARAM_NUMERIC = [
    u"BTZ_Description_01",
    u"BTZ_Description_02",
    u"BTZ_Description_03",
    u"BTZ_Description_04",
    u"BTZ_Description_05",
    u"BTZ_Description_06",
    u"BTZ_Description_07",
    u"BTZ_Description_08",
    u"BTZ_Description_09",
    u"BTZ_Description_10",
    u"BTZ_Description_11",
    u"BTZ_Description_12",
    u"BTZ_Description_13",
]
ALL_BTZ_PARAMS = [PARAM_BASE] + PARAM_NUMERIC

# Metadatos sugerencia IA (mismo TXT que BTZ_Description; vincular con ensure_btz_shared_parameters)
PARAM_STATUS = u"BTZ_Status"
PARAM_SOURCE = u"BTZ_Source"
PARAM_CONFIDENCE = u"BTZ_Confidence"
ALL_BIND_PARAMS = ALL_BTZ_PARAMS + [PARAM_STATUS, PARAM_SOURCE, PARAM_CONFIDENCE]

# Columnas base del CSV blocks (misma lógica que Sugerir)
CSV_CODE_COL = "code"
CSV_DESC_COL = "description"
CSV_LAST_BASE_COL = "displacement_date"

# Máx. IDs de muestra por grupo en JSON/CSV
MAX_SAMPLE_IDS = 50

# Separador interno para group_key (si un nombre contiene "|", se reemplaza)
GROUP_KEY_SEP = u"|"
def _param_value_as_string(element, param_name):
    p = element.LookupParameter(param_name)
    if p is None or not p.HasValue:
        return u""
    try:
        st = p.AsString()
        if st is not None:
            return unicode(st)
    except Exception:
        pass
    try:
        vs = p.AsValueString()
        return unicode(vs or u"")
    except Exception:
        pass
    return u""
def _ensure_public_dir():
    ensure_public_layout()
def load_payload_from_json_file(path, log_lines):
    """
    Carga el JSON que se enviará a n8n (p. ej. public/payload_groups.json).
    utf-8-sig tolera BOM de Excel/Notepad.
    """
    if not path or not os.path.isfile(path):
        raise IOError(u"No existe el archivo: {0}".format(path))
    with codecs.open(path, u"r", u"utf-8-sig") as fp:
        raw = fp.read()
    log_lines.append(
        u"Cargado {0} ({1} caracteres)".format(path, len(raw))
    )
    try:
        return json.loads(raw)
    except ValueError as e:
        raise ValueError(
            u"JSON inválido en {0}: {1}".format(path, e)
        )


def append_run_log(path, lines):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = u"\n[{0}]\n".format(ts) + u"\n".join(lines) + u"\n"
    with codecs.open(path, u"a", u"utf-8") as fp:
        fp.write(block)
def _unicode_name(obj):
    """Normaliza nombres desde Revit / IronPython (str, unicode, System.String)."""
    if obj is None:
        return u""
    try:
        return unicode(obj).strip()
    except Exception:
        try:
            return unicode(str(obj)).strip()
        except Exception:
            return u""


def _parse_param_names_from_txt(txt_path, log_lines):
    """
    Lee el TXT en disco y lista nombres en líneas PARAM\\t... (sin depender de Revit).
    Sirve para diagnosticar si el archivo en disco coincide con lo que esperamos.
    """
    names = []
    if not txt_path or not os.path.isfile(txt_path):
        return names
    encodings = [
        u"utf-8-sig",
        u"utf-8",
        u"utf-16",
        u"utf-16-le",
        u"utf-16-be",
        u"cp1252",
        u"latin1",
    ]
    used_enc = None
    for enc in encodings:
        try:
            with codecs.open(txt_path, u"r", enc) as fp:
                for line in fp:
                    line = line.strip(u"\r\n")
                    if not line.startswith(u"PARAM") and not line.startswith("PARAM"):
                        continue
                    parts = line.split(u"\t")
                    if len(parts) >= 3:
                        pname = _unicode_name(parts[2])
                        if pname:
                            names.append(pname)
            used_enc = enc
            break
        except Exception as ex:
            if log_lines is not None:
                log_lines.append(
                    u"parse TXT encoding {0} falló: {1}".format(enc, ex)
                )
            continue
    if log_lines is not None and used_enc:
        log_lines.append(u"Parse TXT: encoding usado = {0}".format(used_enc))
    return names


def _get_definition_map(def_file):
    """
    Mapa nombre → Definition. Claves siempre unicode para coincidir con ALL_BIND_PARAMS.
    """
    defs = {}
    for group in def_file.Groups:
        for definition in group.Definitions:
            key = _unicode_name(definition.Name)
            if key:
                defs[key] = definition
    return defs


def _build_model_category_set(doc):
    catset = doc.Application.Create.NewCategorySet()
    count = 0
    for cat in doc.Settings.Categories:
        try:
            if cat is None or not cat.AllowsBoundParameters or cat.IsTagCategory:
                continue
            if cat.CategoryType != CategoryType.Model:
                continue
            catset.Insert(cat)
            count += 1
        except Exception:
            pass
    if count == 0:
        raise ValueError(u"No se pudo armar CategorySet de categorías de modelo.")
    return catset


def _get_existing_binding_names(doc):
    names = set()
    it = doc.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        try:
            definition = it.Key
            if definition and definition.Name:
                names.add(_unicode_name(definition.Name))
        except Exception:
            pass
    return names


def log_shared_params_diagnostics(log_lines):
    """Registra ruta efectiva del TXT y existencia (antes de abrir en Revit)."""
    log_lines.append(u"--- Diagnóstico SHARED_PARAMS_FILE ---")
    log_lines.append(u"Ruta efectiva (absoluta): {0}".format(SHARED_PARAMS_FILE))
    log_lines.append(u"¿Existe el archivo?: {0}".format(os.path.isfile(SHARED_PARAMS_FILE)))
    if os.path.isfile(SHARED_PARAMS_FILE):
        try:
            sz = os.path.getsize(SHARED_PARAMS_FILE)
            log_lines.append(u"Tamaño en disco: {0} bytes".format(sz))
        except Exception:
            pass
    log_lines.append(u"Cómo se resolvió la ruta: {0}".format(_BTZ_PATH_SOURCE or u"(sin dato)"))
    names_in_txt = _parse_param_names_from_txt(SHARED_PARAMS_FILE, log_lines)
    log_lines.append(
        u"Parámetros encontrados en el TXT (líneas PARAM): {0}".format(len(names_in_txt))
    )
    if names_in_txt:
        log_lines.append(u"Lista (TXT): {0}".format(u", ".join(names_in_txt)))

    req = [_unicode_name(x) for x in ALL_BIND_PARAMS]
    txt_set = set(names_in_txt)
    req_set = set(req)
    missing_in_txt_parse = sorted(req_set - txt_set)
    extra_in_txt = sorted(txt_set - req_set)
    if missing_in_txt_parse:
        log_lines.append(
            u"Respecto al script, faltan en el TXT (parse): {0}".format(
                u", ".join(missing_in_txt_parse)
            )
        )
    else:
        log_lines.append(
            u"Parse del TXT: cubre los {0} parámetros requeridos.".format(len(req_set))
        )
    if extra_in_txt:
        log_lines.append(
            u"Parámetros extra en el TXT (no usados por este script): {0}".format(
                u", ".join(extra_in_txt)
            )
        )
    log_lines.append(u"--- Fin diagnóstico SHARED_PARAMS_FILE ---")


def ensure_btz_shared_parameters(doc, log_lines):
    """Vincula shared parameters BTZ (incl. BTZ_Status, BTZ_Source, BTZ_Confidence)."""
    existing_names = _get_existing_binding_names(doc)
    req_names = set(_unicode_name(x) for x in ALL_BIND_PARAMS)
    if req_names.issubset(existing_names):
        log_lines.append(
            u"Shared parameters BTZ ya estaban vinculados; se omite la transacción de vinculación."
        )
        return

    log_shared_params_diagnostics(log_lines)

    if not SHARED_PARAMS_FILE or not os.path.isfile(SHARED_PARAMS_FILE):
        raise IOError(
            u"No se encontró el archivo de shared parameters:\n{0}".format(
                SHARED_PARAMS_FILE
            )
        )

    app = doc.Application
    app.SharedParametersFilename = SHARED_PARAMS_FILE
    def_file = app.OpenSharedParameterFile()
    if def_file is None:
        raise IOError(
            u"Revit no pudo abrir/parsear el shared parameter file.\n"
            u"Comprobá formato TAB, encoding UTF-8 y que el archivo no esté corrupto:\n{0}".format(
                SHARED_PARAMS_FILE
            )
        )

    definition_map = _get_definition_map(def_file)
    names_revit = sorted(definition_map.keys())
    log_lines.append(
        u"Parámetros cargados por Revit (Definition.Name): {0}".format(len(names_revit))
    )
    if names_revit:
        log_lines.append(u"Lista (Revit): {0}".format(u", ".join(names_revit)))

    missing = []
    for n in ALL_BIND_PARAMS:
        nu = _unicode_name(n)
        if nu not in definition_map:
            missing.append(nu)

    if missing:
        log_lines.append(
            u"Parámetros requeridos por el script que NO están en el mapa de Revit: {0}".format(
                u", ".join(missing)
            )
        )
        raise ValueError(
            u"Faltan parámetros en el shared parameter file (según Revit): {0}".format(
                u", ".join(missing)
            )
        )

    catset = _build_model_category_set(doc)
    creator = doc.Application.Create
    existing_names = _get_existing_binding_names(doc)

    tx = Transaction(doc, u"BTZ | Vincular shared parameters (Exportar grupos)")
    tx.Start()
    try:
        for name in ALL_BIND_PARAMS:
            nu = _unicode_name(name)
            definition = definition_map[nu]
            binding = creator.NewInstanceBinding(catset)
            if nu in existing_names:
                doc.ParameterBindings.ReInsert(
                    definition, binding, GroupTypeId.Text
                )
            else:
                ok = doc.ParameterBindings.Insert(
                    definition, binding, GroupTypeId.Text
                )
                if not ok:
                    doc.ParameterBindings.ReInsert(
                        definition, binding, GroupTypeId.Text
                    )
        tx.Commit()
    except Exception:
        try:
            if tx.GetStatus() == TransactionStatus.Started:
                tx.RollBack()
        except Exception:
            pass
        raise

    log_lines.append(
        u"Shared parameters BTZ vinculados correctamente ({0} definiciones).".format(
            len(ALL_BIND_PARAMS)
        )
    )


# =============================================================================
# Mapa group_key → elementos (misma clave que build_group_key / export)
# =============================================================================


def map_group_key_to_elements(element_rows):
    """
    Devuelve dict group_key → lista de element_id (int) para todos los elementos exportados.
    Debe coincidir con la lógica de group_key usada en collect_revit_elements.
    """
    m = {}
    for r in element_rows:
        gk = r[u"group_key"]
        eid = r[u"element_id"]
        m.setdefault(gk, []).append(eid)
    return m
def load_group_key_element_ids_from_json(path, log_lines):
    with codecs.open(path, u"r", u"utf-8-sig") as fp:
        raw = fp.read()
    data = json.loads(raw)
    out = {}
    for k, v in data.items():
        out[unicode(k)] = [int(x) for x in v]
    log_lines.append(u"Cargado mapa group_key desde {0}".format(path))
    return out


def load_refined_groups_manifest(path, log_lines):
    """Manifest opcional (export con enriquecimiento)."""
    if not path or not os.path.isfile(path):
        if log_lines is not None:
            log_lines.append(u"Manifest refinado: no encontrado (solo claves base en n8n).")
        return {}
    with codecs.open(path, u"r", u"utf-8-sig") as fp:
        data = json.loads(fp.read())
    out = {}
    for k, v in data.items():
        if isinstance(v, dict):
            out[unicode(k)] = v
    log_lines.append(u"Cargado manifest refinado: {0} entradas".format(len(out)))
    return out


def build_apply_group_key_map(base_map, refined_path, _manifest_path, log_lines):
    """Mezcla mapa base (group_key) con refined_group_key, sin eliminar base."""
    merged = dict(base_map)
    if not refined_path or not os.path.isfile(refined_path):
        return merged
    with codecs.open(refined_path, u"r", u"utf-8-sig") as fp:
        refined_map = json.loads(fp.read())
    refined_map = {unicode(k): [int(x) for x in v] for k, v in refined_map.items()}

    for rk, ids in refined_map.items():
        merged[rk] = ids

    log_lines.append(
        u"Mapa apply: {0} claves (base + refined coexistentes).".format(len(merged))
    )
    return merged


def _top_matched_code_from_mapping(mapping):
    cands = mapping.get(u"candidate_btz") or mapping.get("candidate_btz") or []
    if not isinstance(cands, list) or not cands:
        return u""
    c0 = cands[0]
    if not isinstance(c0, dict):
        return u""
    return unicode(
        c0.get(u"matched_code") or c0.get("matched_code") or u""
    ).strip()


def resolve_btz_status_and_source(mapping, manifest_entry):
    """
    BTZ_Status: AUTO / REVIEW / SPLIT_AUTO según n8n + manifest (preflight).
    BTZ_Source: BLOCKS+LLM si coincide código dominante blocks con top n8n; si no, LLM_ONLY.
    """
    nr_n8n = bool(mapping.get(u"needs_review") or mapping.get("needs_review"))
    nr_man = bool(manifest_entry.get(u"needs_review")) if manifest_entry else False
    top_code = _top_matched_code_from_mapping(mapping)
    dom = u""
    if manifest_entry:
        dom = unicode(manifest_entry.get(u"dominant_code") or u"").strip()

    if nr_n8n or nr_man:
        st = u"REVIEW"
    else:
        st = u"AUTO"
        if manifest_entry and manifest_entry.get(u"group_origin") == u"split":
            mh = unicode(manifest_entry.get(u"btz_status_hint") or u"").upper()
            if mh == u"SPLIT_AUTO":
                st = u"SPLIT_AUTO"
            elif mh == u"REVIEW":
                st = u"REVIEW"
        elif manifest_entry:
            mh = unicode(manifest_entry.get(u"btz_status_hint") or u"").upper()
            if mh == u"REVIEW":
                st = u"REVIEW"

    if dom and top_code and dom == top_code:
        src = u"BLOCKS+LLM"
    elif dom and top_code:
        src = u"LLM_ONLY"
    elif top_code and not dom:
        src = u"LLM_ONLY"
    elif dom and not top_code:
        src = u"BLOCKS_ONLY"
    else:
        src = u"LLM_ONLY"

    return st, src


def _repair_duplicate_reason_confidence_in_json(s):
    """
    Repara JSON roto por el LLM: repite confidence+reason con el mismo texto que reason previo.
    Se aplica en bucle por si hay más de un bloque defectuoso.
    """
    pat = r'("reason"\s*:\s*"((?:[^"\\]|\\.)*)")\s*,\s*\n\s*"confidence"\s*:\s*[^,]+,\s*\n\s*"reason"\s*:\s*"\2"'
    prev = None
    while prev != s:
        prev = s
        s = re.sub(pat, r"\1\n        }", s)
    return s


def _parse_json_from_raw_output(raw, log_lines):
    """
    Parsea el string en raw_output (n8n). Si el JSON es inválido, intenta reparación heurística.
    """
    raw_str = unicode(raw).strip()
    if not raw_str:
        return None
    try:
        return json.loads(raw_str)
    except Exception as ex:
        if log_lines is not None:
            log_lines.append(u"raw_output: JSON inválido ({0}); intentando reparar…".format(ex))
    try:
        repaired = _repair_duplicate_reason_confidence_in_json(raw_str)
        return json.loads(repaired)
    except Exception as ex2:
        if log_lines is not None:
            log_lines.append(u"raw_output: sigue sin parsear: {0}".format(ex2))
        return None


def normalize_webhook_response(parsed, log_lines=None):
    """
    - Lista raíz [ {...} ]: primer dict o merge de group_mappings.
    - n8n a veces devuelve group_mappings vacío y el JSON real en raw_output (string).
    """
    if isinstance(parsed, list):
        if not parsed:
            raise ValueError(u"Respuesta JSON: lista vacía en la raíz")
        merged = None
        for item in parsed:
            if not isinstance(item, dict):
                continue
            if merged is None:
                merged = dict(item)
            else:
                gm_a = merged.get(u"group_mappings")
                if gm_a is None:
                    gm_a = merged.get("group_mappings")
                if gm_a is None:
                    gm_a = []
                gm_b = item.get(u"group_mappings")
                if gm_b is None:
                    gm_b = item.get("group_mappings")
                if gm_b is None:
                    gm_b = []
                if isinstance(gm_a, list) and isinstance(gm_b, list):
                    merged[u"group_mappings"] = gm_a + gm_b
        if merged is None:
            raise ValueError(u"Respuesta JSON: lista sin objetos válidos")
        parsed = merged

    if not isinstance(parsed, dict):
        raise ValueError(u"Respuesta no es un objeto JSON")

    gm = parsed.get(u"group_mappings")
    if gm is None:
        gm = parsed.get("group_mappings")
    if gm is None:
        gm = []
    if not isinstance(gm, list):
        gm = []

    if len(gm) == 0:
        raw = parsed.get(u"raw_output")
        if raw is None:
            raw = parsed.get("raw_output")
        if raw:
            inner = _parse_json_from_raw_output(raw, log_lines)
            if isinstance(inner, list):
                inner = inner[0] if (len(inner) and isinstance(inner[0], dict)) else None
            if isinstance(inner, dict):
                gm2 = inner.get(u"group_mappings")
                if gm2 is None:
                    gm2 = inner.get("group_mappings")
                if isinstance(gm2, list) and len(gm2) > 0:
                    if log_lines is not None:
                        log_lines.append(
                            u"Respuesta n8n: group_mappings vacío en raíz; se usó raw_output ({0} grupos).".format(
                                len(gm2)
                            )
                        )
                    out = {
                        u"mode": inner.get(u"mode")
                        or inner.get("mode")
                        or u"group_btz_mapping_result",
                        u"group_mappings": gm2,
                    }
                    pn = inner.get(u"project_name")
                    if pn is None:
                        pn = inner.get("project_name")
                    if pn is not None:
                        out[u"project_name"] = pn
                    return out

    return parsed


def load_group_mapping_response(parsed, log_lines=None):
    """
    Valida JSON de n8n con mode=group_btz_mapping_result y devuelve group_mappings.
    """
    parsed = normalize_webhook_response(parsed, log_lines)

    if not isinstance(parsed, dict):
        raise ValueError(u"Respuesta no es un objeto JSON")

    mode = parsed.get(u"mode") or parsed.get("mode")
    if mode not in (u"group_btz_mapping_result", "group_btz_mapping_result"):
        raise ValueError(
            u"mode inesperado (esperado group_btz_mapping_result): {0}".format(mode)
        )

    gm = parsed.get(u"group_mappings")
    if gm is None:
        gm = parsed.get("group_mappings")
    if gm is None:
        raise ValueError(u"Falta group_mappings en la respuesta")
    if not isinstance(gm, list):
        raise ValueError(u"group_mappings debe ser una lista")

    return gm


def _build_group_mappings_from_local_payload(payload_path, log_lines=None):
    """
    Fallback local: construye group_mappings desde payload_groups.json cuando n8n
    devuelve group_mappings vacío o inválido.
    """
    if not payload_path or (not os.path.isfile(payload_path)):
        return []

    try:
        payload = load_payload_from_json_file(payload_path, log_lines)
    except Exception as ex:
        if log_lines is not None:
            log_lines.append(
                u"Fallback local: no se pudo leer payload_groups.json: {0}".format(ex)
            )
        return []

    groups = payload.get(u"revit_groups")
    if not isinstance(groups, list) or not groups:
        groups = payload.get("revit_groups")
    if not isinstance(groups, list) or not groups:
        groups = payload.get(u"enriched_revit_groups")
    if not isinstance(groups, list) or not groups:
        groups = payload.get("enriched_revit_groups")
    if not isinstance(groups, list):
        groups = []

    out = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        gk = g.get(u"group_key") or g.get("group_key")
        if not gk:
            gk = g.get(u"refined_group_key") or g.get("refined_group_key")
        if not gk:
            gk = g.get(u"base_group_key") or g.get("base_group_key")
        if not gk:
            continue

        cands = g.get(u"candidate_btz")
        if cands is None:
            cands = g.get("candidate_btz")
        if not isinstance(cands, list):
            cands = []
        if not cands:
            cands = _fallback_candidates_from_mapping(g)

        out.append({
            u"group_key": unicode(gk),
            u"candidate_btz": cands,
            u"dominant_candidate": g.get(u"dominant_candidate")
            if g.get(u"dominant_candidate") is not None
            else g.get("dominant_candidate"),
            u"blocks_supporting_rows": g.get(u"blocks_supporting_rows")
            if g.get(u"blocks_supporting_rows") is not None
            else g.get("blocks_supporting_rows"),
        })

    if log_lines is not None:
        log_lines.append(
            u"Fallback local aplicado: {0} group_mappings desde payload_groups.json".format(
                len(out)
            )
        )
    return out
def _norm_key_btz(s):
    return (s or u"").strip().lower()


def _format_display_value_from_candidate(c):
    disp = c.get(u"display_value")
    if disp is None:
        disp = c.get("display_value")
    if disp is not None and unicode(disp).strip():
        return unicode(disp).strip()
    code = unicode(
        c.get(u"matched_code") or c.get("matched_code") or u""
    ).strip()
    val = unicode(
        c.get(u"suggested_value") or c.get("suggested_value") or u""
    ).strip()
    if code and val:
        return u"{0} - {1}".format(code, val)
    return val or code


def get_free_btz_slots(element):
    """BTZ_Description_01…13 vacíos, en orden."""
    empty = []
    for pname in PARAM_NUMERIC:
        val = _param_value_as_string(element, pname)
        if not (val or u"").strip():
            empty.append(pname)
    return empty


def count_existing_btz_slots(element):
    """Cantidad de slots BTZ_Description_01..13 actualmente ocupados."""
    used = 0
    for pname in PARAM_NUMERIC:
        val = _param_value_as_string(element, pname)
        if (val or u"").strip():
            used += 1
    return used


def get_existing_btz_values(element):
    """Valores no vacíos en BTZ_Description y _01…13 (para detectar duplicados)."""
    vals = set()
    for pname in ALL_BTZ_PARAMS:
        raw = _param_value_as_string(element, pname)
        s = (raw or u"").strip()
        if s:
            vals.add(_norm_key_btz(s))
    return vals


def choose_btz_candidates_for_element(element, candidate_btz_list, min_items=MIN_BTZ_PER_ELEMENT):
    """
    Filtra candidate_btz y prioriza conf >= umbral.
    Si no alcanza min_items, completa con candidatos de menor confianza.
    """
    existing = get_existing_btz_values(element)
    high = []
    low = []
    for c in candidate_btz_list:
        if not isinstance(c, dict):
            continue
        alr = c.get(u"already_present", c.get("already_present", False))
        if alr:
            continue
        try:
            conf = float(c.get(u"confidence", c.get("confidence", 0)))
        except Exception:
            conf = 0.0
        disp = _format_display_value_from_candidate(c)
        if not disp:
            continue
        nk = _norm_key_btz(disp)
        if nk in existing:
            continue
        rec = (conf, c, disp, nk)
        if conf >= AUTO_APPLY_CONFIDENCE:
            high.append(rec)
        else:
            low.append(rec)

    high.sort(key=lambda x: -x[0])
    low.sort(key=lambda x: -x[0])
    picked = list(high)
    if len(picked) < int(min_items):
        picked.extend(low)
    out = []
    seen_disp = set()
    for conf, c, disp, nk in picked:
        if nk in seen_disp:
            continue
        seen_disp.add(nk)
        out.append({u"c": c, u"disp": disp, u"conf": conf, u"nk": nk})
    return out


def set_text_parameter(element, param_name, value):
    param = element.LookupParameter(param_name)
    if param is None:
        return False, u"sin parámetro: {0}".format(param_name)
    if param.IsReadOnly:
        return False, u"solo lectura: {0}".format(param_name)
    try:
        param.Set(value)
        return True, None
    except Exception as ex:
        return False, unicode(ex)


def _compute_slot_assignments(element, ordered_candidates, target_writes=None):
    """
    ordered_candidates: salida de choose_btz_candidates_for_element (lista de dicts con disp, conf).
    Asigna a los primeros slots libres sin pisar ocupados.
    """
    free_slots = get_free_btz_slots(element)
    assignments = []
    max_conf = 0.0
    limit = None
    try:
        limit = int(target_writes) if target_writes is not None else None
    except Exception:
        limit = None

    for item in ordered_candidates:
        if not free_slots:
            break
        if limit is not None and len(assignments) >= max(0, limit):
            break
        disp = item[u"disp"]
        conf = item[u"conf"]
        slot = free_slots.pop(0)
        assignments.append((slot, disp, conf))
        if conf > max_conf:
            max_conf = conf
    return assignments, max_conf


def _fallback_candidates_from_mapping(mapping):
    """Si n8n no devuelve candidate_btz, intenta construir mínimos desde otros campos."""
    out = []
    dom = mapping.get(u"dominant_candidate") or mapping.get("dominant_candidate")
    if isinstance(dom, dict):
        out.append({
            u"matched_code": dom.get(u"matched_code") or dom.get("matched_code") or u"",
            u"suggested_value": dom.get(u"suggested_value") or dom.get("suggested_value") or u"",
            u"display_value": dom.get(u"display_value") or dom.get("display_value") or u"",
            u"confidence": float(dom.get(u"confidence", dom.get("confidence", 0.45)) or 0.45),
        })
    rows = mapping.get(u"blocks_supporting_rows") or mapping.get("blocks_supporting_rows") or []
    if isinstance(rows, list):
        for r in rows[:5]:
            if not isinstance(r, dict):
                continue
            code = unicode(r.get(u"code") or r.get("code") or u"").strip()
            desc = unicode(r.get(u"description") or r.get("description") or u"").strip()
            if not (code or desc):
                continue
            out.append({
                u"matched_code": code,
                u"suggested_value": desc,
                u"display_value": u"{0} - {1}".format(code, desc).strip(u" -"),
                u"confidence": 0.35,
            })
    return out


def _element_id_from_export_id(eid):
    """Evita fallos nativos con tipos raros; Revit 2024+ usa ids largos."""
    try:
        i = int(eid)
    except Exception:
        return None
    try:
        return ElementId(i)
    except Exception:
        try:
            return ElementId(long(i))
        except Exception:
            return None


def _safe_transaction_rollback(tx):
    try:
        if tx is not None and tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
    except Exception:
        pass


def apply_group_mapping_to_elements(
    doc, mapping, group_key_to_ids, log_lines, apply_rows, manifest_by_key=None
):
    """
    Aplica un item de group_mappings a todos los element_id de ese group_key.
    """
    local = {
        u"elements_updated": 0,
        u"elements_skipped": 0,
        u"btz_written": 0,
        u"errors": [],
        u"group_applied": False,
        u"skip_not_found": 0,
        u"skip_low_confidence": 0,
        u"skip_no_free_slot": 0,
        u"skip_no_n8n_candidates": 0,
    }

    gk = mapping.get(u"group_key") or mapping.get("group_key")
    if gk is None:
        local[u"errors"].append(u"Mapping sin group_key")
        return local
    gk = unicode(gk)

    m_entry = (manifest_by_key or {}).get(gk) if manifest_by_key else None

    cands = mapping.get(u"candidate_btz") or mapping.get("candidate_btz") or []
    if (not isinstance(cands, list) or not cands):
        cands = _fallback_candidates_from_mapping(mapping)
    ids = group_key_to_ids.get(gk)
    if not ids:
        local[u"errors"].append(
            u"group_key sin elementos en export actual: {0}".format(gk[:120])
        )
        return local

    if not isinstance(cands, list) or not cands:
        n = len(ids)
        local[u"skip_no_n8n_candidates"] = n
        local[u"elements_skipped"] = n
        return local

    for eid in ids:
        eid_obj = _element_id_from_export_id(eid)
        if eid_obj is None:
            local[u"errors"].append(u"Id inválido: {0}".format(eid))
            continue

        el = doc.GetElement(eid_obj)
        if el is None:
            local[u"errors"].append(u"Elemento no encontrado: {0}".format(eid))
            local[u"elements_skipped"] += 1
            local[u"skip_not_found"] += 1
            continue

        current_used = count_existing_btz_slots(el)
        required = max(0, MIN_BTZ_PER_ELEMENT - current_used)
        desired_to_write = max(0, DESIRED_BTZ_PER_ELEMENT - current_used)

        ordered_raw = choose_btz_candidates_for_element(
            el, cands, min_items=required
        )
        if not ordered_raw:
            local[u"elements_skipped"] += 1
            local[u"skip_low_confidence"] += 1
            continue

        assignments, max_conf = _compute_slot_assignments(
            el, ordered_raw, target_writes=desired_to_write
        )
        if not assignments:
            local[u"elements_skipped"] += 1
            local[u"skip_no_free_slot"] += 1
            continue

        tx = Transaction(doc, u"BTZ | Auto grupo n8n")
        try:
            tx.Start()
        except Exception as ex:
            local[u"errors"].append(u"Id {0}: no se pudo iniciar transacción: {1}".format(eid, unicode(ex)))
            continue

        err_tx = None
        try:
            for slot, disp, _cconf in assignments:
                ok, err = set_text_parameter(el, slot, disp)
                if not ok:
                    err_tx = err
                    break

            if err_tx:
                _safe_transaction_rollback(tx)
                local[u"errors"].append(
                    u"Id {0}: {1}".format(eid, err_tx)
                )
                continue

            ok, err = set_text_parameter(el, PARAM_BASE, u"*")
            if not ok:
                _safe_transaction_rollback(tx)
                local[u"errors"].append(u"Id {0} *: {1}".format(eid, err))
                continue
            st_val, src_val = resolve_btz_status_and_source(mapping, m_entry)
            ok, err = set_text_parameter(el, PARAM_STATUS, st_val)
            if not ok:
                _safe_transaction_rollback(tx)
                local[u"errors"].append(u"Id {0} Status: {1}".format(eid, err))
                continue
            ok, err = set_text_parameter(el, PARAM_SOURCE, src_val)
            if not ok:
                _safe_transaction_rollback(tx)
                local[u"errors"].append(u"Id {0} Source: {1}".format(eid, err))
                continue
            conf_str = u"{0:.4f}".format(max_conf)
            ok, err = set_text_parameter(el, PARAM_CONFIDENCE, conf_str)
            if not ok:
                _safe_transaction_rollback(tx)
                local[u"errors"].append(u"Id {0} Confidence: {1}".format(eid, err))
                continue

            tx.Commit()
        except Exception as ex:
            _safe_transaction_rollback(tx)
            local[u"errors"].append(u"Id {0}: {1}".format(eid, unicode(ex)))
            continue

        local[u"elements_updated"] += 1
        local[u"btz_written"] += len(assignments)
        local[u"group_applied"] = True
        apply_rows.append({
            u"group_key": gk,
            u"element_id": eid,
            u"slots": len(assignments),
            u"max_confidence": max_conf,
        })

    return local


def apply_all_group_mappings(doc, group_mappings, group_key_to_ids, log_lines, manifest_by_key=None):
    """
    Recorre group_mappings; no corta la corrida ante error en un grupo/elemento.
    """
    stats = {
        u"groups_received": len(group_mappings),
        u"groups_with_candidates": 0,
        u"groups_applied": 0,
        u"elements_updated": 0,
        u"elements_skipped": 0,
        u"btz_slots_written": 0,
        u"errors": [],
        u"skip_not_found": 0,
        u"skip_low_confidence": 0,
        u"skip_no_free_slot": 0,
        u"skip_no_n8n_candidates": 0,
    }
    apply_rows = []

    for mapping in group_mappings:
        if not isinstance(mapping, dict):
            continue
        cands = mapping.get(u"candidate_btz") or mapping.get("candidate_btz") or []
        if isinstance(cands, list) and len(cands) > 0:
            stats[u"groups_with_candidates"] += 1

        loc = apply_group_mapping_to_elements(
            doc, mapping, group_key_to_ids, log_lines, apply_rows, manifest_by_key
        )
        stats[u"elements_updated"] += loc[u"elements_updated"]
        stats[u"elements_skipped"] += loc[u"elements_skipped"]
        stats[u"btz_slots_written"] += loc[u"btz_written"]
        stats[u"errors"].extend(loc[u"errors"])
        stats[u"skip_not_found"] += loc.get(u"skip_not_found", 0)
        stats[u"skip_low_confidence"] += loc.get(u"skip_low_confidence", 0)
        stats[u"skip_no_free_slot"] += loc.get(u"skip_no_free_slot", 0)
        stats[u"skip_no_n8n_candidates"] += loc.get(u"skip_no_n8n_candidates", 0)
        if loc[u"group_applied"]:
            stats[u"groups_applied"] += 1

    return stats, apply_rows


def export_apply_results_txt(path, apply_rows, log_lines):
    lines = [
        u"element_id\tgroup_key\tslots\tmax_confidence",
    ]
    for r in apply_rows:
        lines.append(
            u"{0}\t{1}\t{2}\t{3}".format(
                r[u"element_id"],
                r[u"group_key"].replace(u"\t", u" "),
                r[u"slots"],
                r[u"max_confidence"],
            )
        )
    with codecs.open(path, u"w", u"utf-8-sig") as fp:
        fp.write(u"\n".join(lines) + u"\n")
    log_lines.append(u"Guardado: {0}".format(path))


def show_apply_summary(stats, log_lines):
    msg = (
        u"--- Aplicación BTZ (n8n por grupo) ---\n"
        u"Umbral confianza mínima (AUTO_APPLY_CONFIDENCE): {conf}\n"
        u"Grupos recibidos: {groups_received}\n"
        u"Grupos con candidate_btz: {groups_with_candidates}\n"
        u"Grupos con al menos un elemento actualizado: {groups_applied}\n"
        u"Elementos actualizados: {elements_updated}\n"
        u"Elementos sin escribir BTZ: {elements_skipped}\n"
        u"  · sin candidato que supere el umbral / ya duplicado: {sk_lc}\n"
        u"  · sin slots libres (01–13 llenos): {sk_sl}\n"
        u"  · elemento no encontrado en el modelo: {sk_nf}\n"
        u"  · grupo sin candidate_btz en JSON n8n: {sk_nc}\n"
        u"Slots BTZ escritos (01–13): {btz_slots_written}\n"
        u"Errores (lista): {err_count}"
    ).format(
        conf=AUTO_APPLY_CONFIDENCE,
        groups_received=stats[u"groups_received"],
        groups_with_candidates=stats[u"groups_with_candidates"],
        groups_applied=stats[u"groups_applied"],
        elements_updated=stats[u"elements_updated"],
        elements_skipped=stats[u"elements_skipped"],
        sk_lc=stats.get(u"skip_low_confidence", 0),
        sk_sl=stats.get(u"skip_no_free_slot", 0),
        sk_nf=stats.get(u"skip_not_found", 0),
        sk_nc=stats.get(u"skip_no_n8n_candidates", 0),
        btz_slots_written=stats[u"btz_slots_written"],
        err_count=len(stats[u"errors"]),
    )
    if stats[u"errors"]:
        msg += u"\n\n" + u"\n".join(stats[u"errors"][:40])
        if len(stats[u"errors"]) > 40:
            msg += u"\n… ({0} más)".format(len(stats[u"errors"]) - 40)

    log_lines.append(msg)
    print(msg)
    forms.alert(msg, title=u"BTZ — aplicación automática", warn_icon=bool(stats[u"errors"]))


def try_apply_webhook_response(doc, parsed, element_rows, log_lines, force_apply=False):
    """
    Vincula shared params, valida group_btz_mapping_result, aplica por grupo.
    element_rows: si None, se usa group_key_element_ids.json (mismo export).
    force_apply: si True, aplica aunque APPLY_WEBHOOK_RESULTS sea False (botón «Ejecutar automático»).
    """
    if not force_apply and not APPLY_WEBHOOK_RESULTS:
        return
    if parsed is None:
        log_lines.append(u"APPLY_WEBHOOK_RESULTS: sin respuesta JSON.")
        return

    try:
        ensure_btz_shared_parameters(doc, log_lines)
        gms = load_group_mapping_response(parsed, log_lines)
        if not gms:
            gms = _build_group_mappings_from_local_payload(
                PAYLOAD_GROUPS_JSON_PATH, log_lines
            )
            if gms:
                log_lines.append(
                    u"Aplicación: n8n devolvió 0 grupos; se usó fallback local desde payload_groups.json."
                )
    except Exception as ex:
        log_lines.append(u"Validación / shared params: {0}".format(ex))
        forms.alert(
            u"No se pudo preparar la aplicación:\n{0}".format(ex),
            title=u"BTZ — aplicación",
            warn_icon=True,
        )
        return

    if element_rows is not None:
        base_map = map_group_key_to_elements(element_rows)
    else:
        if not os.path.isfile(GROUP_KEY_ELEMENT_IDS_JSON_PATH):
            forms.alert(
                u"Falta el mapa de grupos:\n{0}\n\n"
                u"Ejecutá export completo (SEND_PAYLOAD_FILE_ONLY=False) antes.".format(
                    GROUP_KEY_ELEMENT_IDS_JSON_PATH
                ),
                title=u"BTZ — aplicación",
                warn_icon=True,
            )
            return
        base_map = load_group_key_element_ids_from_json(
            GROUP_KEY_ELEMENT_IDS_JSON_PATH, log_lines
        )

    gk_map = build_apply_group_key_map(
        base_map,
        REFINED_GROUP_KEY_ELEMENT_IDS_JSON_PATH,
        REFINED_GROUPS_MANIFEST_JSON_PATH,
        log_lines,
    )
    manifest = load_refined_groups_manifest(REFINED_GROUPS_MANIFEST_JSON_PATH, log_lines)

    stats, apply_rows = apply_all_group_mappings(doc, gms, gk_map, log_lines, manifest_by_key=manifest)
    path_apply = get_public_file(u"apply_results.txt", u"legacy", fallback=False)
    if EXPORT_APPLY_RESULTS_TXT:
        export_apply_results_txt(path_apply, apply_rows, log_lines)
    show_apply_summary(stats, log_lines)


def main_apply_saved_webhook_only():
    """
    Solo aplica candidatos BTZ desde public/webhook_response.json.
    No recorre el modelo ni hace POST al webhook.
    (Invocado desde el botón «Ejecutar automático».)
    """
    log_lines = []
    log_lines.append(u"Modo: aplicar solo desde public/webhook_response.json")
    log_lines.append(u"PUBLIC_DIR={0}".format(PUBLIC_DIR))

    doc = revit.doc
    path_log = get_public_file(u"run_log.txt", u"debug", fallback=False)
    path_webhook_resp = WEBHOOK_RESPONSE_JSON_PATH

    try:
        _ensure_public_dir()
    except Exception as ex:
        forms.alert(
            u"No se pudo acceder a public/: {0}".format(ex),
            title=u"Ejecutar automático",
            warn_icon=True,
        )
        return

    if not os.path.isfile(path_webhook_resp):
        forms.alert(
            u"No hay respuesta guardada:\n{0}\n\n"
            u"Ejecutá antes «Exportar grupos» (envío a n8n) o pegá ahí el JSON de la respuesta.".format(
                path_webhook_resp
            ),
            title=u"Ejecutar automático",
            warn_icon=True,
        )
        return

    try:
        parsed = load_payload_from_json_file(path_webhook_resp, log_lines)
        try_apply_webhook_response(doc, parsed, None, log_lines, force_apply=True)
        log_lines.append(u"Fin OK")
    except Exception as ex:
        log_lines.append(u"ERROR: {0}".format(ex))
        append_run_log(path_log, log_lines)
        forms.alert(
            u"{0}\n\nDetalle en run_log.txt".format(ex),
            title=u"Ejecutar automático",
            warn_icon=True,
        )
        print(u"\n".join(log_lines))
        return

    append_run_log(path_log, log_lines)
    print(u"\n".join(log_lines))
