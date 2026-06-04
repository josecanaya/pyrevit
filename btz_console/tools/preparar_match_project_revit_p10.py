# -*- coding: utf-8 -*-
"""
Cruce diagnóstico Project/Revit para Planta 10.000.

No usa Revit API y no escribe nada en Revit. Lee:
- public/modelo_btz_export_p10.csv
- public/project_planta_10000.xlm (CSV/delimitado, aunque tenga extensión .xlm)

Genera:
- public/match_project_revit_preparacion.csv
- public/match_project_revit_preparacion_summary.txt
"""
from __future__ import print_function

import argparse
import codecs
import csv
import io
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict, defaultdict


EXT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), u"..", u".."))
PUBLIC_DIR = os.path.join(EXT_DIR, u"public")

DEFAULT_REVIT_CSV = os.path.join(PUBLIC_DIR, u"modelo_btz_export_p10.csv")
DEFAULT_PROJECT_FILE = os.path.join(PUBLIC_DIR, u"PROJECT_PLANTA_10000_SOLO_CODIGOS_MS_PROJECT.xml")
DEFAULT_OUT_CSV = os.path.join(PUBLIC_DIR, u"match_project_revit_preparacion.csv")
DEFAULT_OUT_SUMMARY = os.path.join(PUBLIC_DIR, u"match_project_revit_preparacion_summary.txt")
DEFAULT_CONTAINERS_CSV = os.path.join(PUBLIC_DIR, u"contenedores_revit_p10.csv")
DEFAULT_CONFIRMADO_AUTO_CSV = os.path.join(PUBLIC_DIR, u"match_project_revit_confirmado_auto.csv")
DEFAULT_REVISION_CSV = os.path.join(PUBLIC_DIR, u"match_project_revit_revision.csv")
DEFAULT_CONTAINER_CHILDREN_CSV = os.path.join(PUBLIC_DIR, u"asociacion_contenedor_hijos_p10.csv")
DEFAULT_APPLY_READY_CSV = os.path.join(PUBLIC_DIR, u"match_project_revit_confirmado_para_aplicar.csv")
DEFAULT_APPLY_CSV = os.path.join(PUBLIC_DIR, u"match_project_revit_confirmado.csv")
DEFAULT_CONTAINER_CHILDREN_FINAL_CSV = os.path.join(PUBLIC_DIR, u"asociacion_contenedor_hijos_final_p10.csv")
DEFAULT_CONTAINER_CHILDREN_OMITTED_CSV = os.path.join(PUBLIC_DIR, u"asociacion_contenedor_hijos_omitidos_por_slots.csv")
DEFAULT_APPLY_SUMMARY = os.path.join(PUBLIC_DIR, u"preparar_aplicacion_btz_summary.txt")

PLANT_CODE = u"P10"
PROJECT_CODE_RE = re.compile(r"^({0}-[^\s,;|]+)".format(PLANT_CODE), re.IGNORECASE)
ANY_P10_CODE_RE = re.compile(
    r"(?<![A-Z0-9]){0}-[A-Z0-9][A-Z0-9_.\-/]*".format(PLANT_CODE),
    re.IGNORECASE,
)

EXTENDED_CLUSTER_STATES = False
CLUSTER_MODE = u"distributed"
FORCE_ANCESTOR_CONTAINER = False

try:
    import match_cluster_resolution as _mcr
except ImportError:
    _tools = os.path.dirname(os.path.abspath(__file__))
    if _tools not in sys.path:
        sys.path.insert(0, _tools)
    import match_cluster_resolution as _mcr

BTZ_DESC_COLS = [u"btz_description_{:02d}".format(i) for i in range(1, 81)]
FORCE_ANCESTOR_SEARCH_FIELDS = (
    [u"btz_numero_activo"]
    + BTZ_DESC_COLS
    + [u"mark", u"comments", u"name", u"type", u"family", u"btz_path_detectado", u"project_path"]
)
REVIT_SEARCH_FIELDS = (
    [u"btz_numero_activo"]
    + BTZ_DESC_COLS
    + [u"mark", u"comments", u"name", u"type", u"family"]
)

OUT_FIELDS = [
    u"estado_match",
    u"tipo_asociacion",
    u"codigo_project",
    u"descripcion_project",
    u"project_id",
    u"outline_level",
    u"outline_number",
    u"parent_task_name",
    u"parent_codigo_project",
    u"ancestor_codes_project",
    u"ancestor_names_project",
    u"project_path",
    u"element_id_revit",
    u"unique_id_revit",
    u"category",
    u"family",
    u"type",
    u"name",
    u"btz_numero_activo",
    u"btz_path_actual",
    u"parametro_match",
    u"contenedor_sugerido_element_id",
    u"contenedor_sugerido_unique_id",
    u"contenedor_sugerido_path",
    u"contenedor_sugerido_nivel",
    u"slots_libres_contenedor",
    u"requiere_split_por_slots",
    u"puntaje_contenedor",
    u"segundo_puntaje_contenedor",
    u"diferencia_puntaje",
    u"criterio_contenedor",
    u"candidatos_contenedor",
    u"ancestro_project_usado",
    u"observacion",
    u"tipo_resolucion",
    u"ancestro_usado",
    u"cluster_element_ids",
    u"element_id_destino",
    u"btz_slot_sugerido",
    u"cluster_mode",
    u"motivo",
] + BTZ_DESC_COLS

CONTAINER_FIELDS = [
    u"element_id",
    u"unique_id",
    u"category",
    u"family",
    u"type",
    u"name",
    u"btz_path_detectado",
] + BTZ_DESC_COLS + [
    u"cantidad_btz_description_con_valor",
    u"slots_libres",
    u"cantidad_codigos_project_asignados_sugeridos",
]

CONFIRMADO_AUTO_FIELDS = OUT_FIELDS + [u"estado_confirmacion"]
REVISION_FIELDS = OUT_FIELDS + [u"motivo_revision"]
CONTAINER_CHILDREN_FIELDS = [
    u"codigo_project",
    u"descripcion_project",
    u"element_id_contenedor",
    u"unique_id_contenedor",
    u"btz_path_contenedor",
    u"ancestro_project_usado",
    u"tipo_asociacion",
    u"puntaje_contenedor",
    u"criterio_contenedor",
    u"requiere_split_por_slots",
]

APPLY_FIELDS = [
    u"element_id",
    u"unique_id",
    u"btz_numero_activo",
] + BTZ_DESC_COLS + [
    u"estado_match",
    u"estado_confirmacion",
    u"observacion",
    u"limpiar_valores",
]

CONTAINER_CHILDREN_FINAL_FIELDS = [
    u"codigo_project",
    u"descripcion_project",
    u"element_id_contenedor",
    u"unique_id_contenedor",
    u"btz_path_contenedor",
    u"tipo_asociacion",
    u"ancestro_project_usado",
    u"estado_asociacion",
    u"escrito_en_btz_description",
    u"btz_description_slot_usado",
    u"motivo",
]

CONTAINER_CHILDREN_OMITTED_FIELDS = [
    u"element_id_contenedor",
    u"unique_id_contenedor",
    u"btz_path_contenedor",
    u"codigo_project",
    u"descripcion_project",
    u"slots_libres",
    u"cantidad_hijos_asignados",
    u"motivo_omision",
]

EQUIVALENCIAS_TIPO = {
    u"BMB": [u"BMB", u"BOMBA", u"BOMBAS"],
    u"VLV": [u"VLV", u"VALVULA", u"VÁLVULA", u"VALVULAS", u"VÁLVULAS"],
    u"CNT": [u"CNT", u"CINTA", u"CINTAS"],
    u"RDL": [u"RDL", u"REDLER", u"REDLERS"],
    u"RSC": [u"RSC", u"ROSCA", u"ROSCAS"],
    u"ENF": [u"ENF", u"ENFRIADOR", u"ENFRIADORES"],
    u"MOL": [u"MOL", u"MOLINO", u"MOLINOS"],
    u"TST": [u"TST", u"TOASTER"],
    u"FLT": [u"FLT", u"FILTRO", u"FILTROS", u"MANGA", u"MANGAS"],
    u"VNT": [u"VNT", u"VENTILADOR", u"VENTILADORES"],
    u"TNQ": [u"TNQ", u"TANQUE", u"TANQUES"],
    u"AGT": [u"AGT", u"AGITADOR", u"AGITADORES"],
    u"CCM": [u"CCM"],
}


def _u(value):
    if value is None:
        return u""
    try:
        return str(value).strip()
    except Exception:
        return u""


def _strip_accents(value):
    text = unicodedata.normalize("NFKD", _u(value))
    return u"".join(ch for ch in text if not unicodedata.combining(ch))


def _norm_header(value):
    return _strip_accents(value).strip().lower().replace(u"_", u" ")


def _norm_code(value):
    return _u(value).upper().rstrip(u".,:;)")


def _extract_project_code(value):
    text = _u(value)
    if not text:
        return u""
    m = PROJECT_CODE_RE.match(text)
    if not m:
        return u""
    return _norm_code(m.group(1))


def _extract_p10_codes_anywhere(value):
    text = _u(value).upper()
    if not text:
        return []
    out = []
    for m in ANY_P10_CODE_RE.finditer(text):
        code = _norm_code(m.group(0))
        if code and code not in out:
            out.append(code)
    return out


def _read_text_file(path):
    last_error = None
    for enc in (u"utf-8-sig", u"utf-8", u"cp1252", u"latin1"):
        try:
            with codecs.open(path, u"r", encoding=enc) as fp:
                return fp.read(), enc
        except Exception as ex:
            last_error = ex
    raise IOError(u"No se pudo leer {0}: {1}".format(path, last_error))


def _guess_delimiter(sample):
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except Exception:
        first = sample.splitlines()[0] if sample.splitlines() else u""
        counts = [(first.count(d), d) for d in (u";", u",", u"\t", u"|")]
        counts.sort(reverse=True)
        return counts[0][1] if counts and counts[0][0] > 0 else u","


def read_delimited_rows(path):
    if not os.path.isfile(path):
        raise IOError(u"No existe el archivo: {0}".format(path))
    raw, enc = _read_text_file(path)
    delimiter = _guess_delimiter(raw[:4096])
    fp = io.StringIO(raw)
    reader = csv.DictReader(fp, delimiter=delimiter)
    rows = []
    for row in reader:
        rows.append(row)
    return rows, list(reader.fieldnames or []), delimiter, enc


def _find_first_col(fieldnames, candidates):
    norm_to_original = OrderedDict((_norm_header(h), h) for h in fieldnames)
    for cand in candidates:
        n_cand = _norm_header(cand)
        for n_header, original in norm_to_original.items():
            if n_header == n_cand or n_cand in n_header:
                return original
    return u""


def detect_project_code_column(rows, fieldnames):
    best_col = u""
    best_score = -1
    counts = {}
    for col in fieldnames:
        count = 0
        for row in rows:
            if _extract_project_code(row.get(col)):
                count += 1
        counts[col] = count
        header = _norm_header(col)
        bonus = 1000 if header in (u"codigo", u"code", u"codigo btz") else 0
        score = count * 10 + bonus
        if count > 0 and score > best_score:
            best_score = score
            best_col = col
    if not best_col:
        raise ValueError(u"No se detectó ninguna columna con códigos que empiecen con {0}-.".format(PLANT_CODE))
    return best_col, counts


def _xml_local(tag):
    return tag.rsplit(u"}", 1)[-1] if u"}" in tag else tag


def _xml_child_text(parent, child_name):
    if parent is None:
        return u""
    for child in list(parent):
        if _xml_local(child.tag) == child_name:
            return _u(child.text)
    return u""


def _load_project_codes_xml(path):
    tree = ET.parse(path)
    root = tree.getroot()

    field_alias_by_id = {}
    for ext_attr in root.findall(u".//{*}ExtendedAttributes/{*}ExtendedAttribute"):
        field_id = _xml_child_text(ext_attr, u"FieldID")
        alias = _xml_child_text(ext_attr, u"Alias")
        field_name = _xml_child_text(ext_attr, u"FieldName")
        if field_id:
            field_alias_by_id[field_id] = alias or field_name or field_id

    by_code = OrderedDict()
    duplicate_rows = defaultdict(int)
    task_count = 0
    stack_by_level = {}

    for task in root.findall(u".//{*}Tasks/{*}Task"):
        is_null = _xml_child_text(task, u"IsNull")
        if is_null == u"1":
            continue
        task_count += 1
        name = _xml_child_text(task, u"Name")
        outline_level = _xml_child_text(task, u"OutlineLevel")
        outline_number = _xml_child_text(task, u"OutlineNumber")
        try:
            level_int = int(outline_level)
        except Exception:
            level_int = 0

        ancestors = []
        for lvl in sorted(stack_by_level.keys()):
            if lvl < level_int:
                ancestors.append(stack_by_level[lvl])
        parent = ancestors[-1] if ancestors else {}
        ancestor_codes = [a[u"code"] for a in ancestors if a.get(u"code")]
        ancestor_names = [a[u"name"] for a in ancestors if a.get(u"name")]
        ancestor_outline_levels = [a.get(u"outline_level", u"") for a in ancestors if a.get(u"code")]
        project_path_parts = ancestor_names + ([name] if name else [])

        code = _extract_project_code(name)
        if not code:
            # El archivo corregido debería traer el código en Name, pero dejamos
            # fallback a atributos extendidos por robustez.
            for ext_attr in task.findall(u"{*}ExtendedAttribute"):
                value = _xml_child_text(ext_attr, u"Value")
                code = _extract_project_code(value)
                if code:
                    break
        if not code:
            stack_by_level[level_int] = {
                u"name": name,
                u"code": u"",
                u"outline_level": outline_level,
                u"outline_number": outline_number,
            }
            for lvl in list(stack_by_level.keys()):
                if lvl > level_int:
                    del stack_by_level[lvl]
            continue

        duplicate_rows[code] += 1
        if code in by_code:
            stack_by_level[level_int] = {
                u"name": name,
                u"code": code,
                u"outline_level": outline_level,
                u"outline_number": outline_number,
            }
            for lvl in list(stack_by_level.keys()):
                if lvl > level_int:
                    del stack_by_level[lvl]
            continue

        ext_values = {}
        for ext_attr in task.findall(u"{*}ExtendedAttribute"):
            field_id = _xml_child_text(ext_attr, u"FieldID")
            value = _xml_child_text(ext_attr, u"Value")
            alias = field_alias_by_id.get(field_id, field_id)
            if alias:
                ext_values[_norm_header(alias)] = value

        desc = (
            ext_values.get(_norm_header(u"Descripción"))
            or ext_values.get(_norm_header(u"Descripcion"))
            or _xml_child_text(task, u"Notes")
        )

        by_code[code] = {
            u"codigo_project": code,
            u"descripcion_project": _u(desc),
            u"project_id": _xml_child_text(task, u"ID"),
            u"outline_level": outline_level,
            u"outline_number": outline_number,
            u"parent_task_name": parent.get(u"name", u""),
            u"parent_codigo_project": parent.get(u"code", u""),
            u"ancestor_codes_project": u" > ".join(ancestor_codes),
            u"ancestor_names_project": u" > ".join(ancestor_names),
            u"project_path": u" > ".join(project_path_parts),
            u"_ancestor_codes_list": list(reversed(ancestor_codes)),
            u"_ancestor_outline_levels_list": list(reversed(ancestor_outline_levels)),
            u"_duplicate_project_rows": 0,
        }

        stack_by_level[level_int] = {
            u"name": name,
            u"code": code,
            u"outline_level": outline_level,
            u"outline_number": outline_number,
        }
        for lvl in list(stack_by_level.keys()):
            if lvl > level_int:
                del stack_by_level[lvl]

    for code, n in duplicate_rows.items():
        if code in by_code:
            by_code[code][u"_duplicate_project_rows"] = n

    meta = {
        u"delimiter": u"(xml)",
        u"encoding": u"(xml parser)",
        u"code_col": u"Task/Name",
        u"desc_col": u"ExtendedAttribute[Alias=Descripción] o Notes",
        u"id_col": u"Task/ID",
        u"outline_level_col": u"Task/OutlineLevel",
        u"outline_number_col": u"Task/OutlineNumber",
        u"code_counts": {},
        u"raw_rows": task_count,
    }
    return list(by_code.values()), meta


def _load_project_codes_delimited(path):
    rows, fieldnames, delimiter, enc = read_delimited_rows(path)
    code_col, code_counts = detect_project_code_column(rows, fieldnames)
    desc_col = _find_first_col(fieldnames, [u"Descripcion", u"Descripción", u"Task Name"])
    id_col = _find_first_col(fieldnames, [u"ID"])
    outline_level_col = _find_first_col(fieldnames, [u"Outline Level"])
    outline_number_col = _find_first_col(fieldnames, [u"Outline Number"])

    by_code = OrderedDict()
    duplicate_rows = defaultdict(int)

    for raw in rows:
        code = _extract_project_code(raw.get(code_col))
        if not code:
            continue
        duplicate_rows[code] += 1
        if code in by_code:
            continue
        desc = _u(raw.get(desc_col))
        if desc_col == code_col:
            desc = PROJECT_CODE_RE.sub(u"", desc, count=1).strip(u" -:|\t")
        by_code[code] = {
            u"codigo_project": code,
            u"descripcion_project": desc,
            u"project_id": _u(raw.get(id_col)),
            u"outline_level": _u(raw.get(outline_level_col)),
            u"outline_number": _u(raw.get(outline_number_col)),
            u"parent_task_name": u"",
            u"parent_codigo_project": u"",
            u"ancestor_codes_project": u"",
            u"ancestor_names_project": u"",
            u"project_path": code,
            u"_ancestor_codes_list": [],
            u"_ancestor_outline_levels_list": [],
            u"_duplicate_project_rows": 0,
        }

    for code, n in duplicate_rows.items():
        if code in by_code:
            by_code[code][u"_duplicate_project_rows"] = n

    meta = {
        u"delimiter": delimiter,
        u"encoding": enc,
        u"code_col": code_col,
        u"desc_col": desc_col,
        u"id_col": id_col,
        u"outline_level_col": outline_level_col,
        u"outline_number_col": outline_number_col,
        u"code_counts": code_counts,
        u"raw_rows": len(rows),
    }
    return list(by_code.values()), meta


def load_project_codes(path):
    _, ext = os.path.splitext(path.lower())
    if ext == u".xml":
        return _load_project_codes_xml(path)
    return _load_project_codes_delimited(path)


def load_revit_rows(path):
    rows, fieldnames, delimiter, enc = read_delimited_rows(path)
    return rows, {
        u"delimiter": delimiter,
        u"encoding": enc,
        u"fieldnames": fieldnames,
    }


def build_revit_code_index(revit_rows):
    index = defaultdict(dict)
    for row in revit_rows:
        element_key = _u(row.get(u"element_id")) or _u(row.get(u"unique_id"))
        if not element_key:
            continue
        for field in REVIT_SEARCH_FIELDS:
            val = row.get(field)
            for code in _extract_p10_codes_anywhere(val):
                hit = index[code].setdefault(
                    element_key,
                    {u"row": row, u"params": []},
                )
                if field not in hit[u"params"]:
                    hit[u"params"].append(field)
    return index


def _row_element_key(row):
    return _u(row.get(u"element_id")) or _u(row.get(u"unique_id"))


def _desc_values(row):
    return [_u(row.get(col)) for col in BTZ_DESC_COLS]


def _count_btz_values(row):
    raw_count = _u(row.get(u"cantidad_btz_description_con_valor"))
    try:
        return int(raw_count)
    except Exception:
        return sum(1 for v in _desc_values(row) if v)


def _tokenize_container_text(value):
    text = _strip_accents(value).upper()
    if not text:
        return set()
    return set(t for t in re.split(r"[^A-Z0-9]+", text) if t)


def _container_tokens(row):
    tokens = set()
    vals = (
        [row.get(u"btz_path_detectado"), row.get(u"btz_numero_activo")]
        + _desc_values(row)
        + [row.get(u"name"), row.get(u"type"), row.get(u"family")]
    )
    for val in vals:
        tokens.update(_tokenize_container_text(val))
    return tokens


def _container_haystack(row):
    vals = (
        [row.get(u"btz_path_detectado"), row.get(u"btz_numero_activo")]
        + _desc_values(row)
        + [row.get(u"name"), row.get(u"type"), row.get(u"family")]
    )
    return _strip_accents(u" | ".join(_u(v) for v in vals)).upper()


def _container_path_tokens(row):
    return _tokenize_container_text(row.get(u"btz_path_detectado"))


def build_revit_containers(revit_rows):
    containers = []
    for row in revit_rows:
        count = _count_btz_values(row)
        if count <= 0:
            continue
        key = _row_element_key(row)
        if not key:
            continue
        path = _u(row.get(u"btz_path_detectado"))
        c = {
            u"element_id": _u(row.get(u"element_id")),
            u"unique_id": _u(row.get(u"unique_id")),
            u"category": _u(row.get(u"category")),
            u"family": _u(row.get(u"family")),
            u"type": _u(row.get(u"type")),
            u"name": _u(row.get(u"name")),
            u"btz_path_detectado": path,
            u"cantidad_btz_description_con_valor": count,
            u"slots_libres": max(0, 80 - count),
            u"cantidad_codigos_project_asignados_sugeridos": 0,
            u"_row": row,
            u"_key": key,
            u"_tokens": _container_tokens(row),
            u"_haystack": _container_haystack(row),
            u"_path_tokens": _container_path_tokens(row),
        }
        for col in BTZ_DESC_COLS:
            c[col] = _u(row.get(col))
        containers.append(c)
    return containers


def _container_dict_from_revit_row(row):
    """Dict contenedor alineado con build_revit_containers (permite count 0 para índice puntual)."""
    key = _row_element_key(row)
    if not key:
        return None
    count = _count_btz_values(row)
    path = _u(row.get(u"btz_path_detectado"))
    c = {
        u"element_id": _u(row.get(u"element_id")),
        u"unique_id": _u(row.get(u"unique_id")),
        u"category": _u(row.get(u"category")),
        u"family": _u(row.get(u"family")),
        u"type": _u(row.get(u"type")),
        u"name": _u(row.get(u"name")),
        u"btz_path_detectado": path,
        u"cantidad_btz_description_con_valor": count,
        u"slots_libres": max(0, 80 - count),
        u"cantidad_codigos_project_asignados_sugeridos": 0,
        u"_row": row,
        u"_key": key,
        u"_tokens": _container_tokens(row),
        u"_haystack": _container_haystack(row),
        u"_path_tokens": _container_path_tokens(row),
    }
    for col in BTZ_DESC_COLS:
        c[col] = _u(row.get(col))
    return c


def _containers_for_punctual_hits(hits, containers_by_eid):
    out = []
    for h in hits:
        row = h.get(u"row")
        if not row:
            return None
        eid = _u(row.get(u"element_id"))
        if not eid:
            return None
        c = containers_by_eid.get(eid) or _container_dict_from_revit_row(row)
        if not c:
            return None
        out.append(c)
    return out


def _project_prefixes(code):
    parts = _norm_code(code).split(u"-")
    prefixes = []
    for n in range(len(parts) - 1, 1, -1):
        prefix = u"-".join(parts[:n])
        if prefix and prefix != code and prefix not in prefixes:
            prefixes.append(prefix)
    if parts and parts[0] not in prefixes:
        prefixes.append(parts[0])
    return prefixes


def _container_sectors(container):
    sectors = set()
    pattern = r"(?<![A-Z0-9]){0}-([A-Z0-9]+)".format(re.escape(PLANT_CODE))
    for m in re.finditer(pattern, container[u"_haystack"]):
        sector = _u(m.group(1)).upper()
        if sector:
            sectors.add(sector)
    return sectors


def _score_container_for_code(code, container):
    code_norm = _norm_code(code)
    blocks = [b for b in code_norm.split(u"-") if b]
    prefix3 = u"-".join(blocks[:3]) if len(blocks) >= 3 else u""
    prefix2 = u"-".join(blocks[:2]) if len(blocks) >= 2 else u""
    sector = blocks[1] if len(blocks) >= 2 else u""
    tipo = blocks[2] if len(blocks) >= 3 else u""
    score = 0
    criteria = []

    exact_vals = [_u(container.get(u"btz_numero_activo")).upper()]
    exact_vals.extend(_u(container.get(col)).upper() for col in BTZ_DESC_COLS)
    if code_norm in exact_vals:
        score += 100
        criteria.append(u"+100 exacto BTZ/NumeroActivo")

    if prefix3 and (
        prefix3 in container[u"_haystack"]
        or set(prefix3.split(u"-")).issubset(container[u"_tokens"])
    ):
        score += 80
        criteria.append(u"+80 contiene {0}".format(prefix3))

    synonyms = EQUIVALENCIAS_TIPO.get(tipo, [tipo] if tipo else [])
    synonym_tokens = set(_strip_accents(x).upper() for x in synonyms if x)
    matched_syn = sorted(synonym_tokens.intersection(container[u"_tokens"]))
    if matched_syn:
        score += 60
        criteria.append(u"+60 equivalencia tipo {0}".format(u"/".join(matched_syn)))

    if prefix2 and (
        prefix2 in container[u"_haystack"]
        or set(prefix2.split(u"-")).issubset(container[u"_tokens"])
    ):
        score += 40
        criteria.append(u"+40 contiene {0}".format(prefix2))

    if PLANT_CODE in container[u"_tokens"]:
        score += 20
        criteria.append(u"+20 contiene {0}".format(PLANT_CODE))

    path_hits = 0
    for block in blocks:
        if block in container[u"_path_tokens"]:
            path_hits += 1
    if path_hits:
        score += path_hits * 10
        criteria.append(u"+{0} bloques en path".format(path_hits * 10))

    sectors = _container_sectors(container)
    if sector and sectors and sector not in sectors:
        score -= 30
        criteria.append(u"-30 otro sector ({0})".format(u",".join(sorted(sectors))))

    if container[u"cantidad_codigos_project_asignados_sugeridos"] > 80:
        score -= 20
        criteria.append(u"-20 contenedor supera 80 sugeridos")

    return {
        u"container": container,
        u"score": score,
        u"criteria": u"; ".join(criteria),
    }


def rank_container_candidates(code, containers):
    ranked = [_score_container_for_code(code, c) for c in containers]
    ranked = [r for r in ranked if r[u"score"] > 0]
    ranked.sort(
        key=lambda r: (
            -r[u"score"],
            r[u"container"][u"cantidad_codigos_project_asignados_sugeridos"],
            -r[u"container"][u"cantidad_btz_description_con_valor"],
            r[u"container"][u"element_id"],
        )
    )
    return ranked


def _format_candidates(ranked, limit=8):
    parts = []
    for r in ranked[:limit]:
        c = r[u"container"]
        parts.append(
            u"{0}:{1}:{2}".format(
                c.get(u"element_id"),
                r[u"score"],
                c.get(u"btz_path_detectado") or u"(sin path)",
            )
        )
    if len(ranked) > limit:
        parts.append(u"... +{0}".format(len(ranked) - limit))
    return u" || ".join(parts)


def _path_segments(value):
    return [_norm_code(p) for p in _u(value).split(u">") if _u(p)]


def _container_contains_ancestor(container, ancestor_code):
    anc = _norm_code(ancestor_code)
    if not anc:
        return False
    if _norm_code(container.get(u"btz_numero_activo")) == anc:
        return True
    for col in BTZ_DESC_COLS:
        if _norm_code(container.get(col)) == anc:
            return True
    return anc in _path_segments(container.get(u"btz_path_detectado"))


def find_container_by_project_ancestor(project_item, containers):
    for ancestor in project_item.get(u"_ancestor_codes_list", []):
        hits = [c for c in containers if _container_contains_ancestor(c, ancestor)]
        if hits:
            return ancestor, hits
    return u"", []


def _blank_output(project_item, estado, observacion=u"", parametro_match=u"", tipo_asociacion=u""):
    out = {
        u"estado_match": estado,
        u"tipo_asociacion": tipo_asociacion,
        u"codigo_project": project_item[u"codigo_project"],
        u"descripcion_project": project_item[u"descripcion_project"],
        u"project_id": project_item[u"project_id"],
        u"outline_level": project_item[u"outline_level"],
        u"outline_number": project_item[u"outline_number"],
        u"parent_task_name": project_item.get(u"parent_task_name", u""),
        u"parent_codigo_project": project_item.get(u"parent_codigo_project", u""),
        u"ancestor_codes_project": project_item.get(u"ancestor_codes_project", u""),
        u"ancestor_names_project": project_item.get(u"ancestor_names_project", u""),
        u"project_path": project_item.get(u"project_path", u""),
        u"element_id_revit": u"",
        u"unique_id_revit": u"",
        u"category": u"",
        u"family": u"",
        u"type": u"",
        u"name": u"",
        u"btz_numero_activo": u"",
        u"btz_path_actual": u"",
        u"parametro_match": parametro_match,
        u"contenedor_sugerido_element_id": u"",
        u"contenedor_sugerido_unique_id": u"",
        u"contenedor_sugerido_path": u"",
        u"contenedor_sugerido_nivel": u"",
        u"slots_libres_contenedor": u"",
        u"requiere_split_por_slots": u"",
        u"puntaje_contenedor": u"",
        u"segundo_puntaje_contenedor": u"",
        u"diferencia_puntaje": u"",
        u"criterio_contenedor": u"",
        u"candidatos_contenedor": u"",
        u"ancestro_project_usado": u"",
        u"observacion": observacion,
        u"tipo_resolucion": u"",
        u"ancestro_usado": u"",
        u"cluster_element_ids": u"",
        u"element_id_destino": u"",
        u"btz_slot_sugerido": u"",
        u"cluster_mode": u"",
        u"motivo": u"",
    }
    for col in BTZ_DESC_COLS:
        out[col] = u""
    return out


def _output_from_revit(project_item, revit_row, estado, parametro_match, observacion, tipo_asociacion):
    out = _blank_output(project_item, estado, observacion, parametro_match, tipo_asociacion)
    out[u"element_id_revit"] = _u(revit_row.get(u"element_id"))
    out[u"unique_id_revit"] = _u(revit_row.get(u"unique_id"))
    out[u"category"] = _u(revit_row.get(u"category"))
    out[u"family"] = _u(revit_row.get(u"family"))
    out[u"type"] = _u(revit_row.get(u"type"))
    out[u"name"] = _u(revit_row.get(u"name"))
    out[u"btz_numero_activo"] = _u(revit_row.get(u"btz_numero_activo"))
    out[u"btz_path_actual"] = _u(revit_row.get(u"btz_path_detectado"))
    for col in BTZ_DESC_COLS:
        out[col] = _u(revit_row.get(col))
    return out


def _output_from_container(project_item, container, estado, observacion, score_info):
    out = _blank_output(
        project_item,
        estado,
        observacion,
        u"contenedor_scoring",
        u"contenedor",
    )
    row = container[u"_row"]
    out[u"element_id_revit"] = container[u"element_id"]
    out[u"unique_id_revit"] = container[u"unique_id"]
    out[u"category"] = container[u"category"]
    out[u"family"] = container[u"family"]
    out[u"type"] = container[u"type"]
    out[u"name"] = container[u"name"]
    out[u"btz_numero_activo"] = _u(row.get(u"btz_numero_activo"))
    out[u"btz_path_actual"] = container[u"btz_path_detectado"]
    out[u"contenedor_sugerido_element_id"] = container[u"element_id"]
    out[u"contenedor_sugerido_unique_id"] = container[u"unique_id"]
    out[u"contenedor_sugerido_path"] = container[u"btz_path_detectado"]
    out[u"contenedor_sugerido_nivel"] = str(container[u"cantidad_btz_description_con_valor"])
    out[u"slots_libres_contenedor"] = str(container[u"slots_libres"])
    out[u"puntaje_contenedor"] = str(score_info.get(u"score", u""))
    out[u"segundo_puntaje_contenedor"] = str(score_info.get(u"second_score", u""))
    out[u"diferencia_puntaje"] = str(score_info.get(u"diff", u""))
    out[u"criterio_contenedor"] = score_info.get(u"criteria", u"")
    out[u"candidatos_contenedor"] = score_info.get(u"candidates", u"")
    out[u"ancestro_project_usado"] = score_info.get(u"ancestor", u"")
    for col in BTZ_DESC_COLS:
        out[col] = container[col]
    return out


def _build_global_codes_in_revit(revit_rows):
    found = set()
    for row in revit_rows:
        for field in [u"btz_numero_activo"] + BTZ_DESC_COLS:
            for c in _extract_p10_codes_anywhere(row.get(field)):
                found.add(_norm_code(c))
    return found


_CONTAINER_ASSIGN_ESTADOS = frozenset(
    (
        u"asignable_a_contenedor",
        u"contenedor_unico",
        u"contenedor_logico_duplicado_canonical",
        u"contenedor_logico_duplicado_distributed",
    )
)

_ESTADO_MERGE_RANK = {
    u"match_directo": 100,
    u"match_elemento_puntual": 95,
    u"ya_existente_en_btz": 90,
    u"contenedor_logico_duplicado_distributed": 82,
    u"contenedor_logico_duplicado_canonical": 81,
    u"contenedor_unico": 80,
    u"asignable_a_contenedor": 79,
    u"omitido_por_slots": 25,
    u"sin_contenedor": 22,
    u"ambiguo_real": 15,
    u"contenedor_duplicado": 12,
    u"duplicado": 10,
}


def _cluster_key_from_prep_row(row):
    csv_ids = _u(row.get(u"cluster_element_ids"))
    if csv_ids:
        return csv_ids
    return _u(row.get(u"contenedor_sugerido_element_id"))


def _cluster_eid_list_from_row(row):
    csv_ids = _u(row.get(u"cluster_element_ids"))
    if csv_ids:
        parts = [x.strip() for x in csv_ids.split(u";") if x.strip()]
        if parts:
            try:
                nums = sorted(set(int(p) for p in parts))
                return [_u(n) for n in nums]
            except Exception:
                return sorted(set(parts))
    eid = _u(row.get(u"contenedor_sugerido_element_id"))
    return [eid] if eid else []


def _capacity_slots_05_80_for_prep_row(row, containers_by_id):
    est = _u(row.get(u"estado_match"))
    eids = _cluster_eid_list_from_row(row)
    if not eids:
        return 0
    if est == u"contenedor_logico_duplicado_canonical":
        master = _u(row.get(u"element_id_destino")) or eids[0]
        c = containers_by_id.get(master)
        if not c:
            return 0
        return _count_free_slots_05_80_source(c.get(u"_row", {}))
    total = 0
    for eid in eids:
        c = containers_by_id.get(eid)
        if not c:
            continue
        total += _count_free_slots_05_80_source(c.get(u"_row", {}))
    return total


_REGISTRY_SOURCE_ESTADOS = frozenset(
    (
        u"contenedor_logico_duplicado_distributed",
        u"contenedor_logico_duplicado_canonical",
        u"contenedor_unico",
        u"asignable_a_contenedor",
        u"match_directo",
        u"ya_existente_en_btz",
    )
)


def _norm_for_force_ancestor_match(text):
    t = re.sub(r"\s+", u" ", _u(text)).strip()
    return _strip_accents(t).upper()


def _revit_row_force_search_blob(revit_row):
    parts = []
    for field in FORCE_ANCESTOR_SEARCH_FIELDS:
        parts.append(_norm_for_force_ancestor_match(revit_row.get(field)))
    return u" ".join(p for p in parts if p)


def _ancestor_text_in_revit_row(revit_row, ancestor_raw):
    anc = _norm_for_force_ancestor_match(ancestor_raw)
    if not anc:
        return False
    blob = _revit_row_force_search_blob(revit_row)
    if not blob:
        return False
    return anc in blob


def _revit_row_belongs_to_current_plant(revit_row):
    plant = PLANT_CODE.upper()
    blob = _revit_row_force_search_blob(revit_row)
    if not blob:
        return False
    if blob.find(plant + u"-") >= 0:
        return True
    pattern = r"(?<![A-Z0-9]){0}(?![A-Z0-9])".format(re.escape(plant))
    return re.search(pattern, blob) is not None


def _code_in_container_bt01_80(container, code):
    code_norm = _norm_code(code)
    row = container.get(u"_row", {}) if container else {}
    if _norm_code(row.get(u"btz_numero_activo")) == code_norm:
        return True
    for col in BTZ_DESC_COLS:
        if _norm_code(row.get(col)) == code_norm:
            return True
    return False


def _code_in_any_containers_bt01_80(code, containers_list):
    for c in containers_list:
        if c and _code_in_container_bt01_80(c, code):
            return True
    return False


def _prep_row_rank_for_merge(row):
    return _ESTADO_MERGE_RANK.get(_u(row.get(u"estado_match")), 0)


def _union_cluster_csv(*csv_parts):
    seen = set()
    ordered = []
    for raw in csv_parts:
        if not _u(raw):
            continue
        for part in _u(raw).split(u";"):
            p = part.strip()
            if not p or p in seen:
                continue
            seen.add(p)
            ordered.append(p)
    if not ordered:
        return u""
    try:
        nums = sorted(set(int(x) for x in ordered))
        return u";".join(_u(x) for x in nums)
    except Exception:
        return u";".join(sorted(set(ordered)))


def _merge_prep_row_group(rows):
    if not rows:
        return None
    if len(rows) == 1:
        return dict(rows[0])
    best = max(rows, key=_prep_row_rank_for_merge)
    out = dict(best)
    obs_parts = []
    clusters = []
    for r in rows:
        o = _u(r.get(u"observacion"))
        if o and o not in obs_parts:
            obs_parts.append(o)
        cl = _u(r.get(u"cluster_element_ids"))
        if cl:
            clusters.append(cl)
    out[u"observacion"] = u" ".join(obs_parts) if obs_parts else out.get(u"observacion", u"")
    merged_c = _union_cluster_csv(*clusters)
    if merged_c:
        out[u"cluster_element_ids"] = merged_c
    return out


def _dedupe_out_rows_one_per_codigo_project(out_rows, project_items):
    if not out_rows:
        return out_rows
    order_first = OrderedDict()
    for it in project_items:
        c = _norm_code(it.get(u"codigo_project"))
        if c and c not in order_first:
            order_first[c] = True
    buckets = defaultdict(list)
    for row in out_rows:
        c = _norm_code(row.get(u"codigo_project"))
        if c:
            buckets[c].append(row)
    out = []
    for c in order_first.keys():
        grp = buckets.get(c) or []
        if not grp:
            continue
        if len(grp) == 1:
            out.append(grp[0])
            continue
        merged = _merge_prep_row_group(grp)
        if merged is None:
            continue
        out.append(merged)
    for c, grp in buckets.items():
        if c in order_first:
            continue
        if not grp:
            continue
        out.extend(grp)
    return out


def _sync_row_based_counts(out_rows, counts, containers_by_id):
    """Alinea contadores con las filas finales (dedupe + force)."""
    n_force = sum(1 for r in out_rows if _u(r.get(u"tipo_resolucion")) == u"force_ancestor_container")
    counts[u"match_elemento_puntual"] = sum(
        1 for r in out_rows if _u(r.get(u"estado_match")) == u"match_elemento_puntual"
    )
    counts[u"match_directo"] = sum(1 for r in out_rows if _u(r.get(u"estado_match")) == u"match_directo")
    counts[u"duplicado"] = sum(1 for r in out_rows if _u(r.get(u"estado_match")) == u"duplicado")
    counts[u"ambiguo_real"] = sum(1 for r in out_rows if _u(r.get(u"estado_match")) == u"ambiguo_real")
    counts[u"ya_existente_en_btz"] = sum(
        1 for r in out_rows if _u(r.get(u"estado_match")) == u"ya_existente_en_btz"
    )
    counts[u"contenedor_unico"] = sum(
        1 for r in out_rows if _u(r.get(u"estado_match")) == u"contenedor_unico"
    )
    counts[u"contenedor_duplicado"] = sum(
        1 for r in out_rows if _u(r.get(u"estado_match")) == u"contenedor_duplicado"
    )
    counts[u"sin_contenedor"] = sum(
        1 for r in out_rows if _u(r.get(u"estado_match")) == u"sin_contenedor"
    )
    counts[u"omitido_por_slots"] = sum(
        1 for r in out_rows if _u(r.get(u"estado_match")) == u"omitido_por_slots"
    )
    counts[u"contenedor_logico_duplicado_canonical"] = sum(
        1 for r in out_rows if _u(r.get(u"estado_match")) == u"contenedor_logico_duplicado_canonical"
    )
    counts[u"contenedor_logico_duplicado_distributed"] = sum(
        1 for r in out_rows if _u(r.get(u"estado_match")) == u"contenedor_logico_duplicado_distributed"
    )
    counts[u"contenedor_logico_duplicado"] = (
        counts[u"contenedor_logico_duplicado_canonical"]
        + counts[u"contenedor_logico_duplicado_distributed"]
    )
    counts[u"asignable_a_contenedor"] = sum(
        1
        for r in out_rows
        if _u(r.get(u"estado_match"))
        in (
            u"contenedor_unico",
            u"asignable_a_contenedor",
            u"contenedor_logico_duplicado_canonical",
            u"contenedor_logico_duplicado_distributed",
        )
    )
    counts[u"ya_existente_en_btz_multi_id"] = sum(
        1
        for r in out_rows
        if _u(r.get(u"estado_match")) == u"ya_existente_en_btz"
        and _u(r.get(u"tipo_resolucion")) == u"codigo_existente_multi_id"
    )
    counts[u"codigos_existentes_multi_id_colapsados"] = counts[u"ya_existente_en_btz_multi_id"]
    counts[u"force_ancestor_container"] = n_force
    counts[u"resueltos_por_force_ancestor_container"] = n_force
    counts[u"_resolved_by_force_ancestor_container"] = n_force
    clusters_seen = set()
    cap_total = 0
    for r in out_rows:
        if _u(r.get(u"tipo_resolucion")) != u"force_ancestor_container":
            continue
        ck = _cluster_key_from_prep_row(r)
        if not ck or ck in clusters_seen:
            continue
        clusters_seen.add(ck)
        cap_total += _capacity_slots_05_80_for_prep_row(r, containers_by_id)
    counts[u"clusters_force_ancestor_container"] = len(clusters_seen)
    counts[u"capacidad_total_force_ancestor"] = cap_total
    counts[u"capacidad_usada_force_ancestor"] = n_force
    counts[u"_resolved_by_ancestor_cluster_registry"] = sum(
        1 for r in out_rows if _u(r.get(u"tipo_resolucion")) == u"ambiguo_absorbido_cluster_capacidad"
    )
    counts[u"_resolved_by_aggressive_ancestor_superior"] = sum(
        1 for r in out_rows if _u(r.get(u"tipo_resolucion")) == u"ambiguo_absorbido_por_ancestro_superior"
    )
    counts[u"_resolved_by_primer_ancestro_valido_relajado"] = sum(
        1 for r in out_rows if _u(r.get(u"tipo_resolucion")) == u"ambiguo_absorbido_por_primer_ancestro_valido"
    )
    counts[u"_resolved_by_punctual_multi_cluster"] = sum(
        1
        for r in out_rows
        if _u(r.get(u"tipo_resolucion")) == u"ambiguo_falso_por_contenedor_duplicado"
        and _u(r.get(u"tipo_asociacion")) == u"contenedor_por_match_puntual_multi"
    )
    counts[u"_resolved_by_ancestor"] = sum(
        1 for r in out_rows if _u(r.get(u"tipo_resolucion")) == u"contenedor_unico_ancestro"
    )
    counts[u"_resolved_by_scoring"] = sum(
        1 for r in out_rows if _u(r.get(u"tipo_resolucion")) == u"scoring_claro"
    )


def _force_ancestor_container_pass(out_rows, project_items, revit_rows, containers_by_id):
    if not FORCE_ANCESTOR_CONTAINER or not EXTENDED_CLUSTER_STATES:
        return out_rows
    plant_prefix = PLANT_CODE.upper() + u"-"

    by_code = OrderedDict()
    for row in out_rows:
        c = _norm_code(row.get(u"codigo_project"))
        if not c:
            continue
        if c not in by_code:
            by_code[c] = row
        else:
            merged = _merge_prep_row_group([by_code[c], row])
            by_code[c] = merged

    demand = _demand_by_cluster_key(list(by_code.values()))
    assigned_codes_this_run = set()

    for item in project_items:
        code = _norm_code(item.get(u"codigo_project"))
        if not code or code not in by_code:
            continue
        row = by_code[code]
        if _u(row.get(u"estado_match")) != u"ambiguo_real":
            continue
        if not code.startswith(plant_prefix):
            continue

        resolved = False
        for anc in item.get(u"_ancestor_codes_list", []):
            anc_s = _u(anc)
            if not anc_s or not _norm_code(anc_s).startswith(plant_prefix):
                continue
            matching_wraps = []
            seen_eid = set()
            for rr in revit_rows:
                if not _revit_row_belongs_to_current_plant(rr):
                    continue
                if not _ancestor_text_in_revit_row(rr, anc_s):
                    continue
                eid = _u(rr.get(u"element_id"))
                if not eid or eid in seen_eid:
                    continue
                seen_eid.add(eid)
                cw = containers_by_id.get(eid) or _container_dict_from_revit_row(rr)
                if cw:
                    matching_wraps.append(cw)
            if not matching_wraps:
                continue

            rec = _cluster_record_from_revit_hits(matching_wraps, containers_by_id)
            ck = rec[u"cluster_key"] if rec else u""

            if not rec or rec[u"cap_05_80"] < 1:
                br = _blank_output(
                    item,
                    u"omitido_por_slots",
                    u"force_ancestor_container: ancestro {0} hallado pero cluster sin capacidad BTZ_05-80.".format(
                        _norm_code(anc_s)
                    ),
                    tipo_asociacion=u"sin_asociacion",
                )
                br[u"tipo_resolucion"] = u"force_ancestor_sin_capacidad"
                br[u"ancestro_usado"] = _norm_code(anc_s)
                br[u"motivo"] = u"force_ancestor_container: sin_slots_en_cluster"
                by_code[code] = br
                resolved = True
                break

            if demand.get(ck, 0) >= rec[u"cap_05_80"]:
                br = _blank_output(
                    item,
                    u"omitido_por_slots",
                    u"force_ancestor_container: demanda ya satura capacidad del cluster ancestro {0}.".format(
                        _norm_code(anc_s)
                    ),
                    tipo_asociacion=u"sin_asociacion",
                )
                br[u"tipo_resolucion"] = u"force_ancestor_omitido_por_slots"
                br[u"ancestro_usado"] = _norm_code(anc_s)
                br[u"cluster_element_ids"] = ck
                br[u"motivo"] = u"force_ancestor_container: omitido_por_demanda_cluster"
                by_code[code] = br
                resolved = True
                break

            if _code_in_any_containers_bt01_80(code, matching_wraps):
                continue

            if code in assigned_codes_this_run:
                break

            cluster_cs = _containers_list_for_registry_rec(rec, containers_by_id)
            if not cluster_cs:
                alt = []
                for cw in matching_wraps:
                    eid = _u(cw.get(u"element_id"))
                    if eid and eid in rec[u"eids"]:
                        alt.append(cw)
                cluster_cs = alt if len(alt) == len(rec[u"eids"]) else None
            if not cluster_cs:
                continue

            master = _mcr.pick_canonical_master(cluster_cs, _norm_code(anc_s))
            master[u"cantidad_codigos_project_asignados_sugeridos"] += 1
            cluster_csv = _mcr.cluster_element_ids_csv(cluster_cs)
            cands = u" || ".join(
                u"{0}:170:{1}".format(x.get(u"element_id"), x.get(u"btz_path_detectado") or u"")
                for x in cluster_cs[:8]
            )
            score_info = {
                u"score": 170,
                u"second_score": 0,
                u"diff": 170,
                u"criteria": u"force_ancestor_container_text_match",
                u"candidates": cands,
                u"ancestor": _norm_code(anc_s),
            }
            obs = (
                u"force_ancestor_container: primer ancestro Project encontrado en export Revit ({0}) con capacidad BTZ_05-80."
            ).format(_norm_code(anc_s))
            out_row = _output_from_container(
                item,
                master,
                u"contenedor_logico_duplicado_distributed",
                obs,
                score_info,
            )
            out_row[u"tipo_asociacion"] = u"contenedor_por_ancestro_forzado"
            out_row[u"tipo_resolucion"] = u"force_ancestor_container"
            out_row[u"ancestro_usado"] = _norm_code(anc_s)
            out_row[u"cluster_element_ids"] = cluster_csv
            out_row[u"cluster_mode"] = CLUSTER_MODE
            out_row[u"element_id_destino"] = u""
            out_row[u"motivo"] = (
                u"force_ancestor_container: asignado al primer ancestro Project encontrado en Revit con capacidad"
            )
            demand[ck] = demand.get(ck, 0) + 1
            assigned_codes_this_run.add(code)
            by_code[code] = out_row
            resolved = True
            break

        if resolved:
            continue

        if _u(by_code[code].get(u"estado_match")) == u"ambiguo_real":
            br = _blank_output(
                item,
                u"sin_contenedor",
                u"force_ancestor_container: ningún ancestro de Project coincide con el export Revit (campos BTZ/Mark/Comments/path).",
                tipo_asociacion=u"sin_asociacion",
            )
            br[u"tipo_resolucion"] = u"force_ancestor_sin_contenedor"
            br[u"motivo"] = u"force_ancestor_container: sin_ancestro_en_modelo"
            by_code[code] = br

    out_ordered = []
    seen = set()
    for it in project_items:
        c = _norm_code(it.get(u"codigo_project"))
        if not c or c in seen:
            continue
        seen.add(c)
        if c in by_code:
            out_ordered.append(by_code[c])
    for c, row in by_code.items():
        if c not in seen:
            out_ordered.append(row)
    return out_ordered


def _registry_cluster_record_from_row(row, containers_by_id):
    est = _u(row.get(u"estado_match"))
    eids = _cluster_eid_list_from_row(row)
    ck = _cluster_key_from_prep_row(row)
    if est == u"match_directo":
        eid = _u(row.get(u"element_id_revit"))
        if not eid:
            return None
        eids = [eid]
        ck = eid
    if est == u"ya_existente_en_btz" and _u(row.get(u"tipo_resolucion")) != u"codigo_existente_multi_id":
        return None
    if not eids or not ck:
        return None
    total_cap = 0
    for eid in eids:
        cw = containers_by_id.get(eid)
        if not cw:
            return None
        total_cap += _count_free_slots_05_80_source(cw.get(u"_row", {}))
    if total_cap < 1:
        return None
    path = (
        _u(row.get(u"contenedor_sugerido_path"))
        or _u(row.get(u"btz_path_actual"))
        or _u((containers_by_id.get(eids[0]) or {}).get(u"btz_path_detectado"))
    )
    return {
        u"cluster_key": ck,
        u"eids": list(eids),
        u"cap_05_80": total_cap,
        u"path": path,
    }


def _build_ancestor_cluster_registry(out_rows, containers_by_id):
    registry = defaultdict(list)
    plant_prefix = PLANT_CODE.upper() + u"-"

    def _add_code(c, rec):
        nc = _norm_code(c)
        if not nc.startswith(plant_prefix):
            return
        lst = registry[nc]
        if any(x[u"cluster_key"] == rec[u"cluster_key"] for x in lst):
            return
        lst.append(dict(rec))

    for row in out_rows:
        est = _u(row.get(u"estado_match"))
        if est not in _REGISTRY_SOURCE_ESTADOS:
            continue
        rec = _registry_cluster_record_from_row(row, containers_by_id)
        if not rec:
            continue
        _add_code(row.get(u"codigo_project"), rec)
        _add_code(row.get(u"ancestro_usado"), rec)
        par = row.get(u"parent_codigo_project")
        if par and _norm_code(par) != _norm_code(row.get(u"codigo_project")):
            _add_code(par, rec)
    return registry


def _enrich_registry_singleton_ancestors(project_items, containers, registry):
    plant_prefix = PLANT_CODE.upper() + u"-"
    for item in project_items:
        for anc in item.get(u"_ancestor_codes_list", []):
            nc = _norm_code(anc)
            if not nc.startswith(plant_prefix):
                continue
            if registry.get(nc):
                continue
            hits = [c for c in containers if _container_contains_ancestor(c, anc)]
            if len(hits) != 1:
                continue
            c = hits[0]
            eid = _u(c.get(u"element_id"))
            if not eid:
                continue
            cap = _count_free_slots_05_80_source(c.get(u"_row", {}))
            if cap < 1:
                continue
            rec = {
                u"cluster_key": eid,
                u"eids": [eid],
                u"cap_05_80": cap,
                u"path": c.get(u"btz_path_detectado") or u"",
            }
            if not any(x[u"cluster_key"] == rec[u"cluster_key"] for x in registry[nc]):
                registry[nc].append(rec)


def _demand_by_cluster_key(out_rows):
    demand = defaultdict(int)
    for row in out_rows:
        if _u(row.get(u"estado_match")) not in _CONTAINER_ASSIGN_ESTADOS:
            continue
        key = _cluster_key_from_prep_row(row)
        if key:
            demand[key] += 1
    return demand


def _resolve_ambiguo_row_via_registry(item, registry, demand_by_key):
    found_key = None
    found_rec = None
    found_anc = None
    for anc in item.get(u"_ancestor_codes_list", []):
        nc = _norm_code(anc)
        recs = registry.get(nc) or []
        if not recs:
            continue
        sub = set(r[u"cluster_key"] for r in recs)
        if len(sub) > 1:
            return None
        rec = recs[0]
        ck = rec[u"cluster_key"]
        if found_key is None:
            found_key, found_rec, found_anc = ck, rec, anc
        elif ck != found_key:
            return None
    if found_rec is None:
        return None
    if demand_by_key.get(found_key, 0) >= found_rec[u"cap_05_80"]:
        return None
    return found_anc, found_rec


def _containers_list_for_registry_rec(rec, containers_by_id):
    out = []
    for eid in rec[u"eids"]:
        c = containers_by_id.get(eid)
        if not c:
            return None
        out.append(c)
    return out


def _prep_row_from_registry_resolution(item, anc_code, rec, containers_by_id):
    cluster_cs = _containers_list_for_registry_rec(rec, containers_by_id)
    if not cluster_cs:
        return None
    anc_norm = _norm_code(anc_code)
    master = _mcr.pick_canonical_master(cluster_cs, anc_norm)
    master[u"cantidad_codigos_project_asignados_sugeridos"] += 1
    cluster_csv = _mcr.cluster_element_ids_csv(cluster_cs)
    cands = u" || ".join(
        u"{0}:190:{1}".format(x.get(u"element_id"), x.get(u"btz_path_detectado") or u"")
        for x in cluster_cs[:8]
    )
    score_info = {
        u"score": 190,
        u"second_score": 0,
        u"diff": 190,
        u"criteria": u"post_ambiguo_registry_ancestro_capacidad",
        u"candidates": cands,
        u"ancestor": anc_norm,
    }
    obs = (
        u"Reclasificado desde ambiguo_real: ancestro Project {0} mapea a un único cluster Revit "
        u"con capacidad BTZ_05-80 (sin competencia de otro ancestro)."
    ).format(anc_norm)
    out = _output_from_container(
        item,
        master,
        u"contenedor_logico_duplicado_distributed",
        obs,
        score_info,
    )
    out[u"tipo_asociacion"] = u"contenedor_por_registry_capacidad"
    out[u"tipo_resolucion"] = u"ambiguo_absorbido_cluster_capacidad"
    out[u"ancestro_usado"] = anc_norm
    out[u"cluster_element_ids"] = cluster_csv
    out[u"cluster_mode"] = u"distributed"
    out[u"element_id_destino"] = u""
    out[u"motivo"] = u"unico_ancestro_mapea_cluster_sin_competencia"
    return out


def _ingest_soft_cluster_from_ambiguo_ancestor_rows(out_rows, containers_by_id, registry):
    """Si el ancestro quedó ambiguo por paths incompatibles pero hay varios element_id, úsalo como cluster de capacidad
    solo si aún no hay entrada estricta para ese ancestro (evita competir con clusters ya validados)."""
    plant_prefix = PLANT_CODE.upper() + u"-"
    for row in out_rows:
        if _u(row.get(u"estado_match")) != u"ambiguo_real":
            continue
        if _u(row.get(u"tipo_resolucion")) != u"ancestro_multi_sin_cluster_logico":
            continue
        anc_raw = row.get(u"ancestro_usado")
        nc = _norm_code(anc_raw)
        if not nc.startswith(plant_prefix):
            continue
        if registry.get(nc):
            continue
        csv = _u(row.get(u"cluster_element_ids"))
        if u";" not in csv:
            continue
        eids = [_u(x.strip()) for x in csv.split(u";") if x.strip()]
        if len(eids) < 2:
            continue
        total_cap = 0
        for eid in eids:
            cw = containers_by_id.get(eid)
            if not cw:
                total_cap = -1
                break
            total_cap += _count_free_slots_05_80_source(cw.get(u"_row", {}))
        if total_cap < 1:
            continue
        rec = {
            u"cluster_key": csv,
            u"eids": list(eids),
            u"cap_05_80": total_cap,
            u"path": _u(row.get(u"contenedor_sugerido_path")) or u"",
        }
        lst = registry[nc]
        if not any(x[u"cluster_key"] == rec[u"cluster_key"] for x in lst):
            lst.append(rec)


def _reclassify_ambiguo_real_via_ancestor_registry(
    out_rows, project_items, containers, counts, containers_by_id
):
    if not EXTENDED_CLUSTER_STATES:
        return out_rows
    registry = _build_ancestor_cluster_registry(out_rows, containers_by_id)
    _ingest_soft_cluster_from_ambiguo_ancestor_rows(out_rows, containers_by_id, registry)
    _enrich_registry_singleton_ancestors(project_items, containers, registry)
    ambig_codes = set()
    for row in out_rows:
        if _u(row.get(u"estado_match")) == u"ambiguo_real":
            ambig_codes.add(_norm_code(row.get(u"codigo_project")))
    if not ambig_codes:
        return out_rows
    demand = _demand_by_cluster_key(out_rows)
    resolved = {}
    for item in project_items:
        code = _norm_code(item[u"codigo_project"])
        if code not in ambig_codes:
            continue
        pair = _resolve_ambiguo_row_via_registry(item, registry, demand)
        if not pair:
            continue
        anc, rec = pair
        new_row = _prep_row_from_registry_resolution(item, anc, rec, containers_by_id)
        if not new_row:
            continue
        resolved[code] = new_row
        ck = rec[u"cluster_key"]
        demand[ck] = demand.get(ck, 0) + 1
    if not resolved:
        return out_rows
    counts[u"ambiguo_real"] -= len(resolved)
    counts[u"contenedor_logico_duplicado_distributed"] += len(resolved)
    counts[u"contenedor_logico_duplicado"] += len(resolved)
    counts[u"asignable_a_contenedor"] += len(resolved)
    counts[u"_resolved_by_ancestor_cluster_registry"] += len(resolved)
    consumed = set()
    out_next = []
    for row in out_rows:
        code = _norm_code(row.get(u"codigo_project"))
        est = _u(row.get(u"estado_match"))
        if code in resolved and est == u"ambiguo_real":
            if code not in consumed:
                out_next.append(resolved[code])
                consumed.add(code)
            continue
        out_next.append(row)
    return out_next


def _cluster_record_from_revit_hits(hits, containers_by_id):
    seen = set()
    hit_by_eid = OrderedDict()
    for c in hits:
        eid = _u(c.get(u"element_id"))
        if not eid or eid in seen:
            continue
        seen.add(eid)
        hit_by_eid[eid] = c
    try:
        eids = [_u(n) for n in sorted(set(int(x) for x in hit_by_eid.keys()))]
    except Exception:
        eids = sorted(set(hit_by_eid.keys()))
    if not eids:
        return None
    total_cap = 0
    first_path = u""
    for eid in eids:
        cw = containers_by_id.get(eid) or hit_by_eid.get(eid)
        if not cw:
            return None
        total_cap += _count_free_slots_05_80_source(cw.get(u"_row", {}))
        if not first_path:
            first_path = _u(cw.get(u"btz_path_detectado"))
    if total_cap < 1:
        return None
    return {
        u"cluster_key": u";".join(eids),
        u"eids": eids,
        u"cap_05_80": total_cap,
        u"path": first_path,
    }


def _pick_unique_cluster_aggressive_ancestor_chain(item, containers, demand_by_key, containers_by_id):
    """Pase agresivo: sin firma BTZ_01–04; todos los contenedores que contienen el código ancestro.
    Válido solo si todos los ancestros con hits en Revit comparten el mismo cluster_key."""
    plant_prefix = PLANT_CODE.upper() + u"-"
    chain_hits = []
    for anc in item.get(u"_ancestor_codes_list", []):
        norm = _norm_code(anc)
        if not norm.startswith(plant_prefix):
            continue
        hits = [c for c in containers if _container_contains_ancestor(c, norm)]
        if not hits:
            continue
        rec = _cluster_record_from_revit_hits(hits, containers_by_id)
        if not rec:
            continue
        ck = rec[u"cluster_key"]
        if demand_by_key.get(ck, 0) >= rec[u"cap_05_80"]:
            continue
        chain_hits.append((anc, ck, rec))
    if not chain_hits:
        return None
    if len(set(x[1] for x in chain_hits)) > 1:
        return None
    anc_pick, _ck, rec = chain_hits[0]
    return anc_pick, rec


def _prep_row_aggressive_ancestor_superior(item, anc_code, rec, containers_by_id):
    cluster_cs = _containers_list_for_registry_rec(rec, containers_by_id)
    if not cluster_cs:
        return None
    anc_norm = _norm_code(anc_code)
    master = _mcr.pick_canonical_master(cluster_cs, anc_norm)
    master[u"cantidad_codigos_project_asignados_sugeridos"] += 1
    cluster_csv = _mcr.cluster_element_ids_csv(cluster_cs)
    cands = u" || ".join(
        u"{0}:185:{1}".format(x.get(u"element_id"), x.get(u"btz_path_detectado") or u"")
        for x in cluster_cs[:8]
    )
    score_info = {
        u"score": 185,
        u"second_score": 0,
        u"diff": 185,
        u"criteria": u"pase3_fallback_ancestro_superior_sin_firma_btz",
        u"candidates": cands,
        u"ancestor": anc_norm,
    }
    obs = (
        u"Pase agresivo TE/PP: ancestro {0} (ruta Project) → único cluster Revit por contención de código, "
        u"con capacidad BTZ_05-80; sin otro cluster competidor en la cadena de ancestros."
    ).format(anc_norm)
    out = _output_from_container(
        item,
        master,
        u"contenedor_logico_duplicado_distributed",
        obs,
        score_info,
    )
    out[u"tipo_asociacion"] = u"contenedor_por_fallback_ancestro_superior"
    out[u"tipo_resolucion"] = u"ambiguo_absorbido_por_ancestro_superior"
    out[u"ancestro_usado"] = anc_norm
    out[u"cluster_element_ids"] = cluster_csv
    out[u"cluster_mode"] = u"distributed"
    out[u"element_id_destino"] = u""
    out[u"motivo"] = u"cadena_ancestros_un_solo_cluster_posible"
    return out


def _reclassify_ambiguo_aggressive_ancestor_fallback(
    out_rows, project_items, containers, counts, containers_by_id
):
    if not EXTENDED_CLUSTER_STATES:
        return out_rows
    ambig_codes = set()
    for row in out_rows:
        if _u(row.get(u"estado_match")) == u"ambiguo_real":
            ambig_codes.add(_norm_code(row.get(u"codigo_project")))
    if not ambig_codes:
        return out_rows
    demand = _demand_by_cluster_key(out_rows)
    resolved = {}
    for item in project_items:
        code = _norm_code(item[u"codigo_project"])
        if code not in ambig_codes:
            continue
        pair = _pick_unique_cluster_aggressive_ancestor_chain(
            item, containers, demand, containers_by_id
        )
        if not pair:
            continue
        anc, rec = pair
        new_row = _prep_row_aggressive_ancestor_superior(item, anc, rec, containers_by_id)
        if not new_row:
            continue
        resolved[code] = new_row
        ck = rec[u"cluster_key"]
        demand[ck] = demand.get(ck, 0) + 1
    if not resolved:
        return out_rows
    counts[u"ambiguo_real"] -= len(resolved)
    counts[u"contenedor_logico_duplicado_distributed"] += len(resolved)
    counts[u"contenedor_logico_duplicado"] += len(resolved)
    counts[u"asignable_a_contenedor"] += len(resolved)
    counts[u"_resolved_by_aggressive_ancestor_superior"] += len(resolved)
    consumed = set()
    out_next = []
    for row in out_rows:
        code = _norm_code(row.get(u"codigo_project"))
        est = _u(row.get(u"estado_match"))
        if code in resolved and est == u"ambiguo_real":
            if code not in consumed:
                out_next.append(resolved[code])
                consumed.add(code)
            continue
        out_next.append(row)
    return out_next


def _container_row_has_plant(container_dict, plant_upper):
    hay = _u(container_dict.get(u"_haystack", u""))
    if not hay:
        hay = _container_haystack(container_dict.get(u"_row", {}))
    return _u(plant_upper).upper() in hay.upper()


def _primer_ancestro_same_outline_level_cluster_conflict(item, containers, containers_by_id):
    """Dos códigos ancestros con el mismo OutlineLevel en Project producen clusters distintos → competencia."""
    codes = item.get(u"_ancestor_codes_list", [])
    levels = item.get(u"_ancestor_outline_levels_list", [])
    if not levels or len(levels) != len(codes):
        return False
    plant_pref = PLANT_CODE.upper() + u"-"
    plant_hay = PLANT_CODE.upper()
    by_lvl = defaultdict(set)
    for idx, anc in enumerate(codes):
        norm = _norm_code(anc)
        if not norm.startswith(plant_pref):
            continue
        hits = []
        for ctr in containers:
            if not _container_contains_ancestor(ctr, norm):
                continue
            if not _container_row_has_plant(ctr, plant_hay):
                continue
            hits.append(ctr)
        if not hits:
            continue
        rec = _cluster_record_from_revit_hits(hits, containers_by_id)
        if not rec:
            continue
        lvl = _u(levels[idx])
        if not lvl:
            continue
        by_lvl[lvl].add(rec[u"cluster_key"])
    for _lvl, cks in by_lvl.items():
        if len(cks) > 1:
            return True
    return False


def _pick_first_ancestor_with_cluster_primer_valido(
    item, containers, demand_by_key, containers_by_id
):
    """Pase 4 relajado: primer ancestro con prefijo planta; unión de hits; varios btz_path permitidos.
    Cada hit debe contener el ancestro y la planta en el modelo."""
    plant_pref = PLANT_CODE.upper() + u"-"
    plant_hay = PLANT_CODE.upper()
    for anc in item.get(u"_ancestor_codes_list", []):
        norm = _norm_code(anc)
        if not norm.startswith(plant_pref):
            continue
        hits = []
        for ctr in containers:
            if not _container_contains_ancestor(ctr, norm):
                continue
            if not _container_row_has_plant(ctr, plant_hay):
                continue
            hits.append(ctr)
        if not hits:
            continue
        rec = _cluster_record_from_revit_hits(hits, containers_by_id)
        if not rec:
            continue
        ck = rec[u"cluster_key"]
        if demand_by_key.get(ck, 0) >= rec[u"cap_05_80"]:
            continue
        return anc, rec
    return None


def _prep_row_primer_ancestro_valido(item, anc_code, rec, containers_by_id):
    cluster_cs = _containers_list_for_registry_rec(rec, containers_by_id)
    if not cluster_cs:
        return None
    anc_norm = _norm_code(anc_code)
    master = _mcr.pick_canonical_master(cluster_cs, anc_norm)
    master[u"cantidad_codigos_project_asignados_sugeridos"] += 1
    cluster_csv = _mcr.cluster_element_ids_csv(cluster_cs)
    cands = u" || ".join(
        u"{0}:180:{1}".format(x.get(u"element_id"), x.get(u"btz_path_detectado") or u"")
        for x in cluster_cs[:8]
    )
    score_info = {
        u"score": 180,
        u"second_score": 0,
        u"diff": 180,
        u"criteria": u"pase4_primer_ancestro_relajado_capacidad_planta_multipath",
        u"candidates": cands,
        u"ancestor": anc_norm,
    }
    obs = (
        u"Pase 4 relajado TE/PP: primer ancestro {0} en Project; unión de todos los contenedores Revit que "
        u"contienen ese código (paths BTZ pueden diferir); planta coherente en cada hit; capacidad BTZ_05-80."
    ).format(anc_norm)
    out = _output_from_container(
        item,
        master,
        u"contenedor_logico_duplicado_distributed",
        obs,
        score_info,
    )
    out[u"tipo_asociacion"] = u"contenedor_por_primer_ancestro_valido"
    out[u"tipo_resolucion"] = u"ambiguo_absorbido_por_primer_ancestro_valido"
    out[u"ancestro_usado"] = anc_norm
    out[u"cluster_element_ids"] = cluster_csv
    out[u"cluster_mode"] = u"distributed"
    out[u"element_id_destino"] = u""
    out[u"motivo"] = u"primer_ancestro_relajado_multipath_misma_planta"
    return out


def _reclassify_ambiguo_primer_ancestro_valido(
    out_rows, project_items, containers, counts, containers_by_id
):
    if not EXTENDED_CLUSTER_STATES:
        return out_rows
    ambig_codes = set()
    for row in out_rows:
        if _u(row.get(u"estado_match")) == u"ambiguo_real":
            ambig_codes.add(_norm_code(row.get(u"codigo_project")))
    if not ambig_codes:
        return out_rows
    demand = _demand_by_cluster_key(out_rows)
    resolved = {}
    for item in project_items:
        code = _norm_code(item[u"codigo_project"])
        if code not in ambig_codes:
            continue
        if _primer_ancestro_same_outline_level_cluster_conflict(item, containers, containers_by_id):
            continue
        pair = _pick_first_ancestor_with_cluster_primer_valido(
            item, containers, demand, containers_by_id
        )
        if not pair:
            continue
        anc, rec = pair
        new_row = _prep_row_primer_ancestro_valido(item, anc, rec, containers_by_id)
        if not new_row:
            continue
        resolved[code] = new_row
        ck = rec[u"cluster_key"]
        demand[ck] = demand.get(ck, 0) + 1
    if not resolved:
        return out_rows
    counts[u"ambiguo_real"] -= len(resolved)
    counts[u"contenedor_logico_duplicado_distributed"] += len(resolved)
    counts[u"contenedor_logico_duplicado"] += len(resolved)
    counts[u"asignable_a_contenedor"] += len(resolved)
    counts[u"_resolved_by_primer_ancestro_valido_relajado"] += len(resolved)
    consumed = set()
    out_next = []
    for row in out_rows:
        code = _norm_code(row.get(u"codigo_project"))
        est = _u(row.get(u"estado_match"))
        if code in resolved and est == u"ambiguo_real":
            if code not in consumed:
                out_next.append(resolved[code])
                consumed.add(code)
            continue
        out_next.append(row)
    return out_next


def compare(project_items, revit_rows, containers):
    index = build_revit_code_index(revit_rows)
    global_codes = _build_global_codes_in_revit(revit_rows)
    plant_prefix = PLANT_CODE.upper() + u"-"
    out_rows = []
    counts = {
        u"match_elemento_puntual": 0,
        u"match_directo": 0,
        u"duplicado": 0,
        u"ambiguo_real": 0,
        u"ya_existente_en_btz": 0,
        u"asignable_a_contenedor": 0,
        u"contenedor_unico": 0,
        u"contenedor_logico_duplicado": 0,
        u"contenedor_logico_duplicado_canonical": 0,
        u"contenedor_logico_duplicado_distributed": 0,
        u"contenedor_duplicado": 0,
        u"sin_contenedor": 0,
        u"_score_diffs": [],
        u"_resolved_by_ancestor": 0,
        u"_resolved_by_scoring": 0,
        u"_resolved_by_punctual_multi_cluster": 0,
        u"_resolved_by_ancestor_cluster_registry": 0,
        u"_resolved_by_aggressive_ancestor_superior": 0,
        u"_resolved_by_primer_ancestro_valido": 0,
        u"_resolved_by_primer_ancestro_valido_relajado": 0,
        u"_duplicate_details": [],
    }

    containers_by_eid = {
        _u(c.get(u"element_id")): c for c in containers if c.get(u"element_id")
    }

    for item in project_items:
        code = item[u"codigo_project"]
        code_norm = _norm_code(code)
        hits_by_element = index.get(code, {})
        hits = list(hits_by_element.values())

        project_dup_note = u""
        if item.get(u"_duplicate_project_rows", 0) > 1:
            project_dup_note = u"Código repetido en Project {0} veces. ".format(
                item[u"_duplicate_project_rows"]
            )

        if (
            EXTENDED_CLUSTER_STATES
            and not hits
            and code_norm in global_codes
            and code_norm.startswith(plant_prefix)
        ):
            counts[u"ya_existente_en_btz"] += 1
            br = _blank_output(
                item,
                u"ya_existente_en_btz",
                project_dup_note + u"Código ya presente en BTZ del export Revit.",
                tipo_asociacion=u"codigo_ya_modelo",
            )
            br[u"tipo_resolucion"] = u"absorbido_por_btz_existente"
            br[u"motivo"] = u"codigo_en_slots_sin_match_puntual"
            out_rows.append(br)
            continue

        if len(hits) == 1:
            if EXTENDED_CLUSTER_STATES:
                counts[u"match_directo"] += 1
                estado_hit = u"match_directo"
            else:
                counts[u"match_elemento_puntual"] += 1
                estado_hit = u"match_elemento_puntual"
            hit = hits[0]
            o = _output_from_revit(
                item,
                hit[u"row"],
                estado_hit,
                u";".join(hit[u"params"]),
                project_dup_note + u"Coincidencia exacta única con elemento Revit.",
                u"elemento_puntual",
            )
            if EXTENDED_CLUSTER_STATES:
                o[u"tipo_resolucion"] = u"match_directo"
                o[u"motivo"] = u"match_puntual_unico"
            out_rows.append(o)
            continue

        if len(hits) > 1:
            if EXTENDED_CLUSTER_STATES:
                hits_containers = _containers_for_punctual_hits(hits, containers_by_eid)
                cluster_pc = None
                if hits_containers and len(hits_containers) == len(hits):
                    cluster_pc = _mcr.logical_cluster_from_punctual_duplicate_hits(
                        code_norm, hits_containers, PLANT_CODE
                    )
                if cluster_pc and len(cluster_pc) > 1:
                    counts[u"contenedor_logico_duplicado"] += 1
                    counts[u"asignable_a_contenedor"] += 1
                    counts[u"_resolved_by_punctual_multi_cluster"] += 1
                    mode = _u(CLUSTER_MODE).lower()
                    if mode == u"canonical":
                        counts[u"contenedor_logico_duplicado_canonical"] += 1
                    else:
                        counts[u"contenedor_logico_duplicado_distributed"] += 1
                    master = _mcr.pick_canonical_master(cluster_pc, code_norm)
                    master[u"cantidad_codigos_project_asignados_sugeridos"] += 1
                    cluster_csv = _mcr.cluster_element_ids_csv(cluster_pc)
                    if mode == u"canonical":
                        est_f = u"contenedor_logico_duplicado_canonical"
                    else:
                        est_f = u"contenedor_logico_duplicado_distributed"
                    candidates = u" || ".join(
                        u"{0}:200:{1}".format(
                            x.get(u"element_id"), x.get(u"btz_path_detectado") or u""
                        )
                        for x in cluster_pc[:8]
                    )
                    score_info = {
                        u"score": 200,
                        u"second_score": 200,
                        u"diff": 0,
                        u"criteria": u"match_puntual_multi_id_cluster_logico",
                        u"candidates": candidates,
                        u"ancestor": code_norm,
                    }
                    obs = project_dup_note + u"Mismo código en {0} elementos Revit; cluster lógico (no ambigüedad real).".format(
                        len(cluster_pc)
                    )
                    out_rows.append(_output_from_container(item, master, est_f, obs, score_info))
                    out_rows[-1][u"tipo_asociacion"] = u"contenedor_por_match_puntual_multi"
                    out_rows[-1][u"tipo_resolucion"] = u"ambiguo_falso_por_contenedor_duplicado"
                    out_rows[-1][u"ancestro_usado"] = code_norm
                    out_rows[-1][u"cluster_element_ids"] = cluster_csv
                    out_rows[-1][u"cluster_mode"] = CLUSTER_MODE
                    mid = _u(master.get(u"element_id"))
                    if mode == u"canonical":
                        out_rows[-1][u"element_id_destino"] = mid
                        out_rows[-1][u"motivo"] = u"mismo_codigo_varios_element_ids_cluster_canonical"
                    else:
                        out_rows[-1][u"element_id_destino"] = u""
                        out_rows[-1][u"motivo"] = u"mismo_codigo_varios_element_ids_cluster_distributed"
                    continue

                counts[u"ya_existente_en_btz"] += 1
                eid_parts = []
                for hit in hits:
                    eid = _u(hit[u"row"].get(u"element_id"))
                    if eid and eid not in eid_parts:
                        eid_parts.append(eid)
                try:
                    eid_parts = [_u(x) for x in sorted(set(int(x) for x in eid_parts))]
                except Exception:
                    eid_parts = sorted(set(eid_parts))
                cluster_csv = u";".join(eid_parts)
                obs = project_dup_note + (
                    u"Código ya existe en {0} elementos Revit; colapsado a un cluster (no ambigüedad).".format(
                        len(eid_parts)
                    )
                )
                br = _blank_output(
                    item,
                    u"ya_existente_en_btz",
                    obs,
                    u"elemento_puntual",
                    tipo_asociacion=u"codigo_ya_modelo_multi_id",
                )
                br[u"tipo_resolucion"] = u"codigo_existente_multi_id"
                br[u"cluster_element_ids"] = cluster_csv
                br[u"motivo"] = u"codigo_existente_multi_id_colapsado"
                if eid_parts:
                    first_hit = next(
                        (h for h in hits if _u(h[u"row"].get(u"element_id")) == eid_parts[0]),
                        hits[0],
                    )
                    row0 = first_hit[u"row"]
                    br[u"element_id_revit"] = eid_parts[0]
                    br[u"unique_id_revit"] = _u(row0.get(u"unique_id"))
                    br[u"category"] = _u(row0.get(u"category"))
                    br[u"family"] = _u(row0.get(u"family"))
                    br[u"type"] = _u(row0.get(u"type"))
                    br[u"name"] = _u(row0.get(u"name"))
                    br[u"btz_numero_activo"] = _u(row0.get(u"btz_numero_activo"))
                    br[u"btz_path_actual"] = _u(row0.get(u"btz_path_detectado"))
                    for col in BTZ_DESC_COLS:
                        br[col] = _u(row0.get(col))
                out_rows.append(br)
                continue

            estado_m = u"ambiguo_real" if EXTENDED_CLUSTER_STATES else u"duplicado"
            if EXTENDED_CLUSTER_STATES:
                counts[u"ambiguo_real"] += 1
            else:
                counts[u"duplicado"] += 1
            obs = project_dup_note + u"{0} elementos Revit contienen el código exacto.".format(len(hits))
            for hit in hits:
                o = _output_from_revit(
                    item,
                    hit[u"row"],
                    estado_m,
                    u";".join(hit[u"params"]),
                    obs,
                    u"elemento_puntual",
                )
                if EXTENDED_CLUSTER_STATES:
                    o[u"tipo_resolucion"] = u"elemento_puntual_multi_id"
                    o[u"motivo"] = u"varios_element_ids_revit_mismo_codigo"
                out_rows.append(o)
            continue

        ancestor_used, ancestor_hits = find_container_by_project_ancestor(item, containers)
        if len(ancestor_hits) == 1:
            counts[u"asignable_a_contenedor"] += 1
            if EXTENDED_CLUSTER_STATES:
                counts[u"contenedor_unico"] += 1
            counts[u"_resolved_by_ancestor"] += 1
            container = ancestor_hits[0]
            container[u"cantidad_codigos_project_asignados_sugeridos"] += 1
            score_info = {
                u"score": 200,
                u"second_score": 0,
                u"diff": 200,
                u"criteria": u"ancestro_project_exacto",
                u"candidates": u"{0}:200:{1}".format(
                    container.get(u"element_id"),
                    container.get(u"btz_path_detectado") or u"(sin path)",
                ),
                u"ancestor": ancestor_used,
            }
            obs = project_dup_note + u"Sin match puntual; contenedor único por ancestro Project {0}.".format(
                ancestor_used
            )
            out_estado = u"contenedor_unico" if EXTENDED_CLUSTER_STATES else u"asignable_a_contenedor"
            out_rows.append(
                _output_from_container(
                    item,
                    container,
                    out_estado,
                    obs,
                    score_info,
                )
            )
            out_rows[-1][u"tipo_asociacion"] = u"contenedor_por_ancestro_project"
            if EXTENDED_CLUSTER_STATES:
                out_rows[-1][u"tipo_resolucion"] = u"contenedor_unico_ancestro"
                out_rows[-1][u"ancestro_usado"] = ancestor_used
                out_rows[-1][u"cluster_element_ids"] = _u(container.get(u"element_id"))
                out_rows[-1][u"element_id_destino"] = _u(container.get(u"element_id"))
                out_rows[-1][u"motivo"] = u"un_elemento_revit_para_ancestro"
            continue

        if len(ancestor_hits) > 1:
            if EXTENDED_CLUSTER_STATES:
                cluster = _mcr.logical_cluster_from_ancestor_hits(
                    ancestor_used, ancestor_hits, PLANT_CODE
                )
                if cluster:
                    counts[u"contenedor_logico_duplicado"] += 1
                    counts[u"asignable_a_contenedor"] += 1
                    counts[u"_resolved_by_ancestor"] += 1
                    mode = _u(CLUSTER_MODE).lower()
                    if mode == u"canonical":
                        counts[u"contenedor_logico_duplicado_canonical"] += 1
                    else:
                        counts[u"contenedor_logico_duplicado_distributed"] += 1
                    master = _mcr.pick_canonical_master(cluster, ancestor_used)
                    master[u"cantidad_codigos_project_asignados_sugeridos"] += 1
                    cluster_csv = _mcr.cluster_element_ids_csv(cluster)
                    if mode == u"canonical":
                        est_f = u"contenedor_logico_duplicado_canonical"
                    else:
                        est_f = u"contenedor_logico_duplicado_distributed"
                    candidates = u" || ".join(
                        u"{0}:200:{1}".format(
                            x.get(u"element_id"), x.get(u"btz_path_detectado") or u""
                        )
                        for x in cluster[:8]
                    )
                    score_info = {
                        u"score": 200,
                        u"second_score": 200,
                        u"diff": 0,
                        u"criteria": u"cluster_logico_mismo_sector",
                        u"candidates": candidates,
                        u"ancestor": ancestor_used,
                    }
                    obs = project_dup_note + u"Cluster lógico: ancestro {0} en {1} elementos Revit equivalentes.".format(
                        ancestor_used, len(cluster)
                    )
                    out_rows.append(
                        _output_from_container(item, master, est_f, obs, score_info)
                    )
                    out_rows[-1][u"tipo_asociacion"] = u"contenedor_por_ancestro_project"
                    out_rows[-1][u"tipo_resolucion"] = u"ambiguo_falso_por_contenedor_duplicado"
                    out_rows[-1][u"ancestro_usado"] = ancestor_used
                    out_rows[-1][u"cluster_element_ids"] = cluster_csv
                    out_rows[-1][u"cluster_mode"] = CLUSTER_MODE
                    mid = _u(master.get(u"element_id"))
                    if mode == u"canonical":
                        out_rows[-1][u"element_id_destino"] = mid
                        out_rows[-1][u"motivo"] = u"canonical_master_elegido"
                    else:
                        out_rows[-1][u"element_id_destino"] = u""
                        out_rows[-1][u"motivo"] = u"distribucion_round_robin_en_preparar_aplicar"
                    continue

            counts[u"contenedor_duplicado"] += 1
            if EXTENDED_CLUSTER_STATES:
                counts[u"ambiguo_real"] += 1
            candidates = u" || ".join(
                u"{0}:200:{1}".format(
                    c.get(u"element_id"), c.get(u"btz_path_detectado") or u"(sin path)"
                )
                for c in ancestor_hits[:8]
            )
            if len(ancestor_hits) > 8:
                candidates += u" || ... +{0}".format(len(ancestor_hits) - 8)
            counts[u"_duplicate_details"].append(
                {
                    u"codigo": code,
                    u"best_score": 200,
                    u"second_score": 200,
                    u"diff": 0,
                    u"candidates": candidates,
                }
            )
            container = ancestor_hits[0]
            score_info = {
                u"score": 200,
                u"second_score": 200,
                u"diff": 0,
                u"criteria": u"ancestro_project_exacto_duplicado",
                u"candidates": candidates,
                u"ancestor": ancestor_used,
            }
            obs = project_dup_note + u"Ancestro Project {0} en contenedores Revit no equivalentes.".format(
                ancestor_used
            )
            est_fail = u"ambiguo_real" if EXTENDED_CLUSTER_STATES else u"contenedor_duplicado"
            out_rows.append(
                _output_from_container(
                    item,
                    container,
                    est_fail,
                    obs,
                    score_info,
                )
            )
            out_rows[-1][u"tipo_asociacion"] = u"contenedor_por_ancestro_project"
            if EXTENDED_CLUSTER_STATES:
                out_rows[-1][u"tipo_resolucion"] = u"ancestro_multi_sin_cluster_logico"
                out_rows[-1][u"ancestro_usado"] = ancestor_used
                out_rows[-1][u"cluster_element_ids"] = _mcr.cluster_element_ids_csv(ancestor_hits)
                out_rows[-1][u"motivo"] = u"paths_o_firma_btz_incompatibles"
            continue

        ranked = rank_container_candidates(code, containers)
        best = ranked[0] if ranked else None
        second = ranked[1] if len(ranked) > 1 else None
        best_score = best[u"score"] if best else 0
        second_score = second[u"score"] if second else 0
        diff = best_score - second_score
        score_info = {
            u"score": best_score,
            u"second_score": second_score,
            u"diff": diff,
            u"criteria": best[u"criteria"] if best else u"",
            u"candidates": _format_candidates(ranked),
        }

        if best and best_score >= 40 and diff >= 15:
            counts[u"asignable_a_contenedor"] += 1
            counts[u"_resolved_by_scoring"] += 1
            counts[u"_score_diffs"].append(diff)
            container = best[u"container"]
            container[u"cantidad_codigos_project_asignados_sugeridos"] += 1
            obs = project_dup_note + u"Sin match puntual; contenedor único por scoring (diferencia {0}).".format(
                diff
            )
            out_es = u"contenedor_unico" if EXTENDED_CLUSTER_STATES else u"asignable_a_contenedor"
            out_rows.append(
                _output_from_container(
                    item, container, out_es, obs, score_info
                )
            )
            out_rows[-1][u"tipo_asociacion"] = u"contenedor_por_scoring"
            if EXTENDED_CLUSTER_STATES:
                out_rows[-1][u"tipo_resolucion"] = u"scoring_claro"
                out_rows[-1][u"element_id_destino"] = _u(container.get(u"element_id"))
                out_rows[-1][u"cluster_element_ids"] = _u(container.get(u"element_id"))
                out_rows[-1][u"motivo"] = u"diff_scores_mayor_igual_15"
            continue

        if best and best_score >= 40:
            if EXTENDED_CLUSTER_STATES:
                counts[u"ambiguo_real"] += 1
                estado_amb = u"ambiguo_real"
                out_rows.append(
                    _output_from_container(
                        item,
                        best[u"container"],
                        estado_amb,
                        project_dup_note + u"Scoring ambiguo (diff<15): mejor={0}, segundo={1}.".format(
                            best_score, second_score
                        ),
                        score_info,
                    )
                )
                out_rows[-1][u"tipo_asociacion"] = u"contenedor_por_scoring"
                out_rows[-1][u"tipo_resolucion"] = u"ambiguo_real_scores"
                out_rows[-1][u"motivo"] = u"dos_contenedores_puntuacion_similar"
            else:
                counts[u"contenedor_duplicado"] += 1
                counts[u"_score_diffs"].append(diff)
                counts[u"_duplicate_details"].append(
                    {
                        u"codigo": code,
                        u"best_score": best_score,
                        u"second_score": second_score,
                        u"diff": diff,
                        u"candidates": _format_candidates(ranked, limit=5),
                    }
                )
                container = best[u"container"]
                obs = project_dup_note + u"Scoring ambiguo: mejor={0}, segundo={1}, diferencia={2}.".format(
                    best_score, second_score, diff
                )
                out_rows.append(
                    _output_from_container(
                        item,
                        container,
                        u"contenedor_duplicado",
                        obs,
                        score_info,
                    )
                )
            continue

        counts[u"sin_contenedor"] += 1
        out_rows.append(
            _blank_output(
                item,
                u"sin_contenedor",
                project_dup_note + u"Ningún contenedor supera puntaje mínimo 40.",
                tipo_asociacion=u"sin_asociacion",
            )
        )

    containers_by_id = {_u(c.get(u"element_id")): c for c in containers if c.get(u"element_id")}
    out_rows = _reclassify_ambiguo_real_via_ancestor_registry(
        out_rows, project_items, containers, counts, containers_by_id
    )
    out_rows = _reclassify_ambiguo_aggressive_ancestor_fallback(
        out_rows, project_items, containers, counts, containers_by_id
    )
    out_rows = _reclassify_ambiguo_primer_ancestro_valido(
        out_rows, project_items, containers, counts, containers_by_id
    )

    out_rows = _dedupe_out_rows_one_per_codigo_project(out_rows, project_items)
    out_rows = _force_ancestor_container_pass(out_rows, project_items, revit_rows, containers_by_id)
    _sync_row_based_counts(out_rows, counts, containers_by_id)

    child_totals = defaultdict(int)
    for row in out_rows:
        if _u(row.get(u"estado_match")) in _CONTAINER_ASSIGN_ESTADOS:
            key = _cluster_key_from_prep_row(row)
            if key:
                child_totals[key] += 1

    for row in out_rows:
        if _u(row.get(u"estado_match")) not in _CONTAINER_ASSIGN_ESTADOS:
            continue
        key = _cluster_key_from_prep_row(row)
        if not key:
            continue
        cap = _capacity_slots_05_80_for_prep_row(row, containers_by_id)
        assigned = child_totals.get(key, 0)
        row[u"requiere_split_por_slots"] = u"SI" if assigned > cap else u"NO"

    return out_rows, counts


def write_csv(path, rows):
    with codecs.open(path, u"w", encoding=u"utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=OUT_FIELDS, lineterminator=u"\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_containers_csv(path, containers):
    with codecs.open(path, u"w", encoding=u"utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=CONTAINER_FIELDS, lineterminator=u"\n")
        writer.writeheader()
        for c in containers:
            row = {}
            for field in CONTAINER_FIELDS:
                row[field] = c.get(field, u"")
            writer.writerow(row)


def _motivo_revision(estado):
    if estado == u"duplicado":
        return u"hay más de un elemento puntual posible"
    if estado == u"contenedor_duplicado":
        return u"hay más de un contenedor candidato"
    if estado == u"sin_contenedor":
        return u"no se encontró contenedor compatible"
    if estado == u"ambiguo_real":
        return u"ambigüedad real (varios candidatos)"
    if estado == u"ya_existente_en_btz":
        return u"código ya cargado en BTZ del modelo"
    if estado == u"omitido_por_slots":
        return u"omitido: capacidad BTZ_05-80 o demanda de cluster"
    return u""


def _dict_for_fields(row, fields):
    return {field: row.get(field, u"") for field in fields}


def write_rows_csv(path, fieldnames, rows):
    with codecs.open(path, u"w", encoding=u"utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, lineterminator=u"\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(_dict_for_fields(row, fieldnames))


def write_postprocess_outputs(out_rows, confirmado_path, revision_path, container_children_path):
    confirmados = []
    revision = []
    contenedor_hijos = []

    auto_ok = (
        u"match_elemento_puntual",
        u"match_directo",
        u"asignable_a_contenedor",
        u"contenedor_unico",
        u"contenedor_logico_duplicado_canonical",
        u"contenedor_logico_duplicado_distributed",
    )
    revision_estados = (
        u"duplicado",
        u"contenedor_duplicado",
        u"sin_contenedor",
        u"ambiguo_real",
        u"ya_existente_en_btz",
        u"omitido_por_slots",
    )

    for row in out_rows:
        estado = _u(row.get(u"estado_match"))
        if estado in auto_ok:
            r = dict(row)
            r[u"estado_confirmacion"] = u"confirmado_auto"
            confirmados.append(r)
        elif estado in revision_estados:
            r = dict(row)
            r[u"motivo_revision"] = _motivo_revision(estado)
            revision.append(r)

        if estado in (
            u"asignable_a_contenedor",
            u"contenedor_unico",
            u"contenedor_logico_duplicado_canonical",
            u"contenedor_logico_duplicado_distributed",
        ):
            contenedor_hijos.append(
                {
                    u"codigo_project": row.get(u"codigo_project", u""),
                    u"descripcion_project": row.get(u"descripcion_project", u""),
                    u"element_id_contenedor": row.get(u"contenedor_sugerido_element_id", u""),
                    u"unique_id_contenedor": row.get(u"contenedor_sugerido_unique_id", u""),
                    u"btz_path_contenedor": row.get(u"contenedor_sugerido_path", u""),
                    u"ancestro_project_usado": row.get(u"ancestro_project_usado", u""),
                    u"tipo_asociacion": row.get(u"tipo_asociacion", u""),
                    u"puntaje_contenedor": row.get(u"puntaje_contenedor", u""),
                    u"criterio_contenedor": row.get(u"criterio_contenedor", u""),
                    u"requiere_split_por_slots": row.get(u"requiere_split_por_slots", u""),
                }
            )

    write_rows_csv(confirmado_path, CONFIRMADO_AUTO_FIELDS, confirmados)
    write_rows_csv(revision_path, REVISION_FIELDS, revision)
    write_rows_csv(container_children_path, CONTAINER_CHILDREN_FIELDS, contenedor_hijos)

    return {
        u"total_confirmado_auto": len(confirmados),
        u"total_revision": len(revision),
        u"total_asociaciones_contenedor_hijos": len(contenedor_hijos),
    }


def _current_revit_row_for_application(prep_row, containers_by_id, containers_by_uid):
    eid = _u(prep_row.get(u"contenedor_sugerido_element_id")) or _u(prep_row.get(u"element_id_revit"))
    uid = _u(prep_row.get(u"contenedor_sugerido_unique_id")) or _u(prep_row.get(u"unique_id_revit"))
    container = containers_by_id.get(eid) or containers_by_uid.get(uid)
    if container:
        return container.get(u"_row", {})
    return prep_row


def _init_apply_element(eid, uid, source_row):
    row = {
        u"element_id": eid,
        u"unique_id": uid,
        u"btz_numero_activo": _u(source_row.get(u"btz_numero_activo")),
        u"estado_match": u"confirmado",
        u"estado_confirmacion": u"confirmado_auto",
        u"observacion": u"",
        u"limpiar_valores": u"NO",
        u"_observaciones": [],
        u"_modified": False,
    }
    for col in BTZ_DESC_COLS:
        row[col] = _u(source_row.get(col))
    return row


def _first_empty_slots(apply_row):
    return [col for col in BTZ_DESC_COLS if not _u(apply_row.get(col))]


def _cols_btz_05_80():
    return [u"btz_description_{:02d}".format(i) for i in range(5, 81)]


def _first_empty_slots_05_80(apply_row):
    return [col for col in _cols_btz_05_80() if not _u(apply_row.get(col))]


def _count_free_slots_05_80_source(source_row):
    return len([c for c in _cols_btz_05_80() if not _u(source_row.get(c))])


def _find_existing_code_slot(apply_row, code):
    code_norm = _norm_code(code)
    for col in BTZ_DESC_COLS:
        if _norm_code(apply_row.get(col)) == code_norm:
            return col
    return u""


def _find_existing_code_slot_05_80(apply_row, code):
    code_norm = _norm_code(code)
    for col in _cols_btz_05_80():
        if _norm_code(apply_row.get(col)) == code_norm:
            return col
    return u""


def _find_existing_code_slot_any(apply_row, code):
    slot = _find_existing_code_slot(apply_row, code)
    if slot:
        return slot
    return _find_existing_code_slot_05_80(apply_row, code)


def _copy_apply_csv(src, dst):
    with codecs.open(src, u"r", encoding=u"utf-8-sig") as fp:
        content = fp.read()
    with codecs.open(dst, u"w", encoding=u"utf-8-sig") as fp:
        fp.write(content)


def prepare_apply_confirmed_outputs(
    out_rows,
    containers,
    apply_ready_path,
    apply_path,
    final_children_path,
    omitted_path,
    apply_summary_path,
):
    containers_by_id = {_u(c.get(u"element_id")): c for c in containers if c.get(u"element_id")}
    containers_by_uid = {c.get(u"unique_id"): c for c in containers if c.get(u"unique_id")}

    _ESTADOS_PUNTUAL = frozenset((u"match_elemento_puntual", u"match_directo"))

    applicable = [
        r
        for r in out_rows
        if _u(r.get(u"estado_match")) in (_ESTADOS_PUNTUAL | _CONTAINER_ASSIGN_ESTADOS)
    ]
    point_rows = [r for r in applicable if _u(r.get(u"estado_match")) in _ESTADOS_PUNTUAL]
    container_rows = [
        r for r in applicable if _u(r.get(u"estado_match")) in _CONTAINER_ASSIGN_ESTADOS
    ]
    by_element = OrderedDict()
    final_children = []
    omitted_children = []

    container_child_counts = defaultdict(int)
    for r in container_rows:
        key = _cluster_key_from_prep_row(r)
        if key:
            container_child_counts[key] += 1

    initial_free_05 = {}
    rr_next = defaultdict(int)
    pp_writes_by_key = defaultdict(int)

    def _ensure_app(eid, uid, source_row):
        if not eid:
            return None
        if eid not in by_element:
            by_element[eid] = _init_apply_element(eid, uid, source_row)
            if eid not in initial_free_05:
                initial_free_05[eid] = _count_free_slots_05_80_source(source_row)
        return by_element[eid]

    def _pick_rr_eid(eids, rr_state_key):
        raw_eids = list(eids)
        if not raw_eids:
            return None, None
        start = rr_next[rr_state_key]
        n = len(raw_eids)
        for step in range(n):
            idx = (start + step) % n
            eid = raw_eids[idx]
            app = by_element.get(eid)
            if app and _first_empty_slots_05_80(app):
                rr_next[rr_state_key] = (idx + 1) % n
                return eid, app
        return None, None

    total_by_ancestor = 0
    total_by_scoring = 0
    total_loaded = 0
    total_external_only = 0

    for r in point_rows:
        eid = _u(r.get(u"element_id_revit"))
        uid = _u(r.get(u"unique_id_revit"))
        if not eid:
            continue
        source_row = _current_revit_row_for_application(r, containers_by_id, containers_by_uid)
        app = _ensure_app(eid, uid, source_row)
        if not app:
            continue
        code = _norm_code(r.get(u"codigo_project"))
        if code:
            app[u"btz_numero_activo"] = code
            app[u"_modified"] = True
        _lbl = _u(r.get(u"estado_match"))
        app[u"_observaciones"].append(
            u"{0} confirmado desde Project/Revit".format(_lbl or u"match_puntual")
        )

    for r in container_rows:
        tipo = _u(r.get(u"tipo_asociacion"))
        if tipo == u"contenedor_por_ancestro_project":
            total_by_ancestor += 1
        elif tipo == u"contenedor_por_ancestro_forzado":
            total_by_ancestor += 1
        elif tipo in (u"contenedor_por_scoring", u"contenedor"):
            total_by_scoring += 1

        est = _u(r.get(u"estado_match"))
        path = _u(r.get(u"contenedor_sugerido_path")) or _u(r.get(u"btz_path_actual"))
        ancestro_u = _u(r.get(u"ancestro_project_usado"))

        if est == u"contenedor_logico_duplicado_distributed":
            target_eids = _cluster_eid_list_from_row(r)
        elif est == u"contenedor_logico_duplicado_canonical":
            master_eid = _u(r.get(u"element_id_destino")) or _u(r.get(u"contenedor_sugerido_element_id"))
            target_eids = [master_eid] if master_eid else []
        else:
            eid0 = _u(r.get(u"contenedor_sugerido_element_id")) or _u(r.get(u"element_id_revit"))
            target_eids = [eid0] if eid0 else []

        target_eids = [e for e in target_eids if e]
        cluster_key_rr = u";".join(target_eids)
        pp_srv = _mcr.is_pp_srv_cluster_row(ancestro_u, path)
        pp_single = pp_srv and len(target_eids) == 1
        prep_cluster_key = _cluster_key_from_prep_row(r)
        assigned_cluster = container_child_counts.get(prep_cluster_key, 0)

        for eid in target_eids:
            uid = u""
            cwrap = containers_by_id.get(eid)
            if cwrap:
                uid = _u(cwrap.get(u"unique_id"))
            source_row = _current_revit_row_for_application(r, containers_by_id, containers_by_uid)
            if cwrap:
                source_row = cwrap.get(u"_row", source_row)
            _ensure_app(eid, uid, source_row)

        code = _norm_code(r.get(u"codigo_project"))
        desc = _u(r.get(u"descripcion_project"))

        initial_cap = sum(initial_free_05.get(eid, 0) for eid in target_eids)

        if not target_eids:
            final_children.append(
                {
                    u"codigo_project": code,
                    u"descripcion_project": desc,
                    u"element_id_contenedor": u"",
                    u"unique_id_contenedor": u"",
                    u"btz_path_contenedor": path,
                    u"tipo_asociacion": tipo,
                    u"ancestro_project_usado": ancestro_u,
                    u"estado_asociacion": u"omitido_por_slots",
                    u"escrito_en_btz_description": u"NO",
                    u"btz_description_slot_usado": u"",
                    u"motivo": u"sin_element_id_destino",
                }
            )
            total_external_only += 1
            continue

        existing_slot_any = None
        existing_eid = None
        for eid2 in target_eids:
            app2 = by_element.get(eid2)
            if not app2:
                continue
            slot = _find_existing_code_slot_any(app2, code)
            if slot:
                existing_slot_any = slot
                existing_eid = eid2
                break

        final_assoc = {
            u"codigo_project": code,
            u"descripcion_project": desc,
            u"element_id_contenedor": target_eids[0],
            u"unique_id_contenedor": _u(
                (containers_by_id.get(target_eids[0]) or {}).get(u"unique_id")
            ),
            u"btz_path_contenedor": path,
            u"tipo_asociacion": tipo,
            u"ancestro_project_usado": ancestro_u,
            u"estado_asociacion": u"",
            u"escrito_en_btz_description": u"",
            u"btz_description_slot_usado": u"",
            u"motivo": u"",
        }

        if existing_slot_any:
            final_assoc[u"estado_asociacion"] = u"asociado_a_contenedor"
            final_assoc[u"escrito_en_btz_description"] = u"SI"
            final_assoc[u"btz_description_slot_usado"] = existing_slot_any
            final_assoc[u"motivo"] = u"ya_existia_en_btz"
            final_assoc[u"element_id_contenedor"] = existing_eid or target_eids[0]
            cw = containers_by_id.get(final_assoc[u"element_id_contenedor"])
            if cw:
                final_assoc[u"unique_id_contenedor"] = _u(cw.get(u"unique_id"))
            total_loaded += 1
            app_ref = by_element.get(final_assoc[u"element_id_contenedor"])
            if app_ref:
                app_ref[u"_observaciones"].append(
                    u"hijo Project {0} ya existía en {1}".format(code, existing_slot_any)
                )
            final_children.append(final_assoc)
            continue

        pick_eid = None
        pick_app = None
        if est == u"contenedor_logico_duplicado_distributed":
            pick_eid, pick_app = _pick_rr_eid(target_eids, cluster_key_rr)
            if pick_eid is None:
                pick_eid = target_eids[0]
                pick_app = by_element.get(pick_eid)
        else:
            pick_eid = target_eids[0]
            pick_app = by_element.get(pick_eid)

        if pp_single and pick_eid:
            budget_base = min(_mcr.PP_SRV_CAP_SINGLE_ELEMENT, initial_free_05.get(pick_eid, 0))
            if pp_writes_by_key[prep_cluster_key] >= budget_base:
                pick_app = None

        if pick_app is None:
            motivo = u"omitido_por_slots"
            final_assoc[u"estado_asociacion"] = u"omitido_por_slots"
            final_assoc[u"escrito_en_btz_description"] = u"NO"
            final_assoc[u"btz_description_slot_usado"] = u""
            final_assoc[u"motivo"] = motivo
            total_external_only += 1
            omitted_children.append(
                {
                    u"element_id_contenedor": target_eids[0],
                    u"unique_id_contenedor": _u(
                        (containers_by_id.get(target_eids[0]) or {}).get(u"unique_id")
                    ),
                    u"btz_path_contenedor": path,
                    u"codigo_project": code,
                    u"descripcion_project": desc,
                    u"slots_libres": initial_cap,
                    u"cantidad_hijos_asignados": assigned_cluster,
                    u"motivo_omision": (
                        u"pp_srv_tope_76_un_elemento"
                        if pp_single
                        else u"sin_slots_05_80_cluster"
                    ),
                }
            )
            final_children.append(final_assoc)
            continue

        slots = _first_empty_slots_05_80(pick_app)
        if not slots:
            motivo = u"omitido_por_slots"
            final_assoc[u"estado_asociacion"] = u"omitido_por_slots"
            final_assoc[u"escrito_en_btz_description"] = u"NO"
            final_assoc[u"motivo"] = motivo
            total_external_only += 1
            omitted_children.append(
                {
                    u"element_id_contenedor": pick_eid,
                    u"unique_id_contenedor": _u(
                        (containers_by_id.get(pick_eid) or {}).get(u"unique_id")
                    ),
                    u"btz_path_contenedor": path,
                    u"codigo_project": code,
                    u"descripcion_project": desc,
                    u"slots_libres": initial_cap,
                    u"cantidad_hijos_asignados": assigned_cluster,
                    u"motivo_omision": motivo,
                }
            )
            final_children.append(final_assoc)
            continue

        slot = slots[0]
        pick_app[slot] = code
        pick_app[u"_modified"] = True
        final_assoc[u"element_id_contenedor"] = pick_eid
        cw = containers_by_id.get(pick_eid)
        if cw:
            final_assoc[u"unique_id_contenedor"] = _u(cw.get(u"unique_id"))
        if tipo == u"contenedor_por_ancestro_forzado":
            final_assoc[u"estado_asociacion"] = u"confirmado_force_ancestor_container"
        else:
            final_assoc[u"estado_asociacion"] = u"asociado_a_contenedor"
        final_assoc[u"escrito_en_btz_description"] = u"SI"
        final_assoc[u"btz_description_slot_usado"] = slot
        final_assoc[u"motivo"] = u"escrito_slot_05_80"
        total_loaded += 1
        if pp_single:
            pp_writes_by_key[prep_cluster_key] += 1
        pick_app[u"_observaciones"].append(
            u"hijo Project {0} escrito en {1} (element_id={2})".format(code, slot, pick_eid)
        )
        final_children.append(final_assoc)

    cap_by_cluster_key = {}
    for r in container_rows:
        pk = _cluster_key_from_prep_row(r)
        if pk and pk not in cap_by_cluster_key:
            cap_by_cluster_key[pk] = _capacity_slots_05_80_for_prep_row(r, containers_by_id)
    containers_over_slots = OrderedDict()
    for pk, cnt in container_child_counts.items():
        cap = cap_by_cluster_key.get(pk, 0)
        if cnt > cap:
            sample_row = next((x for x in container_rows if _cluster_key_from_prep_row(x) == pk), None)
            path_s = u""
            if sample_row:
                path_s = _u(sample_row.get(u"contenedor_sugerido_path")) or _u(
                    sample_row.get(u"btz_path_actual")
                )
            containers_over_slots[pk] = {
                u"element_id": pk,
                u"unique_id": u"",
                u"path": path_s,
                u"slots_libres": cap,
                u"cantidad_hijos": cnt,
            }

    apply_rows = []
    for eid, row in by_element.items():
        if not row.get(u"_modified"):
            continue
        out = {field: row.get(field, u"") for field in APPLY_FIELDS}
        out[u"observacion"] = u" | ".join(row.get(u"_observaciones", []))
        apply_rows.append(out)

    write_rows_csv(apply_ready_path, APPLY_FIELDS, apply_rows)
    _copy_apply_csv(apply_ready_path, apply_path)
    write_rows_csv(final_children_path, CONTAINER_CHILDREN_FINAL_FIELDS, final_children)
    write_rows_csv(omitted_path, CONTAINER_CHILDREN_OMITTED_FIELDS, omitted_children)

    summary = {
        u"total_codigos_project": len(
            set(_u(r.get(u"codigo_project")) for r in out_rows if _u(r.get(u"codigo_project")))
        ),
        u"total_match_elemento_puntual_aplicable": len(
            [r for r in point_rows if _u(r.get(u"estado_match")) == u"match_elemento_puntual"]
        ),
        u"total_match_directo_aplicable": len(
            [r for r in point_rows if _u(r.get(u"estado_match")) == u"match_directo"]
        ),
        u"total_asignable_a_contenedor_aplicable": len(container_rows),
        u"total_asignable_por_ancestro_project": total_by_ancestor,
        u"total_asignable_por_scoring": total_by_scoring,
        u"total_codigos_aplicables": len(applicable),
        u"total_elementos_revit_a_modificar": len(apply_rows),
        u"total_hijos_asociados_a_contenedor": len(final_children),
        u"total_hijos_cargados_en_btz_description": total_loaded,
        u"total_hijos_asociados_solo_por_csv_externo": total_external_only,
        u"total_hijos_omitidos_por_slots": len(omitted_children),
        u"contenedores_superan_slots": len(containers_over_slots),
        u"contenedores_superan_slots_lista": list(containers_over_slots.values()),
        u"ruta_match_project_revit_confirmado": apply_path,
        u"ruta_asociacion_contenedor_hijos_final_p10": final_children_path,
    }

    lines = [
        u"Preparar aplicación BTZ",
        u"",
        u"total_codigos_project: {0}".format(summary[u"total_codigos_project"]),
        u"total_match_elemento_puntual_aplicable: {0}".format(
            summary[u"total_match_elemento_puntual_aplicable"]
        ),
        u"total_match_directo_aplicable: {0}".format(summary[u"total_match_directo_aplicable"]),
        u"total_asignable_a_contenedor_aplicable: {0}".format(
            summary[u"total_asignable_a_contenedor_aplicable"]
        ),
        u"total_asignable_por_ancestro_project: {0}".format(summary[u"total_asignable_por_ancestro_project"]),
        u"total_asignable_por_scoring: {0}".format(summary[u"total_asignable_por_scoring"]),
        u"total_codigos_aplicables: {0}".format(summary[u"total_codigos_aplicables"]),
        u"total_elementos_revit_a_modificar: {0}".format(summary[u"total_elementos_revit_a_modificar"]),
        u"total_hijos_asociados_a_contenedor: {0}".format(summary[u"total_hijos_asociados_a_contenedor"]),
        u"total_hijos_cargados_en_btz_description: {0}".format(summary[u"total_hijos_cargados_en_btz_description"]),
        u"total_hijos_asociados_solo_por_csv_externo: {0}".format(summary[u"total_hijos_asociados_solo_por_csv_externo"]),
        u"total_hijos_omitidos_por_slots: {0}".format(summary[u"total_hijos_omitidos_por_slots"]),
        u"contenedores_superan_slots_80: {0}".format(summary[u"contenedores_superan_slots"]),
        u"",
        u"lista de contenedores que superan slots:",
    ]
    for item in summary[u"contenedores_superan_slots_lista"]:
        lines.append(
            u"- element_id={0} | hijos={1} | slots_libres={2} | {3}".format(
                item[u"element_id"], item[u"cantidad_hijos"], item[u"slots_libres"], item[u"path"]
            )
        )
    lines.extend(
        [
            u"",
            u"ruta de match_project_revit_confirmado.csv: {0}".format(apply_path),
            u"ruta de asociacion_contenedor_hijos_final.csv: {0}".format(final_children_path),
            u"",
            u"aclaración: los hijos que no entran en BTZ_Description siguen asociados por CSV externo y no se consideran error.",
        ]
    )
    with codecs.open(apply_summary_path, u"w", encoding=u"utf-8") as fp:
        fp.write(u"\n".join(lines) + u"\n")

    return summary


def _build_cluster_capacity_report_lines(out_rows, containers):
    if not EXTENDED_CLUSTER_STATES or not out_rows:
        return []
    containers_by_id = {_u(c.get(u"element_id")): c for c in containers if c.get(u"element_id")}
    usage = defaultdict(int)
    caps = {}
    path_sample = {}
    for row in out_rows:
        if _u(row.get(u"estado_match")) not in _CONTAINER_ASSIGN_ESTADOS:
            continue
        key = _cluster_key_from_prep_row(row)
        if not key:
            continue
        usage[key] += 1
        if key not in caps:
            caps[key] = _capacity_slots_05_80_for_prep_row(row, containers_by_id)
            path_sample[key] = _u(row.get(u"contenedor_sugerido_path")) or _u(
                row.get(u"btz_path_actual")
            )
    lines = [
        u"",
        u"clusters contenedor (hijos sugeridos vs capacidad BTZ_05-80 al export):",
    ]
    for key in sorted(usage.keys(), key=lambda k: (-usage[k], k)):
        lines.append(
            u"  cluster={0} | hijos_sugeridos={1} | capacidad_05_80={2} | path={3}".format(
                key, usage[key], caps.get(key, 0), path_sample.get(key, u"")
            )
        )
    return lines


def write_summary(
    path,
    project_items,
    revit_rows,
    containers,
    counts,
    project_meta,
    revit_meta,
    out_csv,
    containers_csv,
    post_counts,
    out_rows=None,
    apply_counts=None,
):
    over_30 = [
        c for c in containers if c[u"cantidad_codigos_project_asignados_sugeridos"] > 80
    ]
    top_containers = sorted(
        containers,
        key=lambda c: c[u"cantidad_codigos_project_asignados_sugeridos"],
        reverse=True,
    )[:20]
    diffs = counts.get(u"_score_diffs", [])
    avg_diff = (sum(diffs) / float(len(diffs))) if diffs else 0.0
    duplicate_details = counts.get(u"_duplicate_details", [])[:20]
    lines = [
        u"Preparación match Project/Revit {0}".format(PLANT_CODE),
        u"",
        u"entrada Project: {0}".format(project_meta.get(u"path", u"")),
        u"entrada Revit: {0}".format(revit_meta.get(u"path", u"")),
        u"salida CSV: {0}".format(out_csv),
        u"salida contenedores CSV: {0}".format(containers_csv),
        u"",
        u"columna códigos Project detectada: {0}".format(project_meta.get(u"code_col", u"")),
        u"columna descripción Project: {0}".format(project_meta.get(u"desc_col", u"")),
        u"delimitador Project: {0}".format(repr(project_meta.get(u"delimiter", u""))),
        u"encoding Project: {0}".format(project_meta.get(u"encoding", u"")),
        u"",
        u"total códigos Project: {0}".format(len(project_items)),
        u"total elementos {0} Revit: {1}".format(PLANT_CODE, len(revit_rows)),
        u"total contenedores Revit {0}: {1}".format(PLANT_CODE, len(containers)),
        u"match_elemento_puntual: {0}".format(counts.get(u"match_elemento_puntual", 0)),
        u"match_directo: {0}".format(counts.get(u"match_directo", 0)),
        u"duplicado: {0}".format(counts.get(u"duplicado", 0)),
        u"ya_existente_en_btz: {0}".format(counts.get(u"ya_existente_en_btz", 0)),
        u"ya_existente_en_btz_multi_id: {0}".format(counts.get(u"ya_existente_en_btz_multi_id", 0)),
        u"codigos_existentes_multi_id_colapsados: {0}".format(
            counts.get(u"codigos_existentes_multi_id_colapsados", 0)
        ),
        u"force_ancestor_container: {0}".format(counts.get(u"force_ancestor_container", 0)),
        u"ambiguo_real: {0}".format(counts.get(u"ambiguo_real", 0)),
        u"asignable_a_contenedor: {0}".format(counts.get(u"asignable_a_contenedor", 0)),
        u"contenedor_unico: {0}".format(counts.get(u"contenedor_unico", 0)),
        u"contenedor_logico_duplicado_dist: {0}".format(
            counts.get(u"contenedor_logico_duplicado_distributed", 0)
        ),
        u"contenedor_logico_duplicado_canon: {0}".format(
            counts.get(u"contenedor_logico_duplicado_canonical", 0)
        ),
        u"contenedor_duplicado: {0}".format(counts.get(u"contenedor_duplicado", 0)),
        u"sin_contenedor: {0}".format(counts.get(u"sin_contenedor", 0)),
        u"omitido_por_slots: {0}".format(counts.get(u"omitido_por_slots", 0)),
        u"filas_requieren_split_por_slots_SI: {0}".format(
            sum(
                1
                for row in (out_rows or [])
                if _u(row.get(u"requiere_split_por_slots")) == u"SI"
            )
        ),
        u"cluster_mode: {0}".format(CLUSTER_MODE if EXTENDED_CLUSTER_STATES else u"(n/a)"),
        u"force_ancestor_container_modo: {0}".format(
            u"SI" if FORCE_ANCESTOR_CONTAINER and EXTENDED_CLUSTER_STATES else u"NO"
        ),
        u"resueltos_por_force_ancestor_container: {0}".format(
            counts.get(u"resueltos_por_force_ancestor_container", 0)
        ),
        u"clusters_force_ancestor_container: {0}".format(
            counts.get(u"clusters_force_ancestor_container", 0)
        ),
        u"capacidad_total_force_ancestor: {0}".format(counts.get(u"capacidad_total_force_ancestor", 0)),
        u"capacidad_usada_force_ancestor: {0}".format(counts.get(u"capacidad_usada_force_ancestor", 0)),
        u"promedio diferencia de puntaje: {0:.2f}".format(avg_diff),
        u"resueltos_por_ancestro_project: {0}".format(counts.get(u"_resolved_by_ancestor", 0)),
        u"resueltos_por_scoring: {0}".format(counts.get(u"_resolved_by_scoring", 0)),
        u"resueltos_por_puntual_multi_cluster: {0}".format(
            counts.get(u"_resolved_by_punctual_multi_cluster", 0)
        ),
        u"resueltos_por_registry_ancestro_capacidad: {0}".format(
            counts.get(u"_resolved_by_ancestor_cluster_registry", 0)
        ),
        u"resueltos_por_fallback_ancestro_superior: {0}".format(
            counts.get(u"_resolved_by_aggressive_ancestor_superior", 0)
        ),
        u"resueltos_por_primer_ancestro_valido: {0}".format(
            counts.get(u"_resolved_by_primer_ancestro_valido", 0)
        ),
        u"resueltos_por_primer_ancestro_valido_relajado: {0}".format(
            counts.get(u"_resolved_by_primer_ancestro_valido_relajado", 0)
        ),
        u"cantidad todavía contenedor_duplicado: {0}".format(counts.get(u"contenedor_duplicado", 0)),
        u"cantidad de contenedores que superan 80 códigos: {0}".format(len(over_30)),
        u"total_confirmado_auto: {0}".format(post_counts.get(u"total_confirmado_auto", 0)),
        u"total_codigos_aplicables: {0}".format(
            sum(
                1
                for row in (out_rows or [])
                if _u(row.get(u"estado_match"))
                in (
                    u"match_directo",
                    u"match_elemento_puntual",
                    u"contenedor_unico",
                    u"contenedor_logico_duplicado_canonical",
                    u"contenedor_logico_duplicado_distributed",
                    u"asignable_a_contenedor",
                )
            )
        ),
        u"total_revision: {0}".format(post_counts.get(u"total_revision", 0)),
        u"total_elementos_revit_a_modificar: {0}".format(
            (apply_counts or {}).get(u"total_elementos_revit_a_modificar", 0)
        ),
        u"total_asociaciones_contenedor_hijos: {0}".format(
            post_counts.get(u"total_asociaciones_contenedor_hijos", 0)
        ),
        u"contenedores_superan_slots_80: {0}".format(len(over_30)),
        u"aclaración: las asociaciones de hijos se guardan en CSV externo y no se escriben como BTZ_Description individuales.",
        u"",
        u"top 20 contenedores con más códigos sugeridos:",
    ]
    for idx, c in enumerate(top_containers, 1):
        lines.append(
            u"{0}. {1} | element_id={2} | asignados={3} | slots_libres={4}".format(
                idx,
                c.get(u"btz_path_detectado") or u"(sin path)",
                c.get(u"element_id"),
                c[u"cantidad_codigos_project_asignados_sugeridos"],
                c[u"slots_libres"],
            )
        )
    lines.append(u"")
    lines.append(u"top 20 duplicados luego de usar ancestro Project:")
    for idx, item in enumerate(duplicate_details, 1):
        lines.append(
            u"{0}. {1} | mejor={2} segundo={3} diff={4} | {5}".format(
                idx,
                item[u"codigo"],
                item[u"best_score"],
                item[u"second_score"],
                item[u"diff"],
                item[u"candidates"],
            )
        )
    amb_reason_lines = []
    if (post_counts.get(u"total_confirmado_auto", 0) or 0) < 500 and (out_rows or []):
        amb_ctr = Counter()
        for row in out_rows:
            if _u(row.get(u"estado_match")) != u"ambiguo_real":
                continue
            key = u"{0} | {1}".format(
                _u(row.get(u"tipo_resolucion")),
                _u(row.get(u"motivo")),
            )
            amb_ctr[key] += 1
        if amb_ctr:
            amb_reason_lines.append(u"")
            amb_reason_lines.append(
                u"top 20 motivos principales ambiguo_real (total_confirmado_auto < 500):"
            )
            for idx, (lbl, cnt) in enumerate(amb_ctr.most_common(20), 1):
                amb_reason_lines.append(u"{0}. ({1}) {2}".format(idx, cnt, lbl))
    lines.extend(amb_reason_lines)
    lines.extend(_build_cluster_capacity_report_lines(out_rows or [], containers))
    with codecs.open(path, u"w", encoding=u"utf-8") as fp:
        fp.write(u"\n".join(lines) + u"\n")



def write_general_fallback_reports(out_rows, revit_rows, csv_path, summary_path):
    """Compatibilidad con preparar_match_project_revit.py (reports opcionales)."""
    return


def resolve_project_path(default_path):
    if os.path.isfile(default_path):
        return default_path
    base = os.path.splitext(default_path)[0]
    for ext in (u".csv", u".txt", u".tsv"):
        candidate = base + ext
        if os.path.isfile(candidate):
            return candidate
    return default_path


def main():
    parser = argparse.ArgumentParser(
        description=u"Cruza Project Planta 10.000 contra modelo_btz_export_p10.csv sin escribir Revit."
    )
    parser.add_argument(
        u"--project",
        default=DEFAULT_PROJECT_FILE,
        help=(
            u"XML de Microsoft Project o CSV/delimitado exportado desde Project. "
            u"Default: public/PROJECT_PLANTA_10000_SOLO_CODIGOS_MS_PROJECT.xml"
        ),
    )
    parser.add_argument(
        u"--revit",
        default=DEFAULT_REVIT_CSV,
        help=u"CSV P10 exportado desde pyRevit. Default: public/modelo_btz_export_p10.csv",
    )
    parser.add_argument(
        u"--out",
        default=DEFAULT_OUT_CSV,
        help=u"CSV de salida. Default: public/match_project_revit_preparacion.csv",
    )
    parser.add_argument(
        u"--summary",
        default=DEFAULT_OUT_SUMMARY,
        help=u"TXT resumen. Default: public/match_project_revit_preparacion_summary.txt",
    )
    parser.add_argument(
        u"--containers-out",
        default=DEFAULT_CONTAINERS_CSV,
        help=u"CSV de contenedores Revit P10. Default: public/contenedores_revit_p10.csv",
    )
    parser.add_argument(
        u"--confirmado-auto-out",
        default=DEFAULT_CONFIRMADO_AUTO_CSV,
        help=u"CSV de confirmados automáticos. Default: public/match_project_revit_confirmado_auto.csv",
    )
    parser.add_argument(
        u"--revision-out",
        default=DEFAULT_REVISION_CSV,
        help=u"CSV de casos para revisión. Default: public/match_project_revit_revision.csv",
    )
    parser.add_argument(
        u"--container-children-out",
        default=DEFAULT_CONTAINER_CHILDREN_CSV,
        help=u"CSV externo contenedor Revit -> hijos Project. Default: public/asociacion_contenedor_hijos_p10.csv",
    )
    parser.add_argument(
        u"--apply-ready-out",
        default=DEFAULT_APPLY_READY_CSV,
        help=u"CSV consolidado para aplicar. Default: public/match_project_revit_confirmado_para_aplicar.csv",
    )
    parser.add_argument(
        u"--apply-out",
        default=DEFAULT_APPLY_CSV,
        help=u"CSV esperado por pyRevit AplicarBTZConfirmado. Default: public/match_project_revit_confirmado.csv",
    )
    parser.add_argument(
        u"--container-children-final-out",
        default=DEFAULT_CONTAINER_CHILDREN_FINAL_CSV,
        help=u"CSV final externo contenedor Revit -> hijos Project. Default: public/asociacion_contenedor_hijos_final_p10.csv",
    )
    parser.add_argument(
        u"--container-children-omitted-out",
        default=DEFAULT_CONTAINER_CHILDREN_OMITTED_CSV,
        help=u"CSV de hijos asociados pero omitidos por slots. Default: public/asociacion_contenedor_hijos_omitidos_por_slots.csv",
    )
    parser.add_argument(
        u"--apply-summary",
        default=DEFAULT_APPLY_SUMMARY,
        help=u"TXT resumen de preparación de aplicación. Default: public/preparar_aplicacion_btz_summary.txt",
    )
    parser.add_argument(
        u"--extended-cluster-states",
        action="store_true",
        help=u"Activa cluster lógico y estados extendidos (match_directo, contenedor_logico_duplicado_*).",
    )
    parser.add_argument(
        u"--cluster-mode",
        choices=[u"canonical", u"distributed"],
        default=None,
        help=u"Modo de cluster: canonical (un maestro) o distributed (round-robin). Requiere --extended-cluster-states.",
    )
    parser.add_argument(
        u"--force-ancestor-container",
        action=u"store_true",
        help=(
            u"Modo agresivo TE/PP: reclasifica ambiguo_real buscando ancestros en el export Revit. "
            u"En preparar_match_project_revit.py TE/PP queda activo por defecto salvo --no-force-ancestor-container."
        ),
    )
    args = parser.parse_args()

    global EXTENDED_CLUSTER_STATES, CLUSTER_MODE, FORCE_ANCESTOR_CONTAINER
    if args.extended_cluster_states:
        EXTENDED_CLUSTER_STATES = True
    if args.cluster_mode:
        CLUSTER_MODE = args.cluster_mode
    FORCE_ANCESTOR_CONTAINER = bool(getattr(args, u"force_ancestor_container", False))

    project_path = resolve_project_path(args.project)
    project_items, project_meta = load_project_codes(project_path)
    revit_rows, revit_meta = load_revit_rows(args.revit)
    containers = build_revit_containers(revit_rows)
    project_meta[u"path"] = project_path
    revit_meta[u"path"] = args.revit

    out_rows, counts = compare(project_items, revit_rows, containers)
    write_csv(args.out, out_rows)
    write_containers_csv(args.containers_out, containers)
    post_counts = write_postprocess_outputs(
        out_rows,
        args.confirmado_auto_out,
        args.revision_out,
        args.container_children_out,
    )
    apply_counts = prepare_apply_confirmed_outputs(
        out_rows,
        containers,
        args.apply_ready_out,
        args.apply_out,
        args.container_children_final_out,
        args.container_children_omitted_out,
        args.apply_summary,
    )
    write_summary(
        args.summary,
        project_items,
        revit_rows,
        containers,
        counts,
        project_meta,
        revit_meta,
        args.out,
        args.containers_out,
        post_counts,
        out_rows,
        apply_counts,
    )

    print(u"Listo.")
    print(u"CSV: {0}".format(args.out))
    print(u"Contenedores CSV: {0}".format(args.containers_out))
    print(u"Confirmado auto CSV: {0}".format(args.confirmado_auto_out))
    print(u"Revision CSV: {0}".format(args.revision_out))
    print(u"Asociacion contenedor-hijos CSV: {0}".format(args.container_children_out))
    print(u"Confirmado para aplicar CSV: {0}".format(args.apply_ready_out))
    print(u"AplicarBTZConfirmado CSV: {0}".format(args.apply_out))
    print(u"Asociacion final contenedor-hijos CSV: {0}".format(args.container_children_final_out))
    print(u"Omitidos por slots CSV: {0}".format(args.container_children_omitted_out))
    print(u"Resumen aplicacion TXT: {0}".format(args.apply_summary))
    print(u"Resumen: {0}".format(args.summary))
    print(u"Project códigos: {0}".format(len(project_items)))
    print(u"Revit P10 elementos: {0}".format(len(revit_rows)))
    print(u"Contenedores Revit P10: {0}".format(len(containers)))
    print(u"match_elemento_puntual: {0}".format(counts.get(u"match_elemento_puntual", 0)))
    print(u"duplicado: {0}".format(counts.get(u"duplicado", 0)))
    print(u"asignable_a_contenedor: {0}".format(counts.get(u"asignable_a_contenedor", 0)))
    print(u"contenedor_duplicado: {0}".format(counts.get(u"contenedor_duplicado", 0)))
    print(u"sin_contenedor: {0}".format(counts.get(u"sin_contenedor", 0)))
    print(u"total_confirmado_auto: {0}".format(post_counts[u"total_confirmado_auto"]))
    print(u"total_revision: {0}".format(post_counts[u"total_revision"]))
    print(u"total_asociaciones_contenedor_hijos: {0}".format(post_counts[u"total_asociaciones_contenedor_hijos"]))
    print(u"total_elementos_revit_a_modificar: {0}".format(apply_counts[u"total_elementos_revit_a_modificar"]))
    print(u"total_hijos_omitidos_por_slots: {0}".format(apply_counts[u"total_hijos_omitidos_por_slots"]))


if __name__ == "__main__":
    main()
