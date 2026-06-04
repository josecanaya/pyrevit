# -*- coding: utf-8 -*-
"""Asignación manual/asistida BTZ navegando un Project XML."""
from __future__ import print_function

__title__ = u"Asignar BTZ\ndesde Project"
__doc__ = (
    u"Permite seleccionar geometrías y asignar BTZ_Description_01..80 "
    u"desde el árbol jerárquico real de un Project XML."
)
__author__ = u"btz.extension"

import codecs
import csv
import datetime
import os
import sys

import clr

clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import Transaction, TransactionStatus
from pyrevit import forms, revit


_bundle_dir = os.path.dirname(os.path.abspath(__file__))
_panel_dir = os.path.normpath(os.path.join(_bundle_dir, u".."))
_ext_dir = os.path.normpath(os.path.join(_panel_dir, u"..", u".."))
_export_dir = os.path.join(_panel_dir, u"ExportarGrupos.pushbutton")
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
from btz_paths import PUBLIC_DIR, ensure_public_layout  # noqa: E402
from project_parser import (  # noqa: E402
    parse_project_xml,
    flatten_project_tree_for_ui,
    get_node_ancestors,
    get_node_children,
    get_node_descendants,
)


try:
    unicode
except NameError:
    unicode = str


PLANTAS = [u"P10", u"PP", u"TE", u"PR"]
TRACE_CSV = os.path.join(PUBLIC_DIR, u"asignaciones_manuales_project.csv")
EXCEDENTES_CSV = os.path.join(PUBLIC_DIR, u"asignaciones_manuales_project_excedentes.csv")
ORIGEN = u"AsignarBTZDesdeProject"
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


def _project_path(planta):
    return os.path.join(PUBLIC_DIR, u"projects", planta, u"project.xml")


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


def _current_btz_values(element):
    return [(p, _param_value(element, p)) for p in PARAM_NUMERIC]


def _has_any_btz(element):
    return any(v for _p, v in _current_btz_values(element))


def _append_csv(path, fields, rows):
    if not rows:
        return
    exists = os.path.isfile(path)
    with codecs.open(path, u"a", encoding=u"utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields, lineterminator=u"\n")
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, u"") for f in fields})


def _unique_codes(nodes, planta):
    out = []
    seen = set()
    for code in [planta] + [n.get(u"codigo_project") for n in nodes]:
        code = _u(code).upper()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _codes_for_selection(project_data, node, option, planta):
    ancestors = get_node_ancestors(project_data, node[u"node_id"])
    base = ancestors + [node]
    if option == u"Nodo + hijos directos":
        base.extend(get_node_children(project_data, node[u"node_id"]))
    elif option == u"Nodo + todos los descendientes":
        base.extend(get_node_descendants(project_data, node[u"node_id"]))
    return _unique_codes(base, planta)


def _choose_node(project_data):
    flat = flatten_project_tree_for_ui(project_data)
    if not flat:
        return None
    labels = []
    by_label = {}
    used = {}
    for label, node in flat:
        label = _u(label)
        if label in used:
            used[label] += 1
            label = u"{0} [{1}]".format(label, used[label])
        else:
            used[label] = 1
        labels.append(label)
        by_label[label] = node
    choice = forms.SelectFromList.show(
        labels,
        title=u"Elegir nodo Project",
        button_name=u"Seleccionar",
        multiselect=False,
    )
    return by_label.get(choice)


def _write_codes_to_element(element, codes, fecha, planta, selected_code, scope_mode, write_mode):
    result_rows = []
    excedent_rows = []
    uid = _u(getattr(element, u"UniqueId", u""))
    eid = _u(element.Id.IntegerValue)

    def add_result(code, slot, estado, msg):
        result_rows.append(
            {
                u"fecha": fecha,
                u"planta": planta,
                u"element_id": eid,
                u"unique_id": uid,
                u"nodo_project_seleccionado": selected_code,
                u"modo_aplicacion": u"{0} | {1}".format(scope_mode, write_mode),
                u"codigo_escrito": code,
                u"btz_description_slot_usado": slot,
                u"estado": estado,
                u"mensaje": msg,
            }
        )

    if write_mode == u"Aplicar solo si el elemento no tiene BTZ" and _has_any_btz(element):
        for code in codes[:80]:
            add_result(code, u"", u"ya_existia", u"Elemento omitido porque ya tiene BTZ")
        return result_rows, excedent_rows, False

    current = _current_btz_values(element)
    existing = dict((v.upper(), p) for p, v in current if v)
    free_slots = [p for p, v in current if not v]
    modified = False

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
            add_result(code, slot, u"elemento_sin_parametro", err or u"No se pudo escribir el parámetro")

    for code in codes[80:]:
        excedent_rows.append(
            {
                u"fecha": fecha,
                u"planta": planta,
                u"element_id": eid,
                u"unique_id": uid,
                u"nodo_project_seleccionado": selected_code,
                u"codigo_no_escrito": code,
                u"motivo": u"supera BTZ_Description_80",
            }
        )

    return result_rows, excedent_rows, modified


def main():
    doc = revit.doc
    uidoc = revit.uidoc
    if not doc or not uidoc:
        forms.alert(u"No hay documento activo.", title=u"Asignar BTZ desde Project")
        return

    elements = _selected_elements(doc, uidoc)
    if not elements:
        forms.alert(u"Seleccioná una o varias geometrías antes de ejecutar el botón.", title=u"Asignar BTZ desde Project")
        return

    planta = forms.SelectFromList.show(
        PLANTAS,
        title=u"Elegir planta",
        button_name=u"Usar planta",
        multiselect=False,
    )
    if not planta:
        return
    planta = _u(planta).upper()

    project_xml = _project_path(planta)
    if not os.path.isfile(project_xml):
        forms.alert(
            u"No existe el Project XML esperado:\n{0}".format(project_xml),
            title=u"Asignar BTZ desde Project",
        )
        return

    try:
        project_data = parse_project_xml(project_xml, planta)
    except Exception as ex:
        forms.alert(_u(ex), title=u"Error leyendo Project XML")
        return

    node = _choose_node(project_data)
    if not node:
        return

    scope_mode = forms.CommandSwitchWindow.show(
        [u"Solo nodo seleccionado", u"Nodo + hijos directos", u"Nodo + todos los descendientes", u"Cancelar"],
        message=u"Qué códigos querés aplicar?",
    )
    if not scope_mode or scope_mode == u"Cancelar":
        return

    codes = _codes_for_selection(project_data, node, scope_mode, planta)
    selected_code = node.get(u"codigo_project") or node.get(u"task_name") or planta

    write_mode = forms.CommandSwitchWindow.show(
        [u"Completar solo slots vacíos", u"Aplicar solo si el elemento no tiene BTZ", u"Cancelar"],
        message=u"Modo de escritura seguro",
    )
    if not write_mode or write_mode == u"Cancelar":
        return

    warning = u""
    if len(codes) > 80:
        warning = (
            u"\n\nHay más códigos que slots disponibles. Se escribirán los primeros 80 "
            u"y el resto quedará registrado en CSV externo."
        )
    confirm = forms.alert(
        u"\n".join(
            [
                u"Planta: {0}".format(planta),
                u"Nodo: {0}".format(selected_code),
                u"Elementos seleccionados: {0}".format(len(elements)),
                u"Códigos a escribir: {0}".format(len(codes)),
                u"Slots BTZ requeridos: {0}".format(min(len(codes), 80)),
                u"Cantidad máxima disponible: 80",
                u"Modo: {0} / {1}".format(scope_mode, write_mode),
            ]
        )
        + warning
        + u"\n\nConfirmar escritura?",
        title=u"Confirmar Asignar BTZ desde Project",
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

    tx = Transaction(doc, u"BTZ | Asignar desde Project")
    tx.Start()
    try:
        for element in elements:
            rows, excedents, modified = _write_codes_to_element(
                element, codes, fecha, planta, selected_code, scope_mode, write_mode
            )
            all_results.extend(rows)
            all_excedents.extend(excedents)
            if modified:
                modified_count += 1
                set_text_parameter(element, PARAM_ESTADO_ASOCIACION, ESTADO)
                set_text_parameter(element, PARAM_ORIGEN_ASOCIACION, ORIGEN)
                set_text_parameter(element, PARAM_FECHA_ASOCIACION, fecha)
                if not get_node_children(project_data, node[u"node_id"]) and node.get(u"codigo_project"):
                    numero_actual = _param_value(element, PARAM_NUMERO_ACTIVO)
                    if not numero_actual or numero_actual.upper() == node.get(u"codigo_project").upper():
                        set_text_parameter(element, PARAM_NUMERO_ACTIVO, node.get(u"codigo_project"))
        tx.Commit()
    except Exception:
        if tx.GetStatus() == TransactionStatus.Started:
            tx.RollBack()
        raise

    _append_csv(
        TRACE_CSV,
        [
            u"fecha",
            u"planta",
            u"element_id",
            u"unique_id",
            u"nodo_project_seleccionado",
            u"modo_aplicacion",
            u"codigo_escrito",
            u"btz_description_slot_usado",
            u"estado",
            u"mensaje",
        ],
        all_results,
    )
    _append_csv(
        EXCEDENTES_CSV,
        [
            u"fecha",
            u"planta",
            u"element_id",
            u"unique_id",
            u"nodo_project_seleccionado",
            u"codigo_no_escrito",
            u"motivo",
        ],
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
            ]
        ),
        title=u"Asignar BTZ desde Project",
    )


if __name__ == "__main__":
    main()
