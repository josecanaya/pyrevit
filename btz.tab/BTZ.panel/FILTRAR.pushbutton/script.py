# -*- coding: utf-8 -*-
"""
pyRevit - FILTRAR (BTZ jerarquico)
"""
from __future__ import print_function

__title__ = u"FILTRAR"
__doc__ = (
    u"Sitio, luego BTZ_Description_01..06; regla de igualdad por nivel. Lineas negras; relleno "
    u"solido de proyeccion/corte segun planta y nivel BTZ en la vista activa."
)
__author__ = u"btz.extension"

import re
import clr
clr.AddReference("RevitAPI")
clr.AddReference("System")
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from Autodesk.Revit.DB import (  # noqa: E402
    Color,
    ElementId,
    ElementParameterFilter,
    FillPatternElement,
    FilteredElementCollector,
    FilterRule,
    OverrideGraphicSettings,
    ParameterFilterElement,
    ParameterFilterRuleFactory,
    Transaction,
)
from System import Byte, Int64  # noqa: E402
from System.Collections.Generic import List  # noqa: E402
from System.Drawing import Font, Point, Size  # noqa: E402
from System.Windows.Forms import (  # noqa: E402
    AnchorStyles,
    Button,
    DialogResult,
    Form,
    FormBorderStyle,
    Label,
    ListBox,
    MessageBox,
    MessageBoxButtons,
    MessageBoxIcon,
    SelectionMode,
    FormStartPosition,
)
from pyrevit import forms, revit  # noqa: E402


BTZ_PARAMS = [
    u"BTZ_Description_01",
    u"BTZ_Description_02",
    u"BTZ_Description_03",
    u"BTZ_Description_04",
    u"BTZ_Description_05",
    u"BTZ_Description_06",
]
MAX_LEVEL_FOR_NOW = len(BTZ_PARAMS)

SITE_SAN_LORENZO = u"SAN LORENZO"
SITE_RICARDONE = u"RICARDONE"
# BTZ_Description_01 permitidos por sitio (comparacion sin distinguir mayusculas)
SITE_BTZ01_ALLOW = {
    SITE_SAN_LORENZO: frozenset([u"P10", u"TE", u"PP"]),
    SITE_RICARDONE: frozenset([u"PR"]),
}

# Filtros generados por esta herramienta (para limpiar la vista en cada corrida)
BTZ_FILTER_NAME_PREFIX = u"FILTRO_BTZ"

# Proyeccion/corte: siempre negro (el relleno lleva el color de planta / nivel BTZ)
FILTER_LINE_RGB = (0, 0, 0)

BASE_COLORS_BY_PLANTA = {
    u"P10": (52, 152, 219),   # azul
    u"PP": (46, 204, 113),    # verde
    u"TE": (255, 0, 0),       # rojo pleno (#FF0000); no aclarar por nivel (evita rosa)
    u"PR": (107, 63, 160),    # violeta Ricardone (IAPlano); niveles mas profundos = lavanda
}

ACEITE_SECTOR_CODE = u"TE-ACT-LGC-SECTOR ACEITE"
ACEITE_BOMBAS_GROUP_CODE = u"TE-ACT-LGC-BOMBAS DE ACEITE"
ACEITE_BOMBAS_SUBSECTORS = (
    u"TE-ACT-LGC-BOMBAS LECITINA",
    u"TE-ACT-SLA-SALA BMB ACEITE",
    u"TE-ACT-SLA-SALA BMB OSL",
    u"TE-BIO-SLA-SALA BMB TK400",
    u"TE-ACT-SLA-SALA BMB BAJO BARR",
)
ACEITE_BOMBAS_UNITS = frozenset(
    [
        u"TE-LCT-BMB-BO101", u"TE-LCT-BMB-BO102", u"TE-LCT-BMB-BO103", u"TE-LCT-BMB-BO104",
        u"TE-LCT-BMB-BO105", u"TE-LCT-BMB-BO107", u"TE-LCT-BMB-BO113",
        u"TE-ACT-BMB-BO106", u"TE-ACT-BMB-BO108", u"TE-ACT-BMB-BO109", u"TE-BIO-BMB-BO110",
        u"TE-BIO-BMB-BO111", u"TE-BIO-BMB-BO112",
        u"TE-ACT-BMB-BO510", u"TE-ACT-BMB-BO511", u"TE-ACT-BMB-BO512", u"TE-ACT-BMB-BO513",
        u"TE-BIO-BMB-BO414", u"TE-BIO-BMB-BO415", u"TE-FUEL-BMB-BO412", u"TE-FUEL-BMB-BO413",
    ]
)

# Agrupador navegable bajo TE > SECTOR ACEITE (codigos hoja reales; el BTZ_03 es sintetico como bombas)
ACEITE_ADMIN_GROUP_CODE = u"TE-ACT-LGC-SECTOR ADMINISTRATIVO"
ADM_SECTOR_EXCLUDE_FROM_GROUP = frozenset(
    [
        u"TE-ADM-EDF-BICICLETERO",
        u"TE-ADM-EDF-VESTUARIOS GRALES",
    ]
)
ADM_SECTOR_DIRECT_LEAVES_ORDERED = (
    u"TE-ADM-EDF-COCHERAS",
    u"TE-ADM-EDF-COMEDOR",
    u"TE-ADM-EDF-DPTO MEDICO",
    u"TE-ADM-EDF-OFICINAS",
    u"TE-ADM-EDF-PORTERIA",
    u"TE-TLL-LGC-OBRADOR ELECTRICO",
    u"TE-TLL-LGC-OBRADOR MECANICO",
)
ADM_SECTOR_DIRECT_LEAVES_U = frozenset(x.upper() for x in ADM_SECTOR_DIRECT_LEAVES_ORDERED)
TALLER_TERMINAL_PARENT = u"TE-TLL-TALLER TERM EMB"
TALLER_TERMINAL_UNITS = (
    u"TE-TLL-GNR- GENERADOR GNW73ER",
    u"TE-TLL-MLC- MLC TALLER",
)
TALLER_TERMINAL_UNITS_U = frozenset(x.upper() for x in TALLER_TERMINAL_UNITS)
CALIDAD_DPTO_PARENT = u"TE-CLD-LGC-DPTOCALIDAD"
CALIDAD_CALADO = u"TE-CLD-LGC-CALADO CAMIONES"
ADM_SECTOR_ORDER_BTZ04 = (TALLER_TERMINAL_PARENT,) + ADM_SECTOR_DIRECT_LEAVES_ORDERED + (CALIDAD_DPTO_PARENT,)


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


def _safe_strip(value):
    return _u(value).strip()


def _element_id_int(eid):
    """Revit 2024+: ElementId.Value; anteriores: IntegerValue."""
    if eid is None:
        return None
    try:
        return int(eid.IntegerValue)
    except Exception:
        try:
            return int(eid.Value)
        except Exception:
            return None


def _element_id_from_category_int(cid_int):
    """Evita ambiguedad ElementId(int) en Revit 2024+ (IronPython)."""
    n = int(cid_int)
    try:
        return ElementId(Int64(n))
    except Exception:
        return ElementId(n)


def _filter_rows_for_site(rows, site_key):
    allow = SITE_BTZ01_ALLOW.get(site_key)
    if not allow:
        return list(rows)
    allow_u = set(a.upper() for a in allow)
    out = []
    for row in rows:
        v = _safe_strip(row[0]).upper()
        if v in allow_u:
            out.append(row)
    return out


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
        etype = doc.GetElement(tid)
        if etype is None:
            return None
        return etype.LookupParameter(param_name)
    except Exception:
        return None


def _get_param_text(doc, element, param_name):
    p = _get_param_instance_or_type(doc, element, param_name)
    if p is None:
        return u"", None
    raw = _safe_strip(p.AsString() or p.AsValueString())
    return raw, p


def _sanitize_for_name(value):
    txt = _safe_strip(value).upper()
    txt = re.sub(r"[^A-Z0-9]+", "_", txt)
    txt = re.sub(r"_+", "_", txt).strip("_")
    return txt or u"VACIO"


def _extract_planta(value, fallback_parent=None):
    if fallback_parent:
        parent = _safe_strip(fallback_parent).upper()
        if parent:
            return parent
    txt = _safe_strip(value).upper()
    if not txt:
        return u""
    if u"-" in txt:
        return txt.split(u"-", 1)[0].strip()
    return txt


def _lighten_color(rgb, ratio):
    ratio = max(0.0, min(1.0, float(ratio)))
    r, g, b = rgb
    r2 = int(r + (255 - r) * ratio)
    g2 = int(g + (255 - g) * ratio)
    b2 = int(b + (255 - b) * ratio)
    return (r2, g2, b2)


def _color_for_selection(level_number, selected_value, parent_path):
    planta = u""
    if parent_path and len(parent_path) > 0:
        planta = _extract_planta(parent_path[0])
    if not planta:
        planta = _extract_planta(selected_value)

    base = BASE_COLORS_BY_PLANTA.get(planta, (127, 140, 141))
    if planta == u"TE":
        return base
    if level_number == 1:
        return base
    if level_number == 2:
        return _lighten_color(base, 0.18)
    if level_number == 3:
        return _lighten_color(base, 0.32)
    if level_number == 4:
        return _lighten_color(base, 0.40)
    if level_number == 5:
        return _lighten_color(base, 0.48)
    return _lighten_color(base, 0.55)


def _build_filter_name(level_number, parent_path, selected_value, site_label=None):
    safe_tokens = []
    if site_label:
        safe_tokens.append(_sanitize_for_name(site_label))
    for token in list(parent_path) + [selected_value]:
        safe_tokens.append(_sanitize_for_name(token))
    name = u"FILTRO_BTZ{0:02d}_{1}".format(level_number, u"_".join(safe_tokens))
    # limite defensivo para nombres largos
    if len(name) > 220:
        name = name[:220]
    return name


def _collect_rows_and_metadata(doc):
    rows = []
    param_meta = {}

    collector = FilteredElementCollector(doc).WhereElementIsNotElementType()
    for el in collector:
        category = getattr(el, "Category", None)
        cat_id = category.Id if category is not None else None

        values = []
        for pname in BTZ_PARAMS:
            txt, p = _get_param_text(doc, el, pname)
            values.append(txt)

            if p is not None:
                meta = param_meta.get(pname)
                if meta is None:
                    meta = {"param_id": p.Id, "cat_ids": set()}
                    param_meta[pname] = meta
                if meta.get("param_id") is None:
                    meta["param_id"] = p.Id
                if cat_id is not None and cat_id != ElementId.InvalidElementId:
                    cid = _element_id_int(cat_id)
                    if cid is not None:
                        meta["cat_ids"].add(cid)

        values = _normalize_aceite_bombas_row(values)
        values = _normalize_aceite_admin_sector_row(values)

        # Mantener filas con al menos BTZ_01 para iniciar jerarquia
        if values[0]:
            rows.append(values)

    return rows, param_meta


def _get_level_values(rows, level_index, parent_path):
    unique_vals = set()
    for row in rows:
        matches = True
        for i in range(len(parent_path)):
            if _safe_strip(row[i]) != _safe_strip(parent_path[i]):
                matches = False
                break
        if not matches:
            continue
        if level_index >= len(row):
            continue
        val = _safe_strip(row[level_index])
        if val:
            unique_vals.add(val)
    return _sort_level_values(level_index, parent_path, unique_vals)


def _sort_level_values(level_index, parent_path, unique_vals):
    vals = list(unique_vals)
    pl = [_safe_strip(p).upper() for p in parent_path]
    if (
        level_index == 3
        and len(pl) == 3
        and pl[0] == u"TE"
        and pl[1] == ACEITE_SECTOR_CODE.upper()
        and pl[2] == ACEITE_ADMIN_GROUP_CODE.upper()
    ):
        order_map = {k.upper(): i for i, k in enumerate(ADM_SECTOR_ORDER_BTZ04)}
        return sorted(
            vals,
            key=lambda x: (order_map.get(_safe_strip(x).upper(), 999), _u(x).upper()),
        )
    if (
        level_index == 4
        and len(pl) == 4
        and pl[0] == u"TE"
        and pl[1] == ACEITE_SECTOR_CODE.upper()
        and pl[2] == ACEITE_ADMIN_GROUP_CODE.upper()
        and pl[3] == _safe_strip(TALLER_TERMINAL_PARENT).upper()
    ):
        order_map = {k.upper(): i for i, k in enumerate(TALLER_TERMINAL_UNITS)}
        return sorted(
            vals,
            key=lambda x: (order_map.get(_safe_strip(x).upper(), 999), _u(x).upper()),
        )
    return sorted(vals, key=lambda x: _u(x).upper())


def _normalize_aceite_bombas_row(values):
    if len(values) < 2:
        return values
    if _safe_strip(values[0]).upper() != u"TE":
        return values
    if _safe_strip(values[1]).upper() != ACEITE_SECTOR_CODE:
        return values

    window = [_safe_strip(v).upper() for v in values[2:6]]
    sala = u""
    for v in window:
        if v in ACEITE_BOMBAS_SUBSECTORS:
            sala = v
            break
    if not sala:
        return values

    bomba = u""
    for v in window:
        if v in ACEITE_BOMBAS_UNITS:
            bomba = v
            break

    out = list(values)
    out[2] = ACEITE_BOMBAS_GROUP_CODE
    if len(out) > 3:
        out[3] = sala
    if len(out) > 4 and bomba:
        out[4] = bomba
    return out


def _pad6(row):
    out = list(row)
    while len(out) < 6:
        out.append(u"")
    return out[:6]


def _normalize_aceite_admin_sector_row(values):
    if len(values) < 2:
        return values
    if _safe_strip(values[0]).upper() != u"TE":
        return values

    if len(values) > 2 and _safe_strip(values[2]).upper() == ACEITE_ADMIN_GROUP_CODE:
        return _pad6(values)

    if _safe_strip(values[1]).upper() == ACEITE_SECTOR_CODE and len(values) > 2:
        if _safe_strip(values[2]).upper() == ACEITE_BOMBAS_GROUP_CODE:
            return values

    adm_edf = u"TE-ADM-LGC-EDIFICIOS VARIOS"
    cld = CALIDAD_DPTO_PARENT
    taller_u = _safe_strip(TALLER_TERMINAL_PARENT).upper()
    exclude_u = frozenset(x.upper() for x in ADM_SECTOR_EXCLUDE_FROM_GROUP)

    if _safe_strip(values[1]).upper() == adm_edf:
        if len(values) < 3 or not _safe_strip(values[2]):
            return values
        leaf_u = _safe_strip(values[2]).upper()
        if leaf_u in exclude_u:
            return values
        if leaf_u == taller_u:
            out = [u""] * 6
            out[0] = u"TE"
            out[1] = ACEITE_SECTOR_CODE
            out[2] = ACEITE_ADMIN_GROUP_CODE
            out[3] = TALLER_TERMINAL_PARENT
            if len(values) > 3 and _safe_strip(values[3]).upper() in TALLER_TERMINAL_UNITS_U:
                out[4] = _safe_strip(values[3])
            return _pad6(out)
        if leaf_u in ADM_SECTOR_DIRECT_LEAVES_U:
            out = [u""] * 6
            out[0] = u"TE"
            out[1] = ACEITE_SECTOR_CODE
            out[2] = ACEITE_ADMIN_GROUP_CODE
            out[3] = _safe_strip(values[2])
            return _pad6(out)

    if _safe_strip(values[1]).upper() == taller_u:
        if len(values) > 2 and _safe_strip(values[2]).upper() in TALLER_TERMINAL_UNITS_U:
            out = [u""] * 6
            out[0] = u"TE"
            out[1] = ACEITE_SECTOR_CODE
            out[2] = ACEITE_ADMIN_GROUP_CODE
            out[3] = TALLER_TERMINAL_PARENT
            out[4] = _safe_strip(values[2])
            return _pad6(out)

    if _safe_strip(values[1]).upper() == cld:
        if len(values) < 3 or not _safe_strip(values[2]):
            return values
        v2_u = _safe_strip(values[2]).upper()
        if v2_u == CALIDAD_CALADO.upper():
            out = [u""] * 6
            out[0] = u"TE"
            out[1] = ACEITE_SECTOR_CODE
            out[2] = ACEITE_ADMIN_GROUP_CODE
            out[3] = CALIDAD_DPTO_PARENT
            out[4] = _safe_strip(values[2])
            return _pad6(out)
        if v2_u == cld.upper():
            out = [u""] * 6
            out[0] = u"TE"
            out[1] = ACEITE_SECTOR_CODE
            out[2] = ACEITE_ADMIN_GROUP_CODE
            out[3] = _safe_strip(values[2])
            return _pad6(out)

    for i in range(len(values)):
        if _safe_strip(values[i]).upper() in TALLER_TERMINAL_UNITS_U:
            out = [u""] * 6
            out[0] = u"TE"
            out[1] = ACEITE_SECTOR_CODE
            out[2] = ACEITE_ADMIN_GROUP_CODE
            out[3] = TALLER_TERMINAL_PARENT
            out[4] = _safe_strip(values[i])
            return _pad6(out)

    return values


def _adm_sector_expand_specs():
    te = u"TE"
    ace = ACEITE_SECTOR_CODE
    adm = ACEITE_ADMIN_GROUP_CODE
    td = TALLER_TERMINAL_PARENT
    cq = CALIDAD_DPTO_PARENT
    specs = []
    for code in ADM_SECTOR_DIRECT_LEAVES_ORDERED:
        specs.append((4, BTZ_PARAMS[3], [te, ace, adm], code))
    for u in TALLER_TERMINAL_UNITS:
        specs.append((5, BTZ_PARAMS[4], [te, ace, adm, td], u))
    specs.append((5, BTZ_PARAMS[4], [te, ace, adm, cq], CALIDAD_CALADO))
    return specs


def _execute_apply_filters_multi(doc, view, site_label, specs, param_meta):
    for _level, param_name, _parent_path, _selected_value in specs:
        meta = param_meta.get(param_name)
        if not meta or meta.get("param_id") is None:
            return (
                False,
                None,
                u"No se pudo localizar el parametro '{0}' para crear filtros.".format(param_name),
            )
        if not meta.get("cat_ids"):
            return (
                False,
                None,
                u"No hay categorias compatibles con '{0}'.".format(param_name),
            )

    created_names = []
    reused_names = []
    cleared = 0

    tx = Transaction(doc, u"BTZ | Crear filtros jerarquicos")
    tx.Start()
    try:
        cleared = _remove_btz_filters_from_view(doc, view)
        existing_by_name = _get_existing_filters_by_name(doc)

        for level, param_name, parent_path, selected_value in specs:
            meta = param_meta.get(param_name)
            filter_name = _build_filter_name(level, parent_path, selected_value, site_label)
            filter_el, reused = _create_or_reuse_filter(
                doc=doc,
                existing_by_name=existing_by_name,
                filter_name=filter_name,
                param_id=meta["param_id"],
                category_ids=meta["cat_ids"],
                value_text=selected_value,
            )

            rgb = _color_for_selection(level, selected_value, parent_path)
            _apply_filter_to_view(doc, view, filter_el.Id, rgb)

            if reused:
                reused_names.append(filter_name)
            else:
                created_names.append(filter_name)

        tx.Commit()
    except Exception as ex:
        tx.RollBack()
        return (False, None, u"Error al crear/aplicar filtros:\n{0}".format(ex))

    return (
        True,
        {"cleared": cleared, "created": created_names, "reused": reused_names},
        None,
    )


class SitePickerForm(Form):
    def __init__(self):
        Form.__init__(self)
        self.site_choice = None
        self.overview_mode = False

        self.Text = u"FILTRAR | Sitio"
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MinimizeBox = False
        self.MaximizeBox = False
        self.ClientSize = Size(440, 268)

        lbl = Label()
        lbl.Location = Point(12, 12)
        lbl.Size = Size(410, 44)
        lbl.Text = (
            u"Elegi sitio. CONTINUAR: filtrar por niveles BTZ. "
            u"MUESTREO GENERAL: todos los BTZ_01 del sitio a la vez (mapa de zonas)."
        )
        self.Controls.Add(lbl)

        self.list_sites = ListBox()
        self.list_sites.Location = Point(12, 60)
        self.list_sites.Size = Size(410, 88)
        self.list_sites.Items.Add(SITE_SAN_LORENZO)
        self.list_sites.Items.Add(SITE_RICARDONE)
        self.list_sites.SelectedIndex = 0
        self.Controls.Add(self.list_sites)

        btn_overview = Button()
        btn_overview.Text = u"MUESTREO GENERAL (todas BTZ_01)"
        btn_overview.Location = Point(12, 156)
        btn_overview.Size = Size(410, 34)
        btn_overview.Click += self._on_overview
        self.Controls.Add(btn_overview)

        btn_ok = Button()
        btn_ok.Text = u"CONTINUAR"
        btn_ok.Location = Point(170, 200)
        btn_ok.Size = Size(120, 32)
        btn_ok.Click += self._on_ok
        self.Controls.Add(btn_ok)

        btn_cancel = Button()
        btn_cancel.Text = u"CANCELAR"
        btn_cancel.Location = Point(302, 200)
        btn_cancel.Size = Size(120, 32)
        btn_cancel.Click += self._on_cancel
        self.Controls.Add(btn_cancel)

    def _on_overview(self, sender, args):
        if self.list_sites.SelectedItem is None:
            return
        self.site_choice = _u(self.list_sites.SelectedItem)
        self.overview_mode = True
        self.DialogResult = DialogResult.OK
        self.Close()

    def _on_ok(self, sender, args):
        if self.list_sites.SelectedItem is None:
            return
        self.site_choice = _u(self.list_sites.SelectedItem)
        self.overview_mode = False
        self.DialogResult = DialogResult.OK
        self.Close()

    def _on_cancel(self, sender, args):
        self.DialogResult = DialogResult.Cancel
        self.Close()


class BTZHierarchyForm(Form):
    def __init__(self, rows, site_label):
        Form.__init__(self)
        self._rows = rows
        self._site_label = site_label
        self.path = []
        self.level_index = 0
        self.result_payload = None

        self.Text = u"FILTRAR | Navegacion BTZ"
        self.StartPosition = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MinimizeBox = False
        self.MaximizeBox = False
        self.ClientSize = Size(760, 540)

        self.lbl_title = Label()
        self.lbl_title.Location = Point(12, 12)
        self.lbl_title.Size = Size(730, 32)
        self.lbl_title.Font = Font(self.lbl_title.Font, self.lbl_title.Font.Style)
        self.Controls.Add(self.lbl_title)

        self.lbl_path = Label()
        self.lbl_path.Location = Point(12, 46)
        self.lbl_path.Size = Size(730, 24)
        self.Controls.Add(self.lbl_path)

        self.lbl_help = Label()
        self.lbl_help.Location = Point(12, 72)
        self.lbl_help.Size = Size(730, 24)
        self.lbl_help.Text = (
            u"Doble click: bajar de nivel (BTZ_01..06 si hay datos). "
            u"Seleccion multiple (Ctrl/Shift) + LISTO. Sin seleccion: aplica TODOS."
        )
        self.Controls.Add(self.lbl_help)

        self.list_values = ListBox()
        self.list_values.Location = Point(12, 100)
        self.list_values.Size = Size(730, 360)
        self.list_values.SelectionMode = SelectionMode.MultiExtended
        self.list_values.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Bottom
        self.list_values.DoubleClick += self._on_double_click
        self.Controls.Add(self.list_values)

        self.btn_back = Button()
        self.btn_back.Text = u"VOLVER"
        self.btn_back.Location = Point(12, 474)
        self.btn_back.Size = Size(120, 36)
        self.btn_back.Click += self._on_back
        self.Controls.Add(self.btn_back)

        self.btn_done = Button()
        self.btn_done.Text = u"LISTO"
        self.btn_done.Location = Point(498, 474)
        self.btn_done.Size = Size(120, 36)
        self.btn_done.Click += self._on_done
        self.Controls.Add(self.btn_done)

        self.btn_all = Button()
        self.btn_all.Text = u"TODOS"
        self.btn_all.Location = Point(370, 474)
        self.btn_all.Size = Size(120, 36)
        self.btn_all.Click += self._on_all
        self.Controls.Add(self.btn_all)

        self.btn_cancel = Button()
        self.btn_cancel.Text = u"CANCELAR"
        self.btn_cancel.Location = Point(622, 474)
        self.btn_cancel.Size = Size(120, 36)
        self.btn_cancel.Click += self._on_cancel
        self.Controls.Add(self.btn_cancel)

        self._refresh_ui()

    def _refresh_ui(self):
        level_number = self.level_index + 1
        self.lbl_title.Text = u"Nivel actual: BTZ_{0:02d}".format(level_number)
        if self.path:
            self.lbl_path.Text = u"Sitio: {0} | Ruta: {1}".format(
                self._site_label, u" > ".join(self.path)
            )
        else:
            self.lbl_path.Text = u"Sitio: {0} | Ruta: (raiz BTZ_01)".format(self._site_label)

        self.btn_back.Enabled = len(self.path) > 0
        values = _get_level_values(self._rows, self.level_index, self.path)

        self.list_values.Items.Clear()
        for v in values:
            self.list_values.Items.Add(v)

    def _on_double_click(self, sender, args):
        if self.level_index + 1 >= len(BTZ_PARAMS):
            return
        if self.list_values.SelectedItem is None:
            return

        selected_value = _u(self.list_values.SelectedItem)
        next_level_index = self.level_index + 1
        next_vals = _get_level_values(self._rows, next_level_index, self.path + [selected_value])
        if not next_vals:
            MessageBox.Show(
                u"No hay valores para BTZ_{0:02d} dentro de '{1}'.".format(next_level_index + 1, selected_value),
                u"FILTRAR",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information,
            )
            return

        self.path.append(selected_value)
        self.level_index = next_level_index
        self._refresh_ui()

    def _on_back(self, sender, args):
        if not self.path:
            return
        self.path.pop()
        self.level_index = max(0, self.level_index - 1)
        self._refresh_ui()

    def _on_done(self, sender, args):
        selected = []
        for item in self.list_values.SelectedItems:
            selected.append(_u(item))
        if not selected:
            for i in range(self.list_values.Items.Count):
                selected.append(_u(self.list_values.Items[i]))
            if not selected:
                MessageBox.Show(
                    u"No hay valores disponibles para aplicar en este nivel.",
                    u"FILTRAR",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning,
                )
                return

        self.result_payload = {
            "site_label": self._site_label,
            "level_number": self.level_index + 1,
            "param_name": BTZ_PARAMS[self.level_index],
            "parent_path": list(self.path),
            "selected_values": selected,
        }
        self.DialogResult = DialogResult.OK
        self.Close()

    def _on_all(self, sender, args):
        for i in range(self.list_values.Items.Count):
            self.list_values.SetSelected(i, True)

    def _on_cancel(self, sender, args):
        self.DialogResult = DialogResult.Cancel
        self.Close()


def _remove_btz_filters_from_view(doc, view):
    """Quita de la vista activa los filtros con nombre FILTRO_BTZ* (no borra la definicion del proyecto)."""
    removed = 0
    try:
        applied = list(view.GetFilters())
    except Exception:
        return 0
    for fid in applied:
        el = doc.GetElement(fid)
        if el is None:
            continue
        try:
            name = _u(el.Name)
        except Exception:
            continue
        if not name.startswith(BTZ_FILTER_NAME_PREFIX):
            continue
        try:
            view.RemoveFilter(fid)
            removed += 1
        except Exception:
            pass
    return removed


def _get_existing_filters_by_name(doc):
    by_name = {}
    for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
        by_name[_u(f.Name)] = f
    return by_name


def _build_revit_filter_rule(param_id, value_text):
    rule = None
    try:
        rule = ParameterFilterRuleFactory.CreateEqualsRule(param_id, value_text, False)
    except Exception:
        rule = ParameterFilterRuleFactory.CreateEqualsRule(param_id, value_text)
    return rule


def _create_or_reuse_filter(doc, existing_by_name, filter_name, param_id, category_ids, value_text):
    existing = existing_by_name.get(filter_name)
    if existing is not None:
        return existing, True

    cats = List[ElementId]()
    for cid_int in sorted(list(category_ids)):
        cats.Add(_element_id_from_category_int(cid_int))

    rule = _build_revit_filter_rule(param_id, value_text)
    wrapped_filter = ElementParameterFilter(rule)

    # Compatibilidad entre versiones de Revit API
    new_filter = None
    try:
        new_filter = ParameterFilterElement.Create(doc, filter_name, cats, wrapped_filter)
    except Exception:
        new_filter = ParameterFilterElement.Create(doc, filter_name, cats)
        try:
            new_filter.SetElementFilter(wrapped_filter)
        except Exception:
            rules = List[FilterRule]()
            rules.Add(rule)
            new_filter.SetRules(rules)

    existing_by_name[filter_name] = new_filter
    return new_filter, False


def _get_solid_fill_pattern_id(doc):
    try:
        sid = FillPatternElement.GetSolidFillPatternId()
        if sid is not None and sid != ElementId.InvalidElementId:
            return sid
    except Exception:
        pass
    try:
        for fpe in FilteredElementCollector(doc).OfClass(FillPatternElement):
            fp = fpe.GetFillPattern()
            if fp is not None and fp.IsSolidFill:
                return fpe.Id
    except Exception:
        pass
    return None


def _apply_filter_to_view(doc, view, filter_id, rgb):
    applied_ids = list(view.GetFilters())
    fid_target = _element_id_int(filter_id)
    already_applied = any(_element_id_int(fid) == fid_target for fid in applied_ids)
    if not already_applied:
        view.AddFilter(filter_id)

    r, g, b = rgb
    fill_color = Color(Byte(r), Byte(g), Byte(b))
    lr, lg, lb = FILTER_LINE_RGB
    line_color = Color(Byte(lr), Byte(lg), Byte(lb))
    ogs = OverrideGraphicSettings()
    ogs.SetProjectionLineColor(line_color)
    ogs.SetCutLineColor(line_color)

    solid_id = _get_solid_fill_pattern_id(doc)
    if solid_id is not None:
        try:
            ogs.SetSurfaceForegroundPatternId(solid_id)
            ogs.SetSurfaceForegroundPatternColor(fill_color)
        except Exception:
            pass
        try:
            ogs.SetCutForegroundPatternId(solid_id)
            ogs.SetCutForegroundPatternColor(fill_color)
        except Exception:
            pass
        try:
            ogs.SetCutFillPatternId(solid_id)
            ogs.SetCutFillPatternColor(fill_color)
        except Exception:
            pass

    view.SetFilterOverrides(filter_id, ogs)
    view.SetFilterVisibility(filter_id, True)


def _is_supported_active_view(view):
    try:
        if view.IsTemplate:
            return False
        if view.ViewType.ToString() == "Schedule":
            return False
        if view.ViewType.ToString() == "DrawingSheet":
            return False
    except Exception:
        pass
    return True


def _execute_apply_filters(doc, view, site_label, level_number, param_name, parent_path, selected_values, param_meta):
    """
    Quita FILTRO_BTZ* de la vista, crea/reutiliza filtros y los aplica con color.
    Retorna (ok, datos_dict o None, mensaje_error o None).
    """
    use_level = level_number
    use_param = param_name
    use_parent = list(parent_path)
    use_selected = list(selected_values)

    # Caso especial ACEITE: el agrupador BTZ_03 "BOMBAS DE ACEITE" representa 4 salas reales en BTZ_04.
    if (
        use_param == BTZ_PARAMS[2]
        and len(use_parent) >= 2
        and _safe_strip(use_parent[0]).upper() == u"TE"
        and _safe_strip(use_parent[1]).upper() == ACEITE_SECTOR_CODE
        and any(_safe_strip(v).upper() == ACEITE_BOMBAS_GROUP_CODE for v in use_selected)
    ):
        normalized_selected = [_safe_strip(v).upper() for v in use_selected]
        if len(normalized_selected) > 1:
            return (
                False,
                None,
                u"En SECTOR ACEITE, 'BOMBAS DE ACEITE' no se combina con otros nodos de ese nivel. "
                u"Aplicalo por separado o entra por doble click y filtra salas/bombas.",
            )
        use_level = 4
        use_param = BTZ_PARAMS[3]
        use_parent = use_parent + [ACEITE_BOMBAS_GROUP_CODE]
        use_selected = list(ACEITE_BOMBAS_SUBSECTORS)

    if (
        use_param == BTZ_PARAMS[2]
        and len(use_parent) >= 2
        and _safe_strip(use_parent[0]).upper() == u"TE"
        and _safe_strip(use_parent[1]).upper() == ACEITE_SECTOR_CODE
        and any(_safe_strip(v).upper() == ACEITE_ADMIN_GROUP_CODE for v in use_selected)
    ):
        normalized_selected = [_safe_strip(v).upper() for v in use_selected]
        if len(normalized_selected) > 1:
            return (
                False,
                None,
                u"En SECTOR ACEITE, 'SECTOR ADMINISTRATIVO' no se combina con otros nodos de ese nivel. "
                u"Aplicalo por separado o entra por doble click y filtra subsectores.",
            )
        return _execute_apply_filters_multi(doc, view, site_label, _adm_sector_expand_specs(), param_meta)

    meta = param_meta.get(use_param)
    if not meta or meta.get("param_id") is None:
        return (
            False,
            None,
            u"No se pudo localizar el parametro '{0}' para crear filtros.".format(param_name),
        )
    if not meta.get("cat_ids"):
        return (
            False,
            None,
            u"No hay categorias compatibles con '{0}'.".format(param_name),
        )

    created_names = []
    reused_names = []
    cleared = 0

    tx = Transaction(doc, u"BTZ | Crear filtros jerarquicos")
    tx.Start()
    try:
        cleared = _remove_btz_filters_from_view(doc, view)
        existing_by_name = _get_existing_filters_by_name(doc)

        for selected_value in use_selected:
            filter_name = _build_filter_name(use_level, use_parent, selected_value, site_label)
            filter_el, reused = _create_or_reuse_filter(
                doc=doc,
                existing_by_name=existing_by_name,
                filter_name=filter_name,
                param_id=meta["param_id"],
                category_ids=meta["cat_ids"],
                value_text=selected_value,
            )

            rgb = _color_for_selection(use_level, selected_value, use_parent)
            _apply_filter_to_view(doc, view, filter_el.Id, rgb)

            if reused:
                reused_names.append(filter_name)
            else:
                created_names.append(filter_name)

        tx.Commit()
    except Exception as ex:
        tx.RollBack()
        return (False, None, u"Error al crear/aplicar filtros:\n{0}".format(ex))

    return (
        True,
        {"cleared": cleared, "created": created_names, "reused": reused_names},
        None,
    )


def main():
    doc = revit.doc
    view = doc.ActiveView if doc else None
    if doc is None or view is None:
        forms.alert(u"No hay documento o vista activa.", title=__title__, warn_icon=True)
        return
    if not _is_supported_active_view(view):
        forms.alert(
            u"La vista activa no soporta filtros de vista (plantilla, plano o planilla).",
            title=__title__,
            warn_icon=True,
        )
        return

    rows, param_meta = _collect_rows_and_metadata(doc)
    if not rows:
        forms.alert(
            u"No se encontraron valores de BTZ_Description_01 en el modelo.",
            title=__title__,
            warn_icon=True,
        )
        return

    site_form = SitePickerForm()
    if site_form.ShowDialog() != DialogResult.OK or not site_form.site_choice:
        return
    site_label = site_form.site_choice
    overview_mode = bool(getattr(site_form, "overview_mode", False))

    rows = _filter_rows_for_site(rows, site_label)
    if not rows:
        forms.alert(
            u"No hay elementos BTZ para el sitio '{0}' (BTZ_01 esperado: {1}).".format(
                site_label,
                u", ".join(sorted(SITE_BTZ01_ALLOW.get(site_label, []))),
            ),
            title=__title__,
            warn_icon=True,
        )
        return

    if overview_mode:
        all_bt01 = _get_level_values(rows, 0, [])
        if not all_bt01:
            forms.alert(
                u"No hay valores BTZ_Description_01 para armar el muestreo en este sitio.",
                title=__title__,
                warn_icon=True,
            )
            return
        ok, data, err = _execute_apply_filters(
            doc,
            view,
            site_label,
            1,
            BTZ_PARAMS[0],
            [],
            all_bt01,
            param_meta,
        )
        if not ok:
            forms.alert(err, title=__title__, warn_icon=True)
            return
        cleared = data[u"cleared"]
        created_names = data[u"created"]
        reused_names = data[u"reused"]
        lines = []
        lines.append(u"Sitio: {0}".format(site_label or u""))
        lines.append(u"Modo: muestreo general — todas las BTZ_01 del sitio activas a la vez")
        lines.append(u"Vista activa: {0}".format(_u(view.Name)))
        lines.append(u"Filtros BTZ quitados de la vista antes de aplicar: {0}".format(cleared))
        lines.append(u"Filtros creados: {0}".format(len(created_names)))
        lines.append(u"Filtros reutilizados: {0}".format(len(reused_names)))
        if created_names:
            lines.append(u"")
            lines.append(u"Creados:")
            for name in created_names:
                lines.append(u"- {0}".format(name))
        if reused_names:
            lines.append(u"")
            lines.append(u"Reutilizados:")
            for name in reused_names:
                lines.append(u"- {0}".format(name))
        forms.alert(u"\n".join(lines), title=__title__)
        return

    dialog = BTZHierarchyForm(rows, site_label)
    result = dialog.ShowDialog()
    if result != DialogResult.OK or not dialog.result_payload:
        return

    payload = dialog.result_payload
    site_label = _u(payload.get("site_label"))
    level_number = int(payload.get("level_number", 0))
    param_name = _u(payload.get("param_name"))
    parent_path = payload.get("parent_path", []) or []
    selected_values = payload.get("selected_values", []) or []

    if level_number < 1 or level_number > MAX_LEVEL_FOR_NOW:
        forms.alert(u"Nivel seleccionado no valido.", title=__title__, warn_icon=True)
        return

    ok, data, err = _execute_apply_filters(
        doc,
        view,
        site_label,
        level_number,
        param_name,
        parent_path,
        selected_values,
        param_meta,
    )
    if not ok:
        forms.alert(err, title=__title__, warn_icon=True)
        return

    cleared = data[u"cleared"]
    created_names = data[u"created"]
    reused_names = data[u"reused"]

    lines = []
    lines.append(u"Sitio: {0}".format(site_label or u""))
    lines.append(u"Nivel BTZ aplicado: BTZ_{0:02d}".format(level_number))
    lines.append(u"Vista activa: {0}".format(_u(view.Name)))
    lines.append(u"Filtros BTZ quitados de la vista antes de aplicar: {0}".format(cleared))
    lines.append(u"Filtros creados: {0}".format(len(created_names)))
    lines.append(u"Filtros reutilizados: {0}".format(len(reused_names)))

    if created_names:
        lines.append(u"")
        lines.append(u"Creados:")
        for name in created_names:
            lines.append(u"- {0}".format(name))
    if reused_names:
        lines.append(u"")
        lines.append(u"Reutilizados:")
        for name in reused_names:
            lines.append(u"- {0}".format(name))

    forms.alert(u"\n".join(lines), title=__title__)


if __name__ == "__main__":
    main()
