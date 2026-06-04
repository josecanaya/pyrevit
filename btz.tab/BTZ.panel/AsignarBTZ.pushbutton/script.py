# -*- coding: utf-8 -*-
"""Asignación manual/asistida BTZ navegando un Project XML."""
from __future__ import print_function

__title__ = u"ASIGNAR"
__doc__ = (
    u"ASIGNAR: Project XML (completo o solo faltantes), catálogo manual 01-04, "
    u"agregar hijos en BTZ 05-80, o reporte de catálogo."
)
__author__ = u"btz.extension"

import codecs
import csv
import datetime
import os
import sys
from glob import glob

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import FilteredElementCollector, Transaction, TransactionStatus
from pyrevit import forms, revit


_bundle_dir = os.path.dirname(os.path.abspath(__file__))
_panel_dir = os.path.normpath(os.path.join(_bundle_dir, u".."))
_ext_dir = os.path.normpath(os.path.join(_panel_dir, u"..", u".."))
_export_dir = os.path.join(_panel_dir, u"_lib", u"ExportarGrupos")
_console_dir = os.path.join(_ext_dir, u"btz_console")
for _p in (_export_dir, _console_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from btz_apply_webhook import (  # noqa: E402
    PARAM_NUMERIC,
    PARAM_NUMERO_ACTIVO,
    PARAM_ESTADO_ASOCIACION,
    PARAM_ORIGEN_ASOCIACION,
    PARAM_FECHA_ASOCIACION,
    ensure_btz_shared_parameters,
    set_text_parameter,
)
from btz_paths import ensure_public_layout, get_public_file  # noqa: E402
# pyRevit/IronPython mantiene módulos cacheados entre ejecuciones.
# Recargar evita usar una versión anterior del parser sin las funciones nuevas.
sys.modules.pop("project_parser", None)
import project_parser  # noqa: E402

from btz_manual_catalog import (  # noqa: E402
    append_catalog_entries,
    load_manual_catalog,
    upsert_sector,
    upsert_subsector,
    validate_hierarchy,
)
from btz_manual_usage import export_usage_report, scan_model_usage  # noqa: E402
from btz_manual_ui import pick_assignment  # noqa: E402
from btz_manual_apply import analyze_selection_state, apply_manual_hierarchy  # noqa: E402
from btz_manual_append_slots import (  # noqa: E402
    append_codes_to_btz_slots,
    build_existing_keys_all_slots,
    count_free_child_slots,
    normalize_pasted_codes,
)


try:
    unicode
except NameError:
    unicode = str


PUBLIC_DIR = os.path.join(_ext_dir, u"public")
RESOURCES_DIR = os.path.join(_ext_dir, u"resources")
PROJECT_DIR = os.path.join(PUBLIC_DIR, u"project")
TRACE_CSV = os.path.join(PUBLIC_DIR, u"asignaciones_manuales_project.csv")
EXCEDENTES_CSV = os.path.join(PUBLIC_DIR, u"asignaciones_manuales_project_excedentes.csv")
SUMMARY_TXT = os.path.join(PUBLIC_DIR, u"asignar_btz_project_summary.txt")
REPAIR_CSV = os.path.join(PUBLIC_DIR, u"corregir_btz_truncados_project.csv")
REPAIR_SUMMARY_TXT = os.path.join(PUBLIC_DIR, u"corregir_btz_truncados_project_summary.txt")
DEBUG_TXT = os.path.join(PUBLIC_DIR, u"asignar_btz_project_debug.txt")
MANUAL_APPEND_LOG = os.path.join(PUBLIC_DIR, u"output", u"manual_append_btz_slots_log.csv")
ORIGEN = u"ASIGNAR"
ESTADO = u"asignado_manual_project"


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


def _choose_project_xml():
    projects = project_parser.discover_project_xmls(PROJECT_DIR)
    _write_debug_line(
        u"XML detectados en {0}: {1}".format(
            PROJECT_DIR,
            u", ".join(item.get(u"name", u"") for item in projects) or u"(ninguno)",
        )
    )
    if not projects:
        raise IOError(
            u"No hay XML de Project en:\n{0}\n\n"
            u"Raíz de extensión detectada:\n{1}\n\n"
            u"Verificá que existan PR.xml, PP.xml, TE.xml o P10.xml en public/project.".format(
                PROJECT_DIR, _ext_dir
            )
        )
    labels = []
    by_label = {}
    for item in projects:
        plant = item.get(u"planta") or u"?"
        label = u"{0} | {1}".format(plant, item.get(u"name"))
        labels.append(label)
        by_label[label] = item
    choice = forms.SelectFromList.show(
        labels,
        title=u"Elegir Project XML",
        button_name=u"Usar Project",
        multiselect=False,
        width=640,
        height=480,
    )
    if choice is None:
        return None
    choice = _u(choice)
    item = by_label.get(choice)
    if item is None:
        for lab, it in by_label.items():
            if _u(lab) == choice:
                return it
    return item


def _selected_elements(doc, uidoc):
    ids = list(uidoc.Selection.GetElementIds())
    elements = []
    for eid in ids:
        el = doc.GetElement(eid)
        if el is not None:
            elements.append(el)
    return elements


def _param_value(element, param_name):
    try:
        p = element.LookupParameter(param_name)
    except Exception:
        p = None
    if p is None or not p.HasValue:
        return u""
    try:
        val = p.AsString()
        if val:
            return _u(val)
    except Exception:
        pass
    try:
        return _u(p.AsValueString())
    except Exception:
        return u""


def _element_id_text(element):
    try:
        if hasattr(element.Id, u"Value"):
            return _u(element.Id.Value)
        return _u(element.Id.IntegerValue)
    except Exception:
        return u""


def _current_btz_values(element):
    return [(p, _param_value(element, p)) for p in PARAM_NUMERIC]


def _has_any_btz(element):
    return any(v for _p, v in _current_btz_values(element))


def _selected_element_plants(elements):
    plants = {}
    for element in elements:
        plant = _param_value(element, u"BTZ_Description_01").upper()
        if plant:
            plants[plant] = plants.get(plant, 0) + 1
    return plants


def _append_csv(path, fields, rows):
    if not rows:
        return
    exists = os.path.isfile(path)
    if exists:
        try:
            with codecs.open(path, u"r", encoding=u"utf-8-sig") as fp:
                reader = csv.DictReader(fp)
                old_fields = list(reader.fieldnames or [])
                old_rows = [r for r in reader]
            if old_fields != list(fields):
                with codecs.open(path, u"w", encoding=u"utf-8-sig") as fp:
                    writer = csv.DictWriter(fp, fieldnames=fields, lineterminator=u"\n")
                    writer.writeheader()
                    for row in old_rows:
                        writer.writerow({f: row.get(f, u"") for f in fields})
        except Exception:
            pass
    with codecs.open(path, u"a", encoding=u"utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields, lineterminator=u"\n")
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, u"") for f in fields})


def _write_debug_line(message):
    try:
        parent = os.path.dirname(DEBUG_TXT)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        line = u"[{0}] {1}\n".format(
            datetime.datetime.now().strftime(u"%Y-%m-%d %H:%M:%S"),
            _u(message),
        )
        with codecs.open(DEBUG_TXT, u"a", encoding=u"utf-8") as fp:
            fp.write(line)
    except Exception:
        pass


def _unique_codes(nodes, planta):
    out = []
    seen = set()
    for code in [planta] + [n.get(u"codigo_project") for n in nodes]:
        code = _u(code).upper()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _scan_model_btz_codes(doc):
    """Todos los valores BTZ_Description_01..80 y BTZ_NumeroActivo presentes en el modelo."""
    codes = set()
    for element in FilteredElementCollector(doc).WhereElementIsNotElementType():
        for pname in list(PARAM_NUMERIC) + [PARAM_NUMERO_ACTIVO]:
            val = _param_value(element, pname)
            if val:
                codes.add(_u(val).upper())
    return codes


def _node_project_code(node):
    return _u(node.get(u"codigo_project") or node.get(u"task_name")).upper()


def _node_is_missing(node, model_codes):
    code = _node_project_code(node)
    return bool(code) and code not in model_codes


def _subtree_has_missing(node, model_codes):
    if _node_is_missing(node, model_codes):
        return True
    for child in node.get(u"children") or []:
        if _subtree_has_missing(child, model_codes):
            return True
    return False


def _filter_nodes_for_missing_nav(nodes, model_codes):
    return [n for n in nodes if _subtree_has_missing(n, model_codes)]


def _count_missing_project_codes(project_data, model_codes):
    return sum(1 for n in project_data.get(u"nodes", []) if _node_is_missing(n, model_codes))


def _filter_codes_to_missing(codes, model_codes):
    return [c for c in codes if _u(c).upper() not in model_codes]


def _nodes_for_scope(project_data, node, option):
    ancestors = project_parser.get_node_ancestors(project_data, node[u"node_id"])
    base = ancestors + [node]
    if option == u"Aplicar este nodo + hijos directos":
        base.extend(project_parser.get_node_children(project_data, node[u"node_id"]))
    elif option == u"Aplicar este nodo + todos los descendientes":
        base.extend(project_parser.get_node_descendants(project_data, node[u"node_id"]))
    return base


def _codes_for_selection(project_data, node, option, planta):
    return _unique_codes(_nodes_for_scope(project_data, node, option), planta)


def _codes_for_node_list(project_data, nodes, option, planta):
    merged = []
    for node in nodes:
        merged.extend(_nodes_for_scope(project_data, node, option))
    return _unique_codes(merged, planta)


def _format_trace_selected_nodes(nodes, planta, max_codes=8):
    parts = []
    for n in nodes:
        c = _u(n.get(u"codigo_project") or n.get(u"task_name") or planta)
        if c:
            parts.append(c)
    if not parts:
        return _u(planta)
    if len(parts) > max_codes:
        shown = parts[:max_codes]
        return u" | ".join(shown) + u" | ... (+{0})".format(len(parts) - max_codes)
    return u" | ".join(parts)


def _outline_sort_key(node):
    raw = _u(node.get(u"outline_number"))
    parts = []
    for p in raw.split(u"."):
        try:
            parts.append(int(p))
        except Exception:
            parts.append(999999)
    return parts


def _format_node_pick_line(node):
    code = _u(node.get(u"codigo_project") or node.get(u"task_name"))
    desc = _u(node.get(u"descripcion_project"))
    on = _u(node.get(u"outline_number"))
    if desc:
        line = u"{0} | {1}".format(code, desc)
    else:
        line = code or on or u"(sin nombre)"
    if on:
        line = u"[{0}] {1}".format(on, line)
    return line


def _filter_nodes_local(nodes, needle):
    n = _u(needle).upper()
    if not n:
        return list(nodes)
    out = []
    for node in nodes:
        blob = u" ".join(
            [
                _format_node_pick_line(node),
                _u(node.get(u"codigo_project")),
                _u(node.get(u"task_name")),
                _u(node.get(u"descripcion_project")),
            ]
        ).upper()
        if n in blob:
            out.append(node)
    return out


def _build_labels_and_map(entries):
    labels = []
    by_label = {}
    used = {}
    for entry in entries:
        label = _u(entry[1]) if isinstance(entry, tuple) else _u(entry)
        if label in used:
            used[label] += 1
            label = u"{0} [{1}]".format(label, used[label])
        else:
            used[label] = 1
        labels.append(label)
        node = entry[0] if isinstance(entry, tuple) else None
        by_label[label] = node
    return labels, by_label


def _as_pick_list(pick):
    if pick is None:
        return None
    if isinstance(pick, (list, tuple)):
        return [_u(x) for x in pick if _u(x)]
    s = _u(pick)
    return [s] if s else []


def _choose_project_nodes(project_data, only_missing=False, model_codes=None, title_prefix=u"ASIGNAR"):
    """Navegación por niveles; permite multiselección para combinar varios nodos hermanos."""
    label_volver = u"[ ↑ Volver un nivel ]"
    label_cancel = u"[ ✕ Cancelar ]"

    roots = list(project_data.get(u"roots") or [])
    if only_missing:
        if model_codes is None:
            model_codes = set()
        roots = _filter_nodes_for_missing_nav(roots, model_codes)
    if not roots:
        forms.alert(
            u"No hay nodos raíz en el Project para esta planta."
            if not only_missing
            else u"No hay códigos faltantes respecto al modelo en este Project XML.",
            title=title_prefix,
            warn_icon=True,
        )
        return None

    stack = []
    MAX_SIBLINGS = 400
    mode_txt = u"faltantes" if only_missing else u"jerárquica"
    _write_debug_line(
        u"Navegación {0}: {1} raíces | códigos en modelo: {2}".format(
            mode_txt, len(roots), len(model_codes or ())
        )
    )

    while True:
        parent = stack[-1] if stack else None
        children = list(parent.get(u"children") or []) if parent else roots
        if only_missing:
            children = _filter_nodes_for_missing_nav(children, model_codes)
        children = sorted(children, key=_outline_sort_key)

        if not children:
            if parent:
                if only_missing and _node_is_missing(parent, model_codes):
                    forms.alert(
                        u"Este nodo faltante no tiene hijos faltantes. Se usará para asignar.",
                        title=title_prefix,
                    )
                    return [parent]
                forms.alert(
                    u"El nodo seleccionado no tiene hijos faltantes."
                    if only_missing
                    else u"El nodo seleccionado no tiene hijos. Se usará ese nodo.",
                    title=title_prefix,
                )
                return [parent]
            return None

        working = list(children)
        if len(working) > MAX_SIBLINGS:
            forms.alert(
                u"Este nivel tiene {0} hijos (máximo cómodo {1}).\n\n"
                u"Escribí un texto para acotar la lista (código o descripción). "
                u"Podés cancelar y subir de nivel para acotar por ruta.".format(
                    len(working), MAX_SIBLINGS
                ),
                title=u"{0} - muchos hijos en este nivel".format(title_prefix),
                warn_icon=True,
            )
            needle = None
            while True:
                needle = forms.ask_for_string(
                    default=u"",
                    prompt=u"Filtrar solo en este nivel (mín. 2 caracteres):",
                    title=u"{0} - acotar lista".format(title_prefix),
                )
                if needle is None:
                    break
                needle = _u(needle)
                if len(needle) < 2:
                    forms.alert(
                        u"Mínimo 2 caracteres o pulsá Cancelar en el cuadro de búsqueda.",
                        title=title_prefix,
                        warn_icon=True,
                    )
                    continue
                working = _filter_nodes_local(children, needle)
                if not working:
                    forms.alert(u"Sin coincidencias en este nivel.", title=title_prefix, warn_icon=True)
                    continue
                if len(working) > MAX_SIBLINGS:
                    forms.alert(
                        u"Aún hay {0} coincidencias. Sé más específico.".format(len(working)),
                        title=title_prefix,
                        warn_icon=True,
                    )
                    continue
                break
            if needle is None or len(working) > MAX_SIBLINGS:
                continue

        entries = []
        if stack:
            entries.append((None, label_volver))
        entries.append((None, label_cancel))
        for c in working:
            entries.append((c, _format_node_pick_line(c)))

        labels, by_label = _build_labels_and_map(entries)
        path_txt = u" > ".join(_format_node_pick_line(n) for n in stack) if stack else u"(raíz)"
        path_short = path_txt if len(path_txt) <= 70 else (path_txt[:67] + u"...")
        pick = forms.SelectFromList.show(
            labels,
            title=u"{0} | Nivel {1} | {2}".format(title_prefix, len(stack) + 1, path_short),
            button_name=u"Siguiente",
            multiselect=True,
            width=1000,
            height=700,
        )
        picks = _as_pick_list(pick)
        if picks is None:
            return None
        if not picks:
            continue

        if label_cancel in picks:
            return None
        if label_volver in picks:
            if len(picks) != 1:
                forms.alert(
                    u"No podés combinar «Volver un nivel» con filas del Project.",
                    title=title_prefix,
                    warn_icon=True,
                )
                continue
            if stack:
                stack.pop()
            else:
                forms.alert(u"Ya estás en la raíz del Project.", title=title_prefix)
            continue

        nodes_raw = []
        bad = False
        for p in picks:
            node = by_label.get(p)
            if node is None:
                for lab, nd in by_label.items():
                    if _u(lab) == p:
                        node = nd
                        break
            if node is None:
                forms.alert(u"No se reconoció la selección.", title=title_prefix, warn_icon=True)
                bad = True
                break
            nodes_raw.append(node)
        if bad:
            continue

        dedup = []
        seen_ids = set()
        for node in nodes_raw:
            nid = node.get(u"node_id")
            if nid in seen_ids:
                continue
            seen_ids.add(nid)
            dedup.append(node)
        nodes = dedup
        if not nodes:
            continue

        if len(nodes) == 1:
            node = nodes[0]
            sub = list(node.get(u"children") or [])
            if only_missing:
                sub = _filter_nodes_for_missing_nav(sub, model_codes)
            msg_extra = u""
            if sub:
                msg_extra = u"Este nodo tiene {0} hijos directos{1}.".format(
                    len(sub),
                    u" faltantes" if only_missing else u"",
                )
            else:
                msg_extra = (
                    u"Este nodo no tiene hijos faltantes (hoja)."
                    if only_missing
                    else u"Este nodo no tiene hijos (hoja del Project)."
                )

            action = forms.CommandSwitchWindow.show(
                [
                    u"Entrar (ver hijos de este nodo)",
                    u"Usar este nodo para asignar BTZ",
                    u"Elegir otro de la lista",
                ],
                message=u"{0}\n\n{1}".format(_format_node_pick_line(node), msg_extra),
            )
            if action is None:
                continue
            if action == u"Entrar (ver hijos de este nodo)":
                if not sub:
                    forms.alert(
                        u"No hay hijos faltantes para bajar. Elegí «Usar este nodo» o subí de nivel."
                        if only_missing
                        else u"No hay hijos para bajar. Elegí «Usar este nodo» o subí de nivel.",
                        title=title_prefix,
                        warn_icon=True,
                    )
                    continue
                stack.append(node)
                continue
            if action == u"Usar este nodo para asignar BTZ":
                return [node]
            continue

        preview = u"\n".join(_format_node_pick_line(n) for n in nodes[:15])
        if len(nodes) > 15:
            preview += u"\n… (+{0} más)".format(len(nodes) - 15)
        action = forms.CommandSwitchWindow.show(
            [
                u"Usar estos {0} nodos para asignar BTZ".format(len(nodes)),
                u"Elegir otro de la lista",
            ],
            message=u"Selección múltiple (Ctrl/Shift en la lista). Se fusionan códigos según el modo de aplicación.\n\n"
            + preview,
        )
        if action is None:
            continue
        if action.startswith(u"Usar estos ") and u" nodos para asignar BTZ" in action:
            _write_debug_line(u"Multiselección Project: {0} nodos raíz de alcance".format(len(nodes)))
            return nodes
        continue


def _trace_fields():
    return [
        u"fecha",
        u"project_xml",
        u"planta",
        u"element_id",
        u"unique_id",
        u"nodo_project_seleccionado",
        u"modo_aplicacion",
        u"modo_escritura",
        u"codigo_escrito",
        u"btz_description_slot_usado",
        u"estado",
        u"mensaje",
    ]


def _excedentes_fields():
    return [
        u"fecha",
        u"project_xml",
        u"planta",
        u"element_id",
        u"unique_id",
        u"nodo_project_seleccionado",
        u"codigo_no_escrito",
        u"motivo",
    ]


def _estado_error_param(err):
    msg = _u(err).lower()
    if u"param" in msg and (u"no existe" in msg or u"not found" in msg):
        return u"elemento_sin_parametro"
    return u"error_escritura"


def _write_codes_to_element(element, codes, fecha, project_xml, planta, selected_code, scope_mode, write_mode):
    result_rows = []
    excedent_rows = []
    uid = _u(getattr(element, u"UniqueId", u""))
    eid = _element_id_text(element)

    def add_result(code, slot, estado, msg):
        result_rows.append(
            {
                u"fecha": fecha,
                u"project_xml": project_xml,
                u"planta": planta,
                u"element_id": eid,
                u"unique_id": uid,
                u"nodo_project_seleccionado": selected_code,
                u"modo_aplicacion": scope_mode,
                u"modo_escritura": write_mode,
                u"codigo_escrito": code,
                u"btz_description_slot_usado": slot,
                u"estado": estado,
                u"mensaje": msg,
            }
        )

    for code in codes[80:]:
        excedent_rows.append(
            {
                u"fecha": fecha,
                u"project_xml": project_xml,
                u"planta": planta,
                u"element_id": eid,
                u"unique_id": uid,
                u"nodo_project_seleccionado": selected_code,
                u"codigo_no_escrito": code,
                u"motivo": u"supera_80_btz_description",
            }
        )

    if write_mode == u"Aplicar solo si el elemento no tiene BTZ" and _has_any_btz(element):
        for code in codes[:80]:
            add_result(code, u"", u"omitido_elemento_con_btz", u"Elemento omitido porque ya tiene BTZ")
        return result_rows, excedent_rows, False

    current = _current_btz_values(element)
    existing = dict((v.upper(), p) for p, v in current if v)
    free_slots = [p for p, v in current if not v]
    modified = False

    if write_mode == u"Reemplazar BTZ_Description_01..80":
        for pname in PARAM_NUMERIC:
            ok, err = set_text_parameter(element, pname, u"")
            if not ok:
                add_result(u"", pname, _estado_error_param(err), err or u"No se pudo limpiar el parámetro")
                return result_rows, excedent_rows, modified
        for idx, code in enumerate(codes[:80]):
            slot = PARAM_NUMERIC[idx]
            ok, err = set_text_parameter(element, slot, code)
            if ok:
                modified = True
                add_result(code, slot, u"reemplazado", u"Escrito luego de reemplazar BTZ_Description_01..80")
            else:
                add_result(code, slot, _estado_error_param(err), err or u"No se pudo escribir el parámetro")
        return result_rows, excedent_rows, modified

    if write_mode == u"Aplicar solo si el elemento no tiene BTZ":
        free_slots = list(PARAM_NUMERIC)

    for code in codes[:80]:
        code_key = code.upper()
        if code_key in existing:
            add_result(code, existing[code_key], u"ya_existia", u"El código ya existía en el elemento")
            continue
        if not free_slots:
            add_result(code, u"", u"omitido_sin_slot", u"No quedan slots BTZ_Description libres")
            continue
        slot = free_slots.pop(0)
        ok, err = set_text_parameter(element, slot, code)
        if ok:
            modified = True
            existing[code_key] = slot
            add_result(code, slot, u"escrito", u"Escrito en slot vacío")
        else:
            add_result(code, slot, _estado_error_param(err), err or u"No se pudo escribir el parámetro")

    return result_rows, excedent_rows, modified


def _count_results(rows, estados):
    allowed = set(estados)
    return sum(1 for r in rows if r.get(u"estado") in allowed)


def _write_summary_txt(fecha, project_xml, planta, selected_code, scope_mode, write_mode, elements_count, codes_count, rows, excedents):
    escritos = _count_results(rows, [u"escrito", u"reemplazado"])
    ya_existian = _count_results(rows, [u"ya_existia"])
    omitidos = _count_results(rows, [u"omitido_sin_slot", u"omitido_elemento_con_btz"])
    errores = _count_results(rows, [u"elemento_sin_parametro", u"error_escritura"])
    lines = [
        u"Asignar BTZ Project",
        u"fecha: {0}".format(fecha),
        u"project_xml: {0}".format(project_xml),
        u"planta: {0}".format(planta),
        u"nodo_project_seleccionado: {0}".format(selected_code),
        u"modo_aplicacion: {0}".format(scope_mode),
        u"modo_escritura: {0}".format(write_mode),
        u"elementos_seleccionados: {0}".format(elements_count),
        u"codigos_a_escribir: {0}".format(codes_count),
        u"codigos_escritos: {0}".format(escritos),
        u"codigos_ya_existian: {0}".format(ya_existian),
        u"codigos_omitidos: {0}".format(omitidos + len(excedents)),
        u"errores: {0}".format(errores),
        u"ruta_trazabilidad: {0}".format(TRACE_CSV),
        u"ruta_excedentes: {0}".format(EXCEDENTES_CSV),
    ]
    with codecs.open(SUMMARY_TXT, u"w", encoding=u"utf-8") as fp:
        fp.write(u"\n".join(lines) + u"\n")


def _show_error(ex):
    try:
        msg = unicode(ex)
    except Exception:
        msg = str(ex)
    forms.alert(msg, title=u"ASIGNAR - error", warn_icon=True)
    _write_debug_line(u"ERROR: {0}".format(msg))


def _catalog_candidate_paths():
    corrected_alt = os.path.join(PUBLIC_DIR, u"sectores_subsectores_btz_manual (2).csv")
    base = [
        corrected_alt,
        get_public_file(u"sectores_subsectores_btz_manual.csv", u"optional", fallback=True),
        os.path.join(RESOURCES_DIR, u"sectores_subsectores_btz_manual.csv"),
    ]
    opt_path = get_public_file(u"sectores_subsectores_btz_manual.csv", u"optional", fallback=False)
    opt_dir = os.path.dirname(opt_path)
    if opt_dir and os.path.isdir(opt_dir):
        base.extend(sorted(glob(os.path.join(opt_dir, u"sectores_subsectores_btz_manual*.csv"))))
    base.extend(sorted(glob(os.path.join(RESOURCES_DIR, u"sectores_subsectores_btz_manual*.csv"))))
    unique = []
    seen = set()
    for p in base:
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        unique.append(ap)
    return unique


def _format_selection_mix(selection_state):
    lines = [
        u"La selección tiene mezcla de valores BTZ previos.",
        u"Combinaciones detectadas:",
    ]
    combos = list(selection_state[u"unique_combos"].items())
    combos.sort(key=lambda x: -x[1])
    for (v1, v2, v3, v4), c in combos[:10]:
        lines.append(
            u"- {0} | {1} | {2} | {3} -> {4} el.".format(
                v1 or u"-", v2 or u"-", v3 or u"-", v4 or u"-", c
            )
        )
    if len(combos) > 10:
        lines.append(u"... y {0} combinaciones más".format(len(combos) - 10))
    return u"\n".join(lines)


def _main_manual_report(doc):
    catalog_paths = _catalog_candidate_paths()
    try:
        catalog = load_manual_catalog(catalog_paths)
    except Exception as ex:
        forms.alert(
            u"No se pudo cargar el catálogo manual.\n\n{0}\n\nRutas:\n- {1}".format(
                _u(ex),
                u"\n- ".join(catalog_paths),
            ),
            title=u"ASIGNAR - catálogo",
            warn_icon=True,
        )
        return
    usage = scan_model_usage(doc)
    report_csv = get_public_file(u"btz_manual_usage_report.csv", u"legacy", fallback=False)
    report_txt = get_public_file(u"btz_manual_usage_report.txt", u"legacy", fallback=False)
    report = export_usage_report(usage, report_csv, report_txt)
    forms.alert(
        u"\n".join(
            [
                u"Reporte de uso catálogo BTZ",
                u"Origen catálogo: {0}".format(catalog.get(u"source_path", u"")),
                u"CSV: {0}".format(report.get(u"csv_path", u"")),
                u"TXT: {0}".format(report.get(u"txt_path", u"")),
                u"Filas: {0}".format(report.get(u"rows", 0)),
                u"Elementos escaneados: {0}".format(usage.get(u"elements_scanned", 0)),
            ]
        ),
        title=u"ASIGNAR",
    )


def _main_manual_assign(doc, uidoc):
    catalog_paths = _catalog_candidate_paths()
    try:
        catalog = load_manual_catalog(catalog_paths)
    except Exception as ex:
        forms.alert(
            u"No se pudo cargar el catálogo manual.\n\n{0}\n\nRutas:\n- {1}".format(
                _u(ex),
                u"\n- ".join(catalog_paths),
            ),
            title=u"ASIGNAR - catálogo",
            warn_icon=True,
        )
        return

    elements = _selected_elements(doc, uidoc)
    if not elements:
        forms.alert(
            u"Seleccioná uno o más elementos y volvé a ejecutar ASIGNAR (modo catálogo).",
            title=u"ASIGNAR",
            warn_icon=True,
        )
        return

    ensure_public_layout()
    log_lines = []
    ensure_btz_shared_parameters(doc, log_lines)
    usage = scan_model_usage(doc)
    picked = pick_assignment(catalog, usage, forms)
    if not picked:
        return

    created_sector = picked.get(u"created_sector")
    created_subsector = picked.get(u"created_subsector")
    if created_sector:
        upsert_sector(
            catalog=catalog,
            plant_code=picked[u"plant_code"],
            sector_key=created_sector.get(u"key"),
            sector_name=created_sector.get(u"name"),
            sector_write_code=created_sector.get(u"write_code"),
        )
    if created_subsector:
        upsert_subsector(
            catalog=catalog,
            plant_code=picked[u"plant_code"],
            sector_key=picked[u"sector_key"],
            subsector_name=created_subsector.get(u"name"),
            subsector_code=created_subsector.get(u"code"),
        )

    ok_v, reason_v = validate_hierarchy(
        catalog=catalog,
        plant_code=picked[u"plant_code"],
        sector_key=picked[u"sector_key"],
        subsector_code=picked[u"subsector_code"],
        unit_code=picked.get(u"unit_code", u""),
    )
    if not ok_v:
        forms.alert(reason_v, title=u"ASIGNAR - jerarquía", warn_icon=True)
        return

    selection_state = analyze_selection_state(elements, _param_value)
    if selection_state[u"is_mixed"]:
        proceed = forms.CommandSwitchWindow.show(
            [u"Continuar", u"Cancelar"],
            message=_format_selection_mix(selection_state),
            title=u"ASIGNAR - mezcla BTZ",
        )
        if proceed != u"Continuar":
            return

    sub_raw = picked.get(u"subsector_code") or u""
    na_general = u""
    if sub_raw and u"GENERAL" in sub_raw.upper():
        na_general = sub_raw

    tx = Transaction(doc, u"BTZ | ASIGNAR manual 01-04")
    tx.Start()
    try:
        result = apply_manual_hierarchy(
            elements=elements,
            plant_code=picked[u"plant_code"],
            sector_code=picked[u"sector_write_code"],
            subsector_code=sub_raw,
            unit_code=picked.get(u"unit_code", u""),
            overwrite=bool(picked.get(u"overwrite")),
            set_text_parameter=set_text_parameter,
            get_current_value=_param_value,
            numero_activo=na_general,
        )
        tx.Commit()
    except Exception as ex:
        if tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
        _show_error(ex)
        return

    if created_sector or created_subsector:
        try:
            append_catalog_entries(
                catalog=catalog,
                output_csv_path=get_public_file(
                    u"sectores_subsectores_btz_manual.csv",
                    u"optional",
                    fallback=False,
                ),
                plant_code=picked[u"plant_code"],
                plant_name=picked.get(u"plant_name", picked[u"plant_code"]),
                sector_key=picked[u"sector_key"],
                sector_name=picked[u"sector_name"],
                sector_write_code=picked[u"sector_write_code"],
                subsector_code=picked[u"subsector_code"],
                subsector_name=picked.get(u"subsector_name", u""),
                unit_code=picked.get(u"unit_code", u""),
                unit_name=picked.get(u"unit_name", u""),
            )
        except Exception as ex:
            forms.alert(
                u"Se asignó BTZ, pero no se pudo guardar el alta en el CSV opcional.\n{0}".format(_u(ex)),
                title=u"ASIGNAR",
                warn_icon=True,
            )

    msg_lines = [
        u"Catálogo: {0}".format(catalog.get(u"source_path", u"")),
        u"BTZ_Description_01: {0}".format(_u(picked[u"plant_code"]).upper()),
        u"BTZ_Description_02: {0}".format(_u(picked[u"sector_write_code"]).upper()),
        u"BTZ_Description_03: {0}".format(_u(sub_raw).upper() or u"(vacío)"),
        u"BTZ_Description_04: {0}".format(_u(picked.get(u"unit_code", u"")).upper() or u"(vacío)"),
    ]
    if na_general:
        msg_lines.append(u"BTZ_NumeroActivo (GENERAL): {0}".format(na_general))
    msg_lines.extend(
        [
            u"Elementos modificados: {0} de {1}".format(result.get(u"modified", 0), len(elements)),
            u"Sin cambios: {0}".format(result.get(u"unchanged", 0)),
            u"Omitidos (sin sobrescribir): {0}".format(result.get(u"skipped_existing", 0)),
        ]
    )
    err_list = result.get(u"errors") or []
    if err_list:
        msg_lines.append(u"")
        msg_lines.append(u"Errores:")
        msg_lines.extend(err_list[:12])
        if len(err_list) > 12:
            msg_lines.append(u"... y {0} más".format(len(err_list) - 12))

    forms.alert(u"\n".join(msg_lines), title=u"ASIGNAR - catálogo manual")


def _prompt_multiline_btz_codes():
    import clr

    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        AnchorStyles,
        Button,
        DialogResult,
        Form,
        FormBorderStyle,
        FormStartPosition,
        Label,
        ScrollBars,
        TextBox,
    )
    from System.Drawing import Point, Size

    form = Form()
    form.Text = u"ASIGNAR - pegar códigos (BTZ 05-80)"
    form.StartPosition = FormStartPosition.CenterScreen
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.MaximizeBox = False
    form.MinimizeBox = False
    form.ClientSize = Size(720, 430)

    lbl = Label()
    lbl.Location = Point(12, 10)
    lbl.AutoSize = False
    lbl.Size = Size(696, 40)
    lbl.Text = (
        u"Pegá un código por línea. Solo se usan slots vacíos BTZ_Description_05..80. "
        u"No se cambian 01..04 ni BTZ_NumeroActivo."
    )

    tb = TextBox()
    tb.Multiline = True
    tb.ScrollBars = ScrollBars.Vertical
    tb.AcceptsReturn = True
    tb.AcceptsTab = False
    tb.Location = Point(12, 54)
    tb.Size = Size(696, 310)
    tb.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Bottom

    btn_ok = Button()
    btn_ok.Text = u"Aceptar"
    btn_ok.DialogResult = DialogResult.OK
    btn_ok.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
    btn_ok.Location = Point(512, 378)

    btn_cancel = Button()
    btn_cancel.Text = u"Cancelar"
    btn_cancel.DialogResult = DialogResult.Cancel
    btn_cancel.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
    btn_cancel.Location = Point(608, 378)

    form.Controls.Add(lbl)
    form.Controls.Add(tb)
    form.Controls.Add(btn_ok)
    form.Controls.Add(btn_cancel)
    form.AcceptButton = btn_ok
    form.CancelButton = btn_cancel

    if form.ShowDialog() != DialogResult.OK:
        return None
    return _u(tb.Text)


def _main_append_child_codes(doc, uidoc):
    elements = _selected_elements(doc, uidoc)
    if len(elements) != 1:
        forms.alert(
            u"Este modo requiere exactamente un elemento seleccionado en Revit.",
            title=u"ASIGNAR - BTZ 05-80",
            warn_icon=True,
        )
        return

    _write_debug_line(u"Modo BTZ 05-80 | element_id={0}".format(_element_id_text(elements[0])))
    ensure_public_layout()
    el = elements[0]
    eid = _element_id_text(el)

    log_lines = []
    ensure_btz_shared_parameters(doc, log_lines)

    pasted = _prompt_multiline_btz_codes()
    if pasted is None:
        return
    codes = normalize_pasted_codes(pasted)
    if not codes:
        forms.alert(u"No ingresaste códigos válidos (líneas vacías ignoradas).", title=u"ASIGNAR")
        return

    existing = build_existing_keys_all_slots(el, _param_value, PARAM_NUMERIC)
    needed = [c for c in codes if _u(c).upper() not in existing]
    free_n = count_free_child_slots(el, _param_value, PARAM_NUMERIC)

    if needed and free_n == 0:
        forms.alert(
            u"No hay slots BTZ libres entre 05 y 80.",
            title=u"ASIGNAR - BTZ 05-80",
            warn_icon=True,
        )
        return

    fecha = datetime.datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")
    tx = Transaction(doc, u"BTZ | ASIGNAR hijos 05-80")
    tx.Start()
    try:
        result = append_codes_to_btz_slots(
            el,
            codes,
            set_text_parameter,
            _param_value,
            PARAM_NUMERIC,
            fecha,
            eid,
            MANUAL_APPEND_LOG,
        )
        tx.Commit()
    except Exception as ex:
        if tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
        _show_error(ex)
        return

    slots_txt = u", ".join(result.get(u"slots_usados") or []) or u"(ninguno)"
    msg = [
        u"Elemento element_id: {0}".format(eid),
        u"Total códigos recibidos: {0}".format(result.get(u"total_recibidos", 0)),
        u"Total agregados: {0}".format(result.get(u"agregados", 0)),
        u"Duplicados omitidos: {0}".format(result.get(u"duplicados_omitidos", 0)),
        u"Sin cargar por falta de slots: {0}".format(result.get(u"sin_slot", 0)),
        u"Errores de escritura: {0}".format(result.get(u"errores_escritura", 0)),
        u"Slots usados: {0}".format(slots_txt),
        u"",
        u"Log CSV: {0}".format(MANUAL_APPEND_LOG),
    ]
    err = result.get(u"errors") or []
    if err:
        msg.append(u"")
        msg.append(u"Detalle errores:")
        msg.extend(err[:8])
    forms.alert(u"\n".join(msg), title=u"ASIGNAR - BTZ 05-80")


def _repair_trace_fields():
    return [
        u"fecha",
        u"project_xml",
        u"planta",
        u"element_id",
        u"unique_id",
        u"parametro",
        u"codigo_anterior",
        u"codigo_nuevo",
        u"estado",
        u"mensaje",
    ]


def _repair_element_truncated_codes(element, repair_map, fecha, project_xml, planta):
    rows = []
    modified = False
    uid = _u(getattr(element, u"UniqueId", u""))
    eid = _element_id_text(element)

    occupied = {}
    for pname in PARAM_NUMERIC:
        val = _u(_param_value(element, pname)).upper()
        if val:
            occupied[val] = pname

    params_to_check = list(PARAM_NUMERIC) + [PARAM_NUMERO_ACTIVO]

    def add_row(param, old_val, new_val, estado, msg):
        rows.append(
            {
                u"fecha": fecha,
                u"project_xml": project_xml,
                u"planta": planta,
                u"element_id": eid,
                u"unique_id": uid,
                u"parametro": param,
                u"codigo_anterior": old_val,
                u"codigo_nuevo": new_val,
                u"estado": estado,
                u"mensaje": msg,
            }
        )

    for pname in params_to_check:
        old_val = _param_value(element, pname)
        old_key = _u(old_val).upper()
        if not old_key:
            continue
        full = repair_map.get(old_key)
        if not full or full == old_key:
            continue
        if full in occupied and occupied.get(full) != pname:
            other_slot = occupied.get(full)
            ok, err = set_text_parameter(element, pname, u"")
            if ok:
                modified = True
                occupied.pop(old_key, None)
                add_row(
                    pname,
                    old_val,
                    u"",
                    u"limpiado_duplicado",
                    u"El código completo ya existía en {0}; se limpió el truncado".format(other_slot),
                )
            else:
                add_row(pname, old_val, u"", _estado_error_param(err), err or u"No se pudo limpiar")
            continue
        ok, err = set_text_parameter(element, pname, full)
        if ok:
            modified = True
            occupied.pop(old_key, None)
            occupied[full] = pname
            add_row(
                pname,
                old_val,
                full,
                u"corregido",
                u"Completado desde etiqueta Project XML",
            )
        else:
            add_row(pname, old_val, full, _estado_error_param(err), err or u"No se pudo escribir")

    return rows, modified


def _write_repair_summary_txt(fecha, project_xml, planta, elements_count, rows, ambiguous_count):
    corregidos = sum(1 for r in rows if r.get(u"estado") == u"corregido")
    limpiados = sum(1 for r in rows if r.get(u"estado") == u"limpiado_duplicado")
    errores = sum(1 for r in rows if r.get(u"estado") in (u"elemento_sin_parametro", u"error_escritura"))
    elementos_mod = len(set(r.get(u"element_id") for r in rows if r.get(u"estado") in (u"corregido", u"limpiado_duplicado")))
    lines = [
        u"Corregir BTZ truncados (Project XML)",
        u"fecha: {0}".format(fecha),
        u"project_xml: {0}".format(project_xml),
        u"planta: {0}".format(planta),
        u"elementos_escaneados: {0}".format(elements_count),
        u"elementos_modificados: {0}".format(elementos_mod),
        u"valores_corregidos: {0}".format(corregidos),
        u"duplicados_limpiados: {0}".format(limpiados),
        u"prefijos_ambiguos_omitidos: {0}".format(ambiguous_count),
        u"errores: {0}".format(errores),
        u"ruta_trazabilidad: {0}".format(REPAIR_CSV),
    ]
    with codecs.open(REPAIR_SUMMARY_TXT, u"w", encoding=u"utf-8") as fp:
        fp.write(u"\n".join(lines) + u"\n")


def _main_repair_truncated_from_project(doc, uidoc):
    try:
        project_choice = _choose_project_xml()
    except Exception as ex:
        forms.alert(_u(ex), title=u"ASIGNAR")
        return
    if not project_choice:
        return

    project_xml = project_choice.get(u"path")
    planta = project_choice.get(u"planta") or project_parser.infer_plant_from_project(project_xml)
    planta = _u(planta).upper()
    if not planta:
        forms.alert(u"No se pudo inferir planta desde el XML seleccionado.", title=u"ASIGNAR")
        return

    forms.alert(
        u"Cargando Project XML ({0}) para detectar codigos truncados...".format(planta),
        title=u"ASIGNAR - corregir truncados",
    )
    try:
        project_data = project_parser.parse_project_xml(project_xml, planta)
    except Exception as ex:
        forms.alert(_u(ex), title=u"Error leyendo Project XML")
        return

    repair_map, ambiguous = project_parser.build_truncated_code_repair_map(project_data)
    if not repair_map:
        forms.alert(
            u"No hay correcciones unívocas disponibles en este Project XML.\n\n"
            u"Prefijos ambiguos detectados: {0}".format(len(ambiguous)),
            title=u"ASIGNAR - corregir truncados",
            warn_icon=True,
        )
        return

    scope = forms.CommandSwitchWindow.show(
        [
            u"Solo elementos seleccionados",
            u"Todo el modelo",
            u"Cancelar",
        ],
        message=(
            u"Se detectaron {0} codigos truncados reparables (p. ej. cortados en espacio).\n"
            u"Prefijos ambiguos omitidos: {1}.\n\n"
            u"¿Que elementos querés revisar?"
        ).format(len(repair_map), len(ambiguous)),
        title=u"ASIGNAR - corregir truncados",
    )
    if scope is None or scope == u"Cancelar":
        return

    if scope == u"Solo elementos seleccionados":
        elements = _selected_elements(doc, uidoc)
        if not elements:
            forms.alert(
                u"Selecciona uno o mas elementos o elegi «Todo el modelo».",
                title=u"ASIGNAR - corregir truncados",
                warn_icon=True,
            )
            return
    else:
        elements = list(FilteredElementCollector(doc).WhereElementIsNotElementType())

    sample = u", ".join(
        u"{0} -> {1}".format(k, v) for k, v in sorted(repair_map.items())[:5]
    )
    if len(repair_map) > 5:
        sample += u", ..."
    ok = forms.alert(
        u"\n".join(
            [
                u"Planta: {0}".format(planta),
                u"Project: {0}".format(os.path.basename(project_xml)),
                u"Elementos a revisar: {0}".format(len(elements)),
                u"Correcciones unívocas: {0}".format(len(repair_map)),
                u"Ejemplos: {0}".format(sample),
                u"",
                u"Se completaran los BTZ truncados con la etiqueta entera del XML.",
                u"¿Confirmar?",
            ]
        ),
        title=u"ASIGNAR - corregir truncados",
        yes=True,
        no=True,
    )
    if not ok:
        return

    ensure_public_layout()
    log_lines = []
    ensure_btz_shared_parameters(doc, log_lines)
    fecha = datetime.datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")
    all_rows = []
    modified_count = 0

    tx = Transaction(doc, u"BTZ | Corregir codigos truncados Project")
    tx.Start()
    try:
        for element in elements:
            rows, modified = _repair_element_truncated_codes(
                element, repair_map, fecha, project_xml, planta
            )
            all_rows.extend(rows)
            if modified:
                modified_count += 1
        tx.Commit()
    except Exception:
        if tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
        raise

    _append_csv(REPAIR_CSV, _repair_trace_fields(), all_rows)
    _write_repair_summary_txt(fecha, project_xml, planta, len(elements), all_rows, len(ambiguous))

    forms.alert(
        u"\n".join(
            [
                u"Correccion terminada.",
                u"Elementos revisados: {0}".format(len(elements)),
                u"Elementos modificados: {0}".format(modified_count),
                u"Valores corregidos: {0}".format(
                    sum(1 for r in all_rows if r.get(u"estado") == u"corregido")
                ),
                u"Duplicados limpiados: {0}".format(
                    sum(1 for r in all_rows if r.get(u"estado") == u"limpiado_duplicado")
                ),
                u"Prefijos ambiguos omitidos: {0}".format(len(ambiguous)),
                u"Trazabilidad: {0}".format(REPAIR_CSV),
                u"Resumen: {0}".format(REPAIR_SUMMARY_TXT),
            ]
        ),
        title=u"ASIGNAR - corregir truncados",
    )


def _main_assign_from_project(doc, uidoc, only_missing=False):
    title_prefix = u"ASIGNAR FALTANTES" if only_missing else u"ASIGNAR"
    done_title = title_prefix

    elements = _selected_elements(doc, uidoc)
    if not elements:
        forms.alert(
            u"Seleccioná una o varias geometrías antes de ejecutar el botón.",
            title=title_prefix,
        )
        return

    model_codes = _scan_model_btz_codes(doc) if only_missing else None
    if only_missing:
        _write_debug_line(
            u"Modo faltantes: {0} códigos BTZ distintos en el modelo".format(len(model_codes))
        )

    try:
        project_choice = _choose_project_xml()
    except Exception as ex:
        forms.alert(_u(ex), title=title_prefix)
        return
    if not project_choice:
        forms.alert(
            u"Cancelaste la elección de Project o no se reconoció el ítem seleccionado.",
            title=title_prefix,
        )
        return
    project_xml = project_choice.get(u"path")
    planta = project_choice.get(u"planta") or project_parser.infer_plant_from_project(project_xml)
    planta = _u(planta).upper()
    if not planta:
        forms.alert(u"No se pudo inferir planta desde el XML seleccionado.", title=title_prefix)
        return

    load_msg = (
        u"Cargando Project XML ({0}) y comparando con el modelo...\n\n"
        u"En plantas grandes puede tardar unos segundos; no cierres Revit."
        if only_missing
        else u"Cargando estructura del Project ({0}).\n\n"
        u"En plantas grandes (PR, P10) puede tardar unos segundos; no cierres Revit."
    ).format(planta)
    forms.alert(load_msg, title=title_prefix)
    try:
        project_data = project_parser.parse_project_xml(project_xml, planta)
    except Exception as ex:
        forms.alert(_u(ex), title=u"Error leyendo Project XML")
        _write_debug_line(u"parse_project_xml ERROR: {0}".format(_u(ex)))
        return

    ncount = len(project_data.get(u"nodes", []))
    if ncount == 0:
        alt = project_parser.infer_dominant_plant_from_xml(project_xml, max_tasks=2000)
        _write_debug_line(
            u"0 nodos con planta {0}; planta dominante en XML: {1}".format(planta, alt or u"(sin)")
        )
        if alt and alt != planta:
            forms.alert(
                u"Con planta «{0}» no se incluyó ninguna tarea.\n\n"
                u"Según los códigos dentro del XML, la planta predominante es «{1}».\n"
                u"Se volverá a cargar el árbol usando «{1}».".format(planta, alt),
                title=u"{0} - corrección de planta".format(title_prefix),
                warn_icon=True,
            )
            planta = alt
            try:
                project_data = project_parser.parse_project_xml(project_xml, planta)
            except Exception as ex:
                forms.alert(_u(ex), title=u"Error leyendo Project XML")
                _write_debug_line(u"parse_project_xml retry ERROR: {0}".format(_u(ex)))
                return
            ncount = len(project_data.get(u"nodes", []))
        if ncount == 0:
            forms.alert(
                u"No se pudo leer ninguna tarea del Project (0 nodos).\n\n"
                u"Planta usada: {0}\nArchivo: {1}\n\n"
                u"Revisá el XML o que los códigos de tarea empiecen con el prefijo de planta correcto.".format(
                    planta, os.path.basename(project_xml)
                ),
                title=title_prefix,
                warn_icon=True,
            )
            return

    _write_debug_line(u"Project parseado OK: {0} nodos (planta {1})".format(ncount, planta))

    if only_missing:
        missing_count = _count_missing_project_codes(project_data, model_codes)
        _write_debug_line(
            u"Faltantes detectados: {0} códigos XML no presentes en el modelo".format(missing_count)
        )
        if missing_count == 0:
            forms.alert(
                u"Todos los códigos del Project XML ({0}) ya están en el modelo.\n\n"
                u"Códigos BTZ distintos en Revit: {1}".format(planta, len(model_codes)),
                title=title_prefix,
            )
            return
        forms.alert(
            u"Project {0}: {1} códigos del XML no están en el modelo.\n\n"
            u"La navegación mostrará solo ramas con faltantes.".format(planta, missing_count),
            title=title_prefix,
        )

    nodes = _choose_project_nodes(
        project_data,
        only_missing=only_missing,
        model_codes=model_codes,
        title_prefix=title_prefix,
    )
    if not nodes:
        forms.alert(u"No elegiste nodo Project o cancelaste.", title=title_prefix)
        return

    scope_mode = forms.CommandSwitchWindow.show(
        [
            u"Aplicar solo este nodo",
            u"Aplicar este nodo + hijos directos",
            u"Aplicar este nodo + todos los descendientes",
            u"Cancelar",
        ],
        message=u"Qué códigos querés aplicar? (Si elegiste varios nodos, el modo vale por cada uno y se unen sin repetir códigos.)",
    )
    if not scope_mode or scope_mode == u"Cancelar":
        return

    codes = _codes_for_node_list(project_data, nodes, scope_mode, planta)
    if only_missing:
        codes_before = len(codes)
        codes = _filter_codes_to_missing(codes, model_codes)
        if not codes:
            forms.alert(
                u"Los códigos del alcance elegido ya están todos en el modelo.",
                title=title_prefix,
                warn_icon=True,
            )
            return
        _write_debug_line(
            u"Filtro faltantes: {0} -> {1} códigos a escribir".format(codes_before, len(codes))
        )
    selected_code = _format_trace_selected_nodes(nodes, planta)

    write_mode = forms.CommandSwitchWindow.show(
        [
            u"Completar solo slots vacíos",
            u"Reemplazar BTZ_Description_01..80",
            u"Aplicar solo si el elemento no tiene BTZ",
            u"Cancelar",
        ],
        message=u"Modo de escritura seguro",
    )
    if not write_mode or write_mode == u"Cancelar":
        return

    selected_plants = _selected_element_plants(elements)
    mismatched = [p for p in sorted(selected_plants.keys()) if p != planta]
    if mismatched:
        msg = (
            u"El elemento seleccionado tiene planta {0} y el Project elegido es {1}. ¿Desea continuar?"
            if len(mismatched) == 1 and len(elements) == 1
            else u"Hay elementos seleccionados con planta {0} y el Project elegido es {1}. ¿Desea continuar?"
        ).format(u", ".join(mismatched), planta)
        ok_mismatch = forms.alert(
            msg,
            title=u"{0} - planta distinta".format(title_prefix),
            yes=True,
            no=True,
            warn_icon=True,
        )
        if not ok_mismatch:
            return

    if write_mode == u"Reemplazar BTZ_Description_01..80":
        ok_replace = forms.alert(
            u"El modo Reemplazar va a limpiar BTZ_Description_01..80 y escribir la nueva lista desde BTZ_Description_01.\n\n"
            u"No se borrarán otros parámetros BTZ salvo los metadatos de asociación que se actualizarán al finalizar.\n\n"
            u"¿Confirmar reemplazo?",
            title=u"Confirmar reemplazo BTZ",
            yes=True,
            no=True,
            warn_icon=True,
        )
        if not ok_replace:
            return

    warning = u""
    if len(codes) > 80:
        warning = (
            u"\n\nHay más de 80 códigos. Se escribieron los primeros 80 y el resto quedó registrado."
        )
    confirm_lines = [
        u"Planta: {0}".format(planta),
        u"Project XML: {0}".format(os.path.basename(project_xml)),
        u"Nodo(s) ({0}): {1}".format(len(nodes), selected_code),
        u"Modo de aplicación: {0}".format(scope_mode),
        u"Modo de escritura: {0}".format(write_mode),
        u"Elementos seleccionados: {0}".format(len(elements)),
        u"Códigos a escribir: {0}".format(len(codes)),
        u"Slots BTZ requeridos: {0}".format(min(len(codes), 80)),
        u"Cantidad máxima disponible: 80",
    ]
    if only_missing:
        confirm_lines.insert(1, u"Modo: solo faltantes (no presentes en el modelo)")
    confirm = forms.alert(
        u"\n".join(confirm_lines) + warning + u"\n\nConfirmar escritura?",
        title=u"Confirmar {0} desde Project".format(title_prefix),
        yes=True,
        no=True,
    )
    if not confirm:
        return

    ensure_public_layout()
    log_lines = []
    ensure_btz_shared_parameters(doc, log_lines)
    fecha = datetime.datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")
    all_results = []
    all_excedents = []
    modified_count = 0

    tx_name = u"BTZ | Asignar faltantes Project" if only_missing else u"BTZ | Asignar desde Project"
    tx = Transaction(doc, tx_name)
    tx.Start()
    try:
        for element in elements:
            rows, excedents, modified = _write_codes_to_element(
                element, codes, fecha, project_xml, planta, selected_code, scope_mode, write_mode
            )
            all_results.extend(rows)
            all_excedents.extend(excedents)
            if modified:
                modified_count += 1
                set_text_parameter(element, PARAM_ESTADO_ASOCIACION, ESTADO)
                set_text_parameter(element, PARAM_ORIGEN_ASOCIACION, ORIGEN)
                set_text_parameter(element, PARAM_FECHA_ASOCIACION, fecha)
                if len(nodes) == 1:
                    sole = nodes[0]
                    if not project_parser.get_node_children(project_data, sole[u"node_id"]) and sole.get(
                        u"codigo_project"
                    ):
                        numero_actual = _param_value(element, PARAM_NUMERO_ACTIVO)
                        if not numero_actual or numero_actual.upper() == sole.get(u"codigo_project").upper():
                            set_text_parameter(element, PARAM_NUMERO_ACTIVO, sole.get(u"codigo_project"))
        tx.Commit()
    except Exception:
        if tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
        raise

    _append_csv(
        TRACE_CSV,
        _trace_fields(),
        all_results,
    )
    _append_csv(
        EXCEDENTES_CSV,
        _excedentes_fields(),
        all_excedents,
    )
    _write_summary_txt(
        fecha,
        project_xml,
        planta,
        selected_code,
        scope_mode,
        write_mode,
        len(elements),
        len(codes),
        all_results,
        all_excedents,
    )

    forms.alert(
        u"\n".join(
            [
                u"Asignación terminada.",
                u"Elementos seleccionados: {0}".format(len(elements)),
                u"Elementos modificados: {0}".format(modified_count),
                u"Filas trazabilidad: {0}".format(len(all_results)),
                u"Excedentes: {0}".format(len(all_excedents)),
                u"Trazabilidad: {0}".format(TRACE_CSV),
                u"Excedentes CSV: {0}".format(EXCEDENTES_CSV),
                u"Resumen TXT: {0}".format(SUMMARY_TXT),
            ]
        ),
        title=done_title,
    )


def main():
    _write_debug_line(
        u"Inicio ASIGNAR | bundle={0} | ext={1} | public={2} | project_dir={3}".format(
            _bundle_dir, _ext_dir, PUBLIC_DIR, PROJECT_DIR
        )
    )
    doc = revit.doc
    uidoc = revit.uidoc
    if not doc or not uidoc:
        forms.alert(u"No hay documento activo.", title=u"ASIGNAR")
        return

    modo = forms.CommandSwitchWindow.show(
        [
            u"Asignar desde Project (XML)",
            u"Asignar faltantes desde Project (XML)",
            u"Corregir códigos truncados (Project XML)",
            u"Asignar manual catálogo BTZ (01-04)",
            u"Agregar activos hijos/sueltos (BTZ 05-80)",
            u"Reporte de uso catálogo",
            u"Cancelar",
        ],
        message=u"Elegí cómo querés usar ASIGNAR.",
        title=u"ASIGNAR",
    )
    if modo is None or modo == u"Cancelar":
        return
    if modo == u"Corregir códigos truncados (Project XML)":
        _main_repair_truncated_from_project(doc, uidoc)
        return
    if modo == u"Reporte de uso catálogo":
        _main_manual_report(doc)
        return
    if modo == u"Asignar manual catálogo BTZ (01-04)":
        _main_manual_assign(doc, uidoc)
        return
    if modo == u"Agregar activos hijos/sueltos (BTZ 05-80)":
        _main_append_child_codes(doc, uidoc)
        return
    if modo == u"Asignar faltantes desde Project (XML)":
        _main_assign_from_project(doc, uidoc, only_missing=True)
        return
    if modo == u"Asignar desde Project (XML)":
        _main_assign_from_project(doc, uidoc, only_missing=False)
        return


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        _show_error(ex)
