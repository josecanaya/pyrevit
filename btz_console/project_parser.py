# -*- coding: utf-8 -*-
"""
Parser comun de Microsoft Project XML para flujos BTZ.

No usa Revit API. Devuelve nodos con codigo, descripcion, jerarquia real y
relaciones padre/hijos para scripts automaticos y botones manuales.
"""
from __future__ import print_function

import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import OrderedDict

PLANT_PREFIXES = (u"P10", u"PP", u"TE", u"PR")
ANY_PROJECT_CODE_RE = re.compile(r"(?<![A-Z0-9])(P10|PP|TE|PR)-[A-Z0-9][A-Z0-9_.\-/]*", re.IGNORECASE)

try:
    unicode
except NameError:
    unicode = str


def _u(value):
    if value is None:
        return u""
    try:
        return unicode(value).strip()
    except Exception:
        try:
            return unicode(str(value)).strip()
        except Exception:
            return u""


def _strip_accents(value):
    text = unicodedata.normalize("NFKD", _u(value))
    return u"".join(ch for ch in text if not unicodedata.combining(ch))


def _norm_header(value):
    return _strip_accents(value).strip().lower().replace(u"_", u" ")


def _norm_code(value):
    return _u(value).upper().rstrip(u".,:;)")


def _code_re_legacy(planta):
    """Regex anterior: truncaba el codigo en el primer espacio (solo para mapa de correccion)."""
    return re.compile(r"^({0}-[^\s,;|]+)".format(re.escape(_u(planta).upper())), re.IGNORECASE)


def _extract_project_code_legacy(value, planta):
    text = _u(value)
    if not text:
        return u""
    m = _code_re_legacy(planta).match(text)
    return _norm_code(m.group(1)) if m else u""


def _extract_project_code(value, planta):
    """Devuelve la etiqueta completa si empieza con PLANTA- (sin cortar en espacios)."""
    text = _u(value)
    if not text:
        return u""
    prefix = _u(planta).upper() + u"-"
    if text.upper().startswith(prefix):
        return _norm_code(text)
    return u""


def _extract_any_plant_code(value):
    text = _u(value)
    if not text:
        return u"", u""
    m = ANY_PROJECT_CODE_RE.search(text)
    if not m:
        return u"", u""
    code = _norm_code(m.group(0))
    return code, m.group(1).upper()


def _xml_local(tag):
    return tag.rsplit(u"}", 1)[-1] if u"}" in tag else tag


def _xml_child_text(parent, child_name):
    if parent is None:
        return u""
    for child in list(parent):
        if _xml_local(child.tag) == child_name:
            return _u(child.text)
    return u""


def _iter_schema_extended_attributes(root):
    """Solo definiciones del bloque ExtendedAttributes del esquema."""
    for container in root.iter():
        if _xml_local(container.tag) != u"ExtendedAttributes":
            continue
        for child in list(container):
            if _xml_local(child.tag) == u"ExtendedAttribute":
                yield child


def _iter_tasks(root):
    """Itera tareas MS Project ignorando namespace (compatible IronPython)."""
    for el in root.iter():
        if _xml_local(el.tag) != u"Task":
            continue
        if _xml_child_text(el, u"IsNull") == u"1":
            continue
        yield el


def _iter_task_extended_values(task):
    for el in list(task):
        if _xml_local(el.tag) != u"ExtendedAttribute":
            continue
        yield el


def parse_project_xml(path, planta=None):
    """Lee un XML de MS Project y devuelve nodos jerarquicos filtrados por planta."""
    if not os.path.isfile(path):
        raise IOError(u"No existe el Project XML: {0}".format(path))
    plant = _u(planta).upper()
    tree = ET.parse(path)
    root = tree.getroot()

    field_alias_by_id = {}
    for ext_attr in _iter_schema_extended_attributes(root):
        field_id = _xml_child_text(ext_attr, u"FieldID")
        alias = _xml_child_text(ext_attr, u"Alias")
        field_name = _xml_child_text(ext_attr, u"FieldName")
        if field_id:
            field_alias_by_id[field_id] = alias or field_name or field_id

    nodes = []
    node_by_id = OrderedDict()
    node_by_code = OrderedDict()
    stack_by_level = {}

    for task in _iter_tasks(root):
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
        parent = ancestors[-1] if ancestors else None

        code = _extract_project_code(name, plant) if plant else u""
        if not code and plant:
            for ext_attr in _iter_task_extended_values(task):
                value = _xml_child_text(ext_attr, u"Value")
                code = _extract_project_code(value, plant)
                if code:
                    break

        ext_values = {}
        for ext_attr in _iter_task_extended_values(task):
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

        include = bool(code) or not plant or _u(name).upper() == plant
        node_id = _xml_child_text(task, u"UID") or _xml_child_text(task, u"ID") or outline_number or name
        ancestor_codes = [a.get(u"codigo_project", u"") for a in ancestors if a.get(u"codigo_project")]
        ancestor_names = [a.get(u"task_name", u"") for a in ancestors if a.get(u"task_name")]
        project_path_parts = ancestor_names + ([name] if name else [])
        parent_id = parent.get(u"node_id") if parent else u""

        node = {
            u"node_id": node_id,
            u"codigo_project": code,
            u"descripcion_project": _u(desc),
            u"task_name": name,
            u"project_id": _xml_child_text(task, u"ID"),
            u"outline_level": outline_level,
            u"outline_number": outline_number,
            u"parent_id": parent_id,
            u"parent_task_name": parent.get(u"task_name", u"") if parent else u"",
            u"parent_codigo_project": parent.get(u"codigo_project", u"") if parent else u"",
            u"ancestor_codes_project": u" > ".join(ancestor_codes),
            u"ancestor_names_project": u" > ".join(ancestor_names),
            u"project_path": u" > ".join(project_path_parts),
            u"children": [],
        }

        stack_by_level[level_int] = node
        for lvl in list(stack_by_level.keys()):
            if lvl > level_int:
                del stack_by_level[lvl]

        if not include:
            continue
        nodes.append(node)
        node_by_id[node_id] = node
        if code and code not in node_by_code:
            node_by_code[code] = node

    for node in nodes:
        parent = node_by_id.get(node.get(u"parent_id"))
        if parent is not None:
            parent[u"children"].append(node)

    return {
        u"planta": plant,
        u"path": path,
        u"nodes": nodes,
        u"node_by_id": node_by_id,
        u"node_by_code": node_by_code,
        u"roots": [n for n in nodes if not n.get(u"parent_id") or n.get(u"parent_id") not in node_by_id],
    }


def infer_dominant_plant_from_xml(path, max_tasks=2000):
    """Cuenta prefijos P10/PP/TE/PR en Task/Name o ExtendedAttribute/Value."""
    if not os.path.isfile(path):
        return u""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        return u""
    counts = {p: 0 for p in PLANT_PREFIXES}
    n = 0
    for task in _iter_tasks(root):
        if n >= max_tasks:
            break
        n += 1
        name = _xml_child_text(task, u"Name")
        _code, plant = _extract_any_plant_code(name)
        if plant:
            counts[plant] = counts.get(plant, 0) + 1
            continue
        for ext_attr in _iter_task_extended_values(task):
            value = _xml_child_text(ext_attr, u"Value")
            _code, plant = _extract_any_plant_code(value)
            if plant:
                counts[plant] = counts.get(plant, 0) + 1
                break
    best_plant = u""
    best_n = 0
    for p, c in counts.items():
        if c > best_n:
            best_n = c
            best_plant = p
    return best_plant


def infer_plant_from_project(path):
    """Infiere P10/PP/TE/PR por nombre de archivo o por contenido del XML."""
    if not os.path.isfile(path):
        return u""
    base = os.path.basename(_u(path))
    stem = os.path.splitext(base)[0].upper()
    plants_set = frozenset(PLANT_PREFIXES)
    if stem in plants_set:
        return stem
    name_upper = base.upper()
    for plant in sorted(PLANT_PREFIXES, key=lambda p: len(p), reverse=True):
        if plant in name_upper:
            return plant
    dominant = infer_dominant_plant_from_xml(path, max_tasks=800)
    if dominant:
        return dominant
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        for task in _iter_tasks(root):
            tname = _xml_child_text(task, u"Name")
            _code, plant = _extract_any_plant_code(tname)
            if plant:
                return plant
            for ext_attr in _iter_task_extended_values(task):
                value = _xml_child_text(ext_attr, u"Value")
                _code, plant = _extract_any_plant_code(value)
                if plant:
                    return plant
    except Exception:
        return u""
    return u""


def discover_project_xmls(project_dir):
    """Lista XML disponibles en public/project con planta inferida."""
    if not os.path.isdir(project_dir):
        return []
    out = []
    for name in sorted(os.listdir(project_dir)):
        if not name.lower().endswith(u".xml"):
            continue
        path = os.path.join(project_dir, name)
        out.append({u"path": path, u"name": name, u"planta": infer_plant_from_project(path)})
    return out


def get_project_tree(project_data, planta=None):
    return project_data.get(u"roots", [])


def get_node_ancestors(project_data, node_id):
    nodes = project_data.get(u"node_by_id", {})
    node = nodes.get(node_id)
    out = []
    seen = set()
    while node:
        parent_id = node.get(u"parent_id")
        if not parent_id or parent_id in seen:
            break
        seen.add(parent_id)
        parent = nodes.get(parent_id)
        if not parent:
            break
        out.append(parent)
        node = parent
    out.reverse()
    return out


def get_node_children(project_data, node_id):
    node = project_data.get(u"node_by_id", {}).get(node_id)
    return list(node.get(u"children", [])) if node else []


def get_node_descendants(project_data, node_id):
    out = []

    def walk(n):
        for child in n.get(u"children", []):
            out.append(child)
            walk(child)

    node = project_data.get(u"node_by_id", {}).get(node_id)
    if node:
        walk(node)
    return out


def build_truncated_code_repair_map(project_data):
    """
    Mapa codigo_truncado_viejo -> codigo_completo segun el Project XML parseado.

    Solo incluye entradas unívocas donde el parser legacy cortaba en espacio.
    """
    plant = _u(project_data.get(u"planta")).upper()
    repair = {}
    ambiguous = set()
    seen_full = set()

    for node in project_data.get(u"nodes", []):
        full = _norm_code(node.get(u"codigo_project"))
        if not full or full in seen_full:
            continue
        seen_full.add(full)
        legacy = _extract_project_code_legacy(full, plant)
        if not legacy or legacy == full:
            continue
        if legacy in repair and repair[legacy] != full:
            ambiguous.add(legacy)
        else:
            repair[legacy] = full

    for key in ambiguous:
        repair.pop(key, None)

    return repair, ambiguous


def flatten_project_tree_for_ui(project_data):
    """Devuelve lista [(label, node)] con indentacion por nivel Project."""
    rows = []

    def label_for(node):
        try:
            lvl = max(0, int(node.get(u"outline_level") or 1) - 1)
        except Exception:
            lvl = 0
        code = node.get(u"codigo_project") or node.get(u"task_name")
        desc = node.get(u"descripcion_project")
        label = (u"  " * lvl) + code
        if desc:
            label += u" | " + desc
        return label

    def walk(nodes):
        for node in nodes:
            rows.append((label_for(node), node))
            walk(node.get(u"children", []))

    walk(project_data.get(u"roots", []))
    return rows
