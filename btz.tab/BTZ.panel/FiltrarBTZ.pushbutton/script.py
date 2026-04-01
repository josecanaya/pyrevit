# -*- coding: utf-8 -*-
"""
pyRevit - Filtrar BTZ por planta

Filtra la vista activa por el prefijo de BTZ_Description_01.
"""
from __future__ import print_function

__title__ = u"Filtrar"
__doc__ = u"Filtra la vista activa por planta (prefijo de BTZ_Description_01)"
__author__ = u"btz.extension"

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import (
    Transaction,
    FilteredElementCollector,
    OverrideGraphicSettings,
    Color,
)
from System import Byte
from pyrevit import revit, forms


PARAM_01 = u"BTZ_Description_01"
PARAM_BASE = u"BTZ_Description"
PARAM_CANDIDATES = [PARAM_01, PARAM_BASE]
PLANTA_LABELS = {
    u"TE": u"Terminal",
    u"PP": u"Puerto Planta",
    u"P10": u"Planta 1000",
    u"PR": u"Ricardone",
}
PLANTA_COLORS = {
    u"TE": (46, 204, 113),   # verde
    u"PP": (52, 152, 219),   # azul
    u"P10": (230, 126, 34),  # naranja
    u"PR": (155, 89, 182),   # violeta
}


def _u(value):
    if value is None:
        return u""
    try:
        return unicode(value)  # noqa: F821 (IronPython)
    except Exception:
        try:
            return str(value)
        except Exception:
            return u""


def _extract_planta(code):
    s = _u(code).strip().upper()
    if not s:
        return u""
    if u"-" in s:
        return s.split(u"-", 1)[0].strip()
    return s


def _get_param_instance_or_type(doc, element, param_name):
    try:
        p = element.LookupParameter(param_name)
    except Exception:
        p = None
    if p is not None:
        return p

    try:
        tid = element.GetTypeId()
        if tid is None:
            return None
        t = doc.GetElement(tid)
        if t is None:
            return None
        return t.LookupParameter(param_name)
    except Exception:
        return None


def _get_btz_value_from_element(doc, element):
    """
    Retorna (valor, parametro_objeto, nombre_parametro) usando prioridad:
    BTZ_Description_01 -> BTZ_Description.
    """
    for pname in PARAM_CANDIDATES:
        p = _get_param_instance_or_type(doc, element, pname)
        if p is None:
            continue
        raw = _u(p.AsString() or p.AsValueString()).strip()
        if raw:
            return raw, p, pname
    return u"", None, u""


def _display_label_for_planta(code):
    c = _u(code).upper()
    label = PLANTA_LABELS.get(c)
    if label:
        return u"{0} - {1}".format(c, label)
    return c


def _color_for_planta(code):
    c = _u(code).upper()
    if c in PLANTA_COLORS:
        return PLANTA_COLORS[c]
    h = sum(ord(ch) for ch in c) % 6
    palette = [
        (231, 76, 60),
        (241, 196, 15),
        (26, 188, 156),
        (149, 165, 166),
        (52, 73, 94),
        (243, 156, 18),
    ]
    return palette[h]


def _collect_view_elements_and_plants(doc, view):
    plantas = set()
    param_name_used = u""
    param_hits = {PARAM_01: 0, PARAM_BASE: 0}
    elements = []

    collector = FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
    for el in collector:
        elements.append(el)

        raw, p, pname = _get_btz_value_from_element(doc, el)
        if p is not None and pname:
            param_hits[pname] = int(param_hits.get(pname, 0) or 0) + 1

        planta = _extract_planta(raw)
        if planta:
            plantas.add(planta)

    if param_hits.get(PARAM_BASE, 0) > param_hits.get(PARAM_01, 0):
        param_name_used = PARAM_BASE
    elif param_hits.get(PARAM_01, 0) > 0:
        param_name_used = PARAM_01
    return elements, sorted(list(plantas)), param_name_used


def _build_planta_buckets(doc, elements):
    buckets = {}
    for el in elements:
        raw, _, _ = _get_btz_value_from_element(doc, el)
        planta = _extract_planta(raw)
        if not planta:
            continue
        key = _u(planta).upper()
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(el.Id)
    return buckets


def _set_color_override(view, element_id, rgb):
    r, g, b = rgb
    ogs = OverrideGraphicSettings()
    ogs.SetProjectionLineColor(Color(Byte(r), Byte(g), Byte(b)))
    view.SetElementOverrides(element_id, ogs)


def _clear_override(view, element_id):
    view.SetElementOverrides(element_id, OverrideGraphicSettings())


def main():
    doc = revit.doc
    view = doc.ActiveView if doc else None
    if doc is None or view is None:
        forms.alert(u"No hay documento o vista activa.", title=__title__, warn_icon=True)
        return

    elements, plantas, param_name_used = _collect_view_elements_and_plants(doc, view)
    if not param_name_used:
        forms.alert(
            u"No se encontró ningún parámetro BTZ para filtrar ({0}, {1}) en la vista activa.".format(PARAM_01, PARAM_BASE),
            title=__title__,
            warn_icon=True,
        )
        return
    if not plantas:
        forms.alert(
            u"Se encontró el parámetro {0}, pero no hay valores BTZ cargados para extraer planta.".format(param_name_used or PARAM_01),
            title=__title__,
            warn_icon=True,
        )
        return
    if not elements:
        forms.alert(u"La vista activa no tiene elementos para colorear.", title=__title__, warn_icon=True)
        return

    options = [
        u"Colorear todas las plantas (BTZ)",
        u"Colorear solo una planta",
        u"Quitar colores BTZ de la vista",
    ]
    selected = forms.SelectFromList.show(
        options,
        title=u"Filtrar/colorear por planta (BTZ)",
        button_name=u"Continuar",
        multiselect=False,
    )
    if not selected:
        return

    buckets = _build_planta_buckets(doc, elements)
    if not buckets:
        forms.alert(
            u"No hay elementos con BTZ cargado para colorear en esta vista.\nParámetro detectado: {0}".format(param_name_used),
            title=__title__,
            warn_icon=True,
        )
        return

    tx = Transaction(doc, u"BTZ | Colorear por planta")
    tx.Start()
    try:
        if selected == u"Quitar colores BTZ de la vista":
            cleared = 0
            for ids in buckets.values():
                for eid in ids:
                    _clear_override(view, eid)
                    cleared += 1
            tx.Commit()
            forms.alert(
                u"Colores BTZ removidos en vista activa.\nElementos limpiados: {0}".format(cleared),
                title=__title__,
            )
            return

        if selected == u"Colorear solo una planta":
            display_to_code = {}
            for code in sorted(buckets.keys()):
                display_to_code[_display_label_for_planta(code)] = code
            opt = forms.SelectFromList.show(
                sorted(display_to_code.keys()),
                title=u"Elegí planta a colorear",
                button_name=u"Aplicar",
                multiselect=False,
            )
            if not opt:
                tx.RollBack()
                return
            code = display_to_code.get(_u(opt), _u(opt))
            rgb = _color_for_planta(code)
            count = 0
            for eid in buckets.get(code, []):
                _set_color_override(view, eid, rgb)
                count += 1
            tx.Commit()
            forms.alert(
                u"Color aplicado.\nPlanta: {0}\nElementos coloreados: {1}\nParámetro usado: {2}".format(
                    _display_label_for_planta(code), count, param_name_used
                ),
                title=__title__,
            )
            return

        # Colorear todas las plantas
        total = 0
        lines = []
        for code in sorted(buckets.keys()):
            rgb = _color_for_planta(code)
            count = 0
            for eid in buckets[code]:
                _set_color_override(view, eid, rgb)
                count += 1
                total += 1
            lines.append(u"- {0}: {1} elementos".format(_display_label_for_planta(code), count))
        tx.Commit()
        forms.alert(
            u"Coloreado por planta aplicado.\nParámetro usado: {0}\nTotal: {1}\n\n{2}".format(
                param_name_used, total, u"\n".join(lines[:20])
            ),
            title=__title__,
        )
    except Exception as ex:
        tx.RollBack()
        forms.alert(u"Error al colorear:\n{0}".format(ex), title=__title__, warn_icon=True)


if __name__ == "__main__":
    main()
