# -*- coding: utf-8 -*-
"""
pyRevit - Exportar PNG por filtros BTZ (vista duplicada, mismo aspecto que la vista salvo el resaltado).
"""
from __future__ import print_function

__title__ = u"EXPORTAR\nBTZ PNG"
__doc__ = (
    u"Un PNG por nodo BTZ_02/03/04: vista base solo 3D, orientación isométrica y el mismo estilo visual que la vista "
    u"que elijas (p. ej. sombreado), sin forzar línea oculta. Solo el filtro lleva relleno TE/PP/P10/PR y líneas negras gruesas."
)
__author__ = u"btz.extension"

import os
import re
import shutil
import clr
import uuid

clr.AddReference("RevitAPI")
clr.AddReference("System")

from Autodesk.Revit.DB import (  # noqa: E402
    Color,
    DisplayStyle,
    ElementId,
    ElementParameterFilter,
    ExportRange,
    FillPatternElement,
    FilteredElementCollector,
    FilterRule,
    ImageExportOptions,
    ImageFileType,
    ImageResolution,
    OverrideGraphicSettings,
    ParameterFilterElement,
    ParameterFilterRuleFactory,
    Transaction,
    View,
    View3D,
    ViewDetailLevel,
    ViewDuplicateOption,
    ViewOrientation3D,
    ZoomType,
)
from System import Byte, Int64  # noqa: E402
from System.Collections.Generic import List  # noqa: E402
from pyrevit import forms, revit  # noqa: E402


# Lineas del elemento filtrado: siempre negras
HIGHLIGHT_LINE_RGB = (0, 0, 0)

# Relleno segun BTZ_Description_01 (token en el nombre FILTRO_BTZ**_... del boton FILTRAR)
HIGHLIGHT_FILL_BY_BTZ01 = {
    u"TE": (220, 0, 0),       # rojo intenso (terminal)
    u"PP": (46, 204, 113),   # verde (planta a puerto)
    u"P10": (135, 206, 250), # celeste / azul cielo (planta 1000)
    u"PR": (107, 63, 160),   # violeta Ricardone (misma base que FILTRAR)
}
KNOWN_BTZ01_CODES = frozenset(HIGHLIGHT_FILL_BY_BTZ01.keys())

# Grosor lineas del filtro (1-16 en Revit; mas alto = mas visible en PNG)
HIGHLIGHT_LINE_WEIGHT = 7

BTZ_PARAMS = [
    u"BTZ_Description_01",
    u"BTZ_Description_02",
    u"BTZ_Description_03",
    u"BTZ_Description_04",
    u"BTZ_Description_05",
    u"BTZ_Description_06",
]

SITE_SAN_LORENZO = u"SAN LORENZO"
SITE_RICARDONE = u"RICARDONE"
SITE_BTZ01_ALLOW = {
    SITE_SAN_LORENZO: frozenset([u"P10", u"TE", u"PP"]),
    SITE_RICARDONE: frozenset([u"PR"]),
}

# Vista base por nombre (None = elegir en UI)
DEFAULT_BASE_VIEW_NAME = None

# Carpeta bajo la raiz de la extension: btz.extension/public/exports_btz_png/
_REL_PUBLIC = os.path.join(u"public", u"exports_btz_png")


def _u(value):
    if value is None:
        return u""
    try:
        return unicode(value)  # noqa: F821
    except Exception:
        try:
            return str(value)
        except Exception:
            return u""


def _safe_strip(s):
    return _u(s).strip()


def _element_id_int(eid):
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
    n = int(cid_int)
    try:
        return ElementId(Int64(n))
    except Exception:
        return ElementId(n)


def _extension_root_dir():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), u"..", u"..", u".."))


def _output_dir():
    return os.path.join(_extension_root_dir(), _REL_PUBLIC.replace(u"/", os.sep))


def _sanitize_file_stem(value):
    txt = _safe_strip(value).upper()
    txt = re.sub(r"[^A-Z0-9._-]+", u"_", txt)
    txt = re.sub(r"_+", u"_", txt).strip(u"_")
    return txt or u"VACIO"


def _parse_filter_level(name):
    m = re.match(r"^FILTRO_BTZ(\d{2})_", _u(name), re.IGNORECASE)
    if not m:
        return None
    return int(m.group(1))


def _planta_btz01_from_filter_name(filter_el_name):
    """
    El nombre del filtro incluye la ruta sanitizada; el codigo de planta (BTZ_01) aparece
    como token P10, PP, TE o PR (misma convencion que FILTRAR).
    """
    body = _u(filter_el_name)
    m = re.match(r"^FILTRO_BTZ\d{2}_", body, re.IGNORECASE)
    if not m:
        return None
    rest = body[len(m.group(0)) :]
    for part in rest.split(u"_"):
        if part in KNOWN_BTZ01_CODES:
            return part
    return None


def _highlight_fill_rgb_for_filter(filter_el_name):
    planta = _planta_btz01_from_filter_name(filter_el_name)
    if planta and planta in HIGHLIGHT_FILL_BY_BTZ01:
        return HIGHLIGHT_FILL_BY_BTZ01[planta]
    return HIGHLIGHT_FILL_BY_BTZ01[u"TE"]


def _png_filename(filter_el_name, level):
    body = _u(filter_el_name)
    prefix = u"FILTRO_BTZ{0:02d}_".format(level)
    if body.upper().startswith(prefix.upper()):
        body = body[len(prefix) :]
    stem = _sanitize_file_stem(body)
    name = u"BTZ{0:02d}_{1}.png".format(level, stem)
    if len(name) > 200:
        name = name[:200]
    return name


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


def _collect_3d_views(doc):
    """Solo vistas 3D (no plantilla): el PNG masivo debe ser axonometrico, no planta."""
    out = []
    for v in FilteredElementCollector(doc).OfClass(View3D):
        if v.IsTemplate:
            continue
        out.append(v)
    out.sort(key=lambda x: _u(x.Name).upper())
    return out


def _pick_base_view(doc):
    if DEFAULT_BASE_VIEW_NAME:
        target = _safe_strip(DEFAULT_BASE_VIEW_NAME)
        for v in _collect_3d_views(doc):
            if _safe_strip(v.Name) == target:
                return v
        forms.alert(
            u"No se encontro la vista base 3D configurada: '{0}' (debe ser View3D, no planta).".format(target),
            title=__title__,
            warn_icon=True,
        )
        return None

    views = _collect_3d_views(doc)
    if not views:
        forms.alert(
            u"No hay vistas 3D en el proyecto (crea una vista 3D con encuadre/isometria y volve a intentar).",
            title=__title__,
            warn_icon=True,
        )
        return None
    labels = [_u(v.Name) for v in views]
    pick = forms.SelectFromList.show(
        labels,
        title=u"Vista 3D base (se duplica por filtro; isometría; PNG con el mismo estilo visual, p. ej. sombreado)",
        button_name=u"Usar",
        multiselect=False,
    )
    if not pick:
        return None
    for v in views:
        if _u(v.Name) == _u(pick):
            return v
    return None


def _list_btz_parameter_filters(doc, levels):
    found = []
    for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
        lvl = _parse_filter_level(f.Name)
        if lvl is None or lvl not in levels:
            continue
        found.append((f, lvl))
    found.sort(key=lambda x: (_u(x[0].Name).upper()))
    return found


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


def _collect_rows_and_param_meta(doc):
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
        if values[0]:
            rows.append(values)
    return rows, param_meta


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


def _sanitize_for_filter_name(value):
    txt = _safe_strip(value).upper()
    txt = re.sub(r"[^A-Z0-9]+", u"_", txt)
    txt = re.sub(r"_+", u"_", txt).strip(u"_")
    return txt or u"VACIO"


def _build_filter_name(level_number, parent_path, selected_value, site_label=None):
    safe_tokens = []
    if site_label:
        safe_tokens.append(_sanitize_for_filter_name(site_label))
    for token in list(parent_path) + [selected_value]:
        safe_tokens.append(_sanitize_for_filter_name(token))
    name = u"FILTRO_BTZ{0:02d}_{1}".format(level_number, u"_".join(safe_tokens))
    if len(name) > 220:
        name = name[:220]
    return name


def _get_existing_filters_by_name(doc):
    by_name = {}
    for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
        by_name[_u(f.Name)] = f
    return by_name


def _build_revit_filter_rule(param_id, value_text):
    try:
        return ParameterFilterRuleFactory.CreateEqualsRule(param_id, value_text, False)
    except Exception:
        return ParameterFilterRuleFactory.CreateEqualsRule(param_id, value_text)


def _create_or_reuse_filter(doc, existing_by_name, filter_name, param_id, category_ids, value_text):
    existing = existing_by_name.get(filter_name)
    if existing is not None:
        return existing, True
    cats = List[ElementId]()
    for cid_int in sorted(list(category_ids)):
        cats.Add(_element_id_from_category_int(cid_int))
    rule = _build_revit_filter_rule(param_id, value_text)
    wrapped_filter = ElementParameterFilter(rule)
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


def _unique_rows_for_level(rows, level_index):
    """
    level_index 1 -> BTZ_02 (parent path [b1])
    level_index 2 -> BTZ_03 (parent path [b1,b2])
    level_index 3 -> BTZ_04 (parent path [b1,b2,b3])
    """
    seen = set()
    combos = []
    for row in rows:
        if level_index + 1 > len(row):
            continue
        parent = tuple(_safe_strip(row[i]) for i in range(level_index))
        val = _safe_strip(row[level_index])
        if not val or not all(parent):
            continue
        key = parent + (val,)
        if key in seen:
            continue
        seen.add(key)
        combos.append((list(parent), val))
    return combos


def _ensure_filters_for_export(doc, rows, levels, site_label, existing_by_name, param_meta):
    """
    Crea filtros con la misma convencion de nombres que FILTRAR (sin modificar ese script).
    """
    for lvl in levels:
        param_name = BTZ_PARAMS[lvl - 1]
        meta = param_meta.get(param_name)
        if not meta or not meta.get("param_id") or not meta.get("cat_ids"):
            continue
        idx = lvl - 1
        combos = _unique_rows_for_level(rows, idx)
        for parent_path, val in combos:
            fname = _build_filter_name(lvl, parent_path, val, site_label)
            _create_or_reuse_filter(
                doc,
                existing_by_name,
                fname,
                meta["param_id"],
                meta["cat_ids"],
                val,
            )


def _clear_view_filters(view):
    try:
        for fid in list(view.GetFilters()):
            view.RemoveFilter(fid)
    except Exception:
        pass


def _prepare_export_view_3d(view, doc, style_source_view):
    """
    Isometría. El estilo (sombreado, línea oculta, realista, etc.) se toma de la vista base que elijiste
    (la duplicata ya hereda el DisplayStyle; lo reasignamos desde la base por si en el futuro cambia el flujo).
    """
    if not isinstance(view, View3D):
        return
    try:
        try:
            ori = ViewOrientation3D.CreateByName(doc, u"Isometric")
            if ori is not None:
                view.SetOrientation(ori)
        except Exception:
            pass
        if style_source_view is not None and isinstance(style_source_view, View3D):
            try:
                view.DisplayStyle = style_source_view.DisplayStyle
            except Exception:
                try:
                    view.DisplayStyle = DisplayStyle.Shading
                except Exception:
                    pass
            try:
                view.DetailLevel = style_source_view.DetailLevel
            except Exception:
                try:
                    view.DetailLevel = ViewDetailLevel.Fine
                except Exception:
                    pass
        else:
            try:
                view.DisplayStyle = DisplayStyle.Shading
            except Exception:
                pass
            try:
                view.DetailLevel = ViewDetailLevel.Fine
            except Exception:
                pass
    except Exception:
        pass


def _apply_filter_highlight_override(view, doc, filter_id, solid_id, fill_rgb):
    r, g, b = fill_rgb
    lr, lg, lb = HIGHLIGHT_LINE_RGB
    fill = Color(Byte(r), Byte(g), Byte(b))
    line = Color(Byte(lr), Byte(lg), Byte(lb))
    ogs = OverrideGraphicSettings()
    ogs.SetHalftone(False)
    ogs.SetProjectionLineColor(line)
    ogs.SetCutLineColor(line)
    try:
        ogs.SetProjectionLineWeight(HIGHLIGHT_LINE_WEIGHT)
    except Exception:
        try:
            ogs.ProjectionLineWeight = HIGHLIGHT_LINE_WEIGHT
        except Exception:
            pass
    try:
        ogs.SetCutLineWeight(HIGHLIGHT_LINE_WEIGHT)
    except Exception:
        try:
            ogs.CutLineWeight = HIGHLIGHT_LINE_WEIGHT
        except Exception:
            pass
    if solid_id is not None:
        try:
            ogs.SetSurfaceForegroundPatternId(solid_id)
            ogs.SetSurfaceForegroundPatternColor(fill)
        except Exception:
            pass
        try:
            ogs.SetCutForegroundPatternId(solid_id)
            ogs.SetCutForegroundPatternColor(fill)
        except Exception:
            pass
        try:
            ogs.SetCutFillPatternId(solid_id)
            ogs.SetCutFillPatternColor(fill)
        except Exception:
            pass
    view.AddFilter(filter_id)
    view.SetFilterOverrides(filter_id, ogs)
    view.SetFilterVisibility(filter_id, True)


def _unique_duplicate_view_name(doc, base_stem):
    stem = base_stem[: 120] if len(base_stem) > 120 else base_stem
    name = stem
    n = 1
    existing = {_u(v.Name).upper() for v in FilteredElementCollector(doc).OfClass(View)}
    while _u(name).upper() in existing:
        n += 1
        suffix = u"_{0}".format(n)
        name = (stem[: 120 - len(suffix)] + suffix) if len(stem) + len(suffix) > 120 else stem + suffix
    return name


def _export_view_to_png(doc, view, dest_png_path):
    folder = os.path.join(os.path.dirname(dest_png_path), u"_tmp_" + _u(uuid.uuid4().hex)[:10])
    os.makedirs(folder)
    trail = folder
    if not trail.endswith(os.sep):
        trail += os.sep

    opts = ImageExportOptions()
    opts.FilePath = trail
    opts.ExportRange = ExportRange.SetOfViews
    ids = List[ElementId]()
    ids.Add(view.Id)
    opts.SetViewsAndSheets(ids)
    try:
        opts.ImageResolution = ImageResolution.DPI_300
    except Exception:
        try:
            opts.ImageResolution = ImageResolution.DPI_150
        except Exception:
            pass
    try:
        opts.PixelSize = 3840
    except Exception:
        pass
    try:
        opts.HLRandWFViewsFileType = ImageFileType.PNG
        opts.ShadowViewsFileType = ImageFileType.PNG
    except Exception:
        pass
    try:
        opts.ZoomType = ZoomType.FitToPage
    except Exception:
        pass

    try:
        doc.Regenerate()
    except Exception:
        pass

    doc.ExportImage(opts)

    pngs = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(u".png"):
                pngs.append(os.path.join(root, f))
    if not pngs:
        shutil.rmtree(folder, ignore_errors=True)
        return False, u"No se genero ningun PNG (ExportImage)."

    pngs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    src = pngs[0]
    try:
        if os.path.isfile(dest_png_path):
            os.remove(dest_png_path)
        shutil.move(src, dest_png_path)
    except Exception as ex:
        shutil.rmtree(folder, ignore_errors=True)
        return False, _u(ex)

    shutil.rmtree(folder, ignore_errors=True)
    return True, u""


def _extract_valor_btz(filter_name, level):
    body = _u(filter_name)
    prefix = u"FILTRO_BTZ{0:02d}_".format(level)
    if body.upper().startswith(prefix.upper()):
        body = body[len(prefix) :]
    parts = body.split(u"_")
    return parts[-1] if parts else body


def _write_summary_csv(csv_path, fieldnames, summary_rows):
    try:
        import codecs
    except Exception:
        codecs = None
    lines = []
    header = u",".join(u'"{0}"'.format(fn.replace(u'"', u'""')) for fn in fieldnames)
    lines.append(header)
    for r in summary_rows:
        cells = []
        for k in fieldnames:
            v = _u(r.get(k, u"")).replace(u'"', u'""')
            cells.append(u'"{0}"'.format(v))
        lines.append(u",".join(cells))
    text = u"\n".join(lines) + u"\n"
    if codecs:
        with codecs.open(csv_path, u"w", encoding=u"utf-8-sig") as f:
            f.write(text)
    else:
        with open(csv_path, u"w") as f:
            f.write(text.encode(u"utf-8"))


def main():
    doc = revit.doc
    if doc is None or doc.IsFamilyDocument:
        forms.alert(u"Abri un proyecto (.rvt), no una familia.", title=__title__, warn_icon=True)
        return

    base_view = _pick_base_view(doc)
    if base_view is None:
        return

    level_choices = [
        (u"Solo BTZ_Description_03", [3]),
        (u"Solo BTZ_Description_04", [4]),
        (u"BTZ_03 y BTZ_04 (tanques, celdas, subdetalle)", [3, 4]),
        (u"BTZ_02 y BTZ_03", [2, 3]),
        (u"BTZ_02, BTZ_03 y BTZ_04 (recomendado: torre, tanques, todo)", [2, 3, 4]),
    ]
    level_labels = [t[0] for t in level_choices]
    level_pick = forms.SelectFromList.show(
        level_labels,
        title=u"Niveles BTZ a exportar (04 = tanques, torre manipuleo, etc.)",
        button_name=u"OK",
        multiselect=False,
    )
    if not level_pick:
        return
    levels = None
    for label, lv in level_choices:
        if level_pick == label:
            levels = lv
            break
    if not levels:
        levels = [3]

    mode = forms.SelectFromList.show(
        [
            u"Todos los nodos del sitio (recomendado): un PNG por cada BTZ del modelo",
            u"Solo filtros FILTRO_BTZ ya existentes en el proyecto",
        ],
        title=u"Alcance",
        button_name=u"OK",
        multiselect=False,
    )
    if not mode:
        return
    use_all_nodes = mode.startswith(u"Todos")

    site_label = None
    if use_all_nodes:
        sp = forms.SelectFromList.show(
            [SITE_SAN_LORENZO, SITE_RICARDONE],
            title=u"Sitio (nombres de filtro iguales que FILTRAR)",
            button_name=u"OK",
            multiselect=False,
        )
        if not sp:
            return
        site_label = _u(sp)

    out_root = _output_dir()
    try:
        os.makedirs(out_root)
    except Exception:
        pass

    rows, param_meta = _collect_rows_and_param_meta(doc)
    if site_label:
        rows = _filter_rows_for_site(rows, site_label)

    existing_by_name = _get_existing_filters_by_name(doc)
    filters_to_export = []

    if use_all_nodes:
        if not rows:
            forms.alert(
                u"No hay elementos BTZ para el sitio elegido.",
                title=__title__,
                warn_icon=True,
            )
            return
        txg = Transaction(doc, u"BTZ PNG | Crear filtros para todos los nodos")
        txg.Start()
        try:
            _ensure_filters_for_export(doc, rows, levels, site_label, existing_by_name, param_meta)
            txg.Commit()
        except Exception as ex:
            txg.RollBack()
            forms.alert(_u(ex), title=__title__, warn_icon=True)
            return
        existing_by_name = _get_existing_filters_by_name(doc)
        for lvl in levels:
            idx = lvl - 1
            for parent_path, val in _unique_rows_for_level(rows, idx):
                fname = _build_filter_name(lvl, parent_path, val, site_label)
                fe = existing_by_name.get(fname)
                if fe is not None:
                    filters_to_export.append((fe, lvl, fname))
    else:
        for fe, lvl in _list_btz_parameter_filters(doc, levels):
            filters_to_export.append((fe, lvl, _u(fe.Name)))

    if not filters_to_export:
        forms.alert(
            u"No hay nada que exportar. Si elegiste solo filtros existentes, crea algunos con FILTRAR. "
            u"Si elegiste todos los nodos, revisa sitio y datos BTZ.",
            title=__title__,
            warn_icon=True,
        )
        return

    csv_path = os.path.join(out_root, u"export_summary.csv")
    summary_rows = []

    solid_id = _get_solid_fill_pattern_id(doc)
    if solid_id is None:
        forms.alert(
            u"No se encontro patron de relleno solido en el proyecto. "
            u"Los PNG pueden salir sin relleno de superficie.",
            title=__title__,
            warn_icon=True,
        )

    for fe, lvl, fname in filters_to_export:
        fname = _u(fname)
        png_name = _png_filename(fname, lvl)
        dest_png = os.path.join(out_root, png_name)
        valor = _extract_valor_btz(fname, lvl)
        row_csv = {
            u"nivel_btz": u"{0:02d}".format(lvl),
            u"valor_btz": valor,
            u"nombre_vista": u"",
            u"nombre_filtro": fname,
            u"archivo_png": png_name,
            u"estado": u"",
            u"mensaje": u"",
        }

        dup = None
        dup_id = None
        tx = None
        try:
            tx = Transaction(doc, u"BTZ PNG | Duplicar y preparar vista")
            tx.Start()
            dup_id = base_view.Duplicate(ViewDuplicateOption.Duplicate)
            dup = doc.GetElement(dup_id)
            if dup is None:
                raise Exception(u"No se pudo duplicar la vista base.")

            dup_name = _unique_duplicate_view_name(doc, u"EXP_" + _sanitize_file_stem(png_name.replace(u".png", u"")))
            try:
                dup.Name = dup_name
            except Exception:
                pass
            row_csv[u"nombre_vista"] = _u(dup.Name)

            _clear_view_filters(dup)
            _prepare_export_view_3d(dup, doc, base_view)
            _apply_filter_highlight_override(
                dup,
                doc,
                fe.Id,
                solid_id,
                _highlight_fill_rgb_for_filter(fname),
            )

            tx.Commit()
        except Exception as ex:
            try:
                if tx is not None:
                    tx.RollBack()
            except Exception:
                pass
            row_csv[u"estado"] = u"error"
            row_csv[u"mensaje"] = _u(ex)
            summary_rows.append(row_csv)
            continue

        try:
            doc.Regenerate()
        except Exception:
            pass

        ok_exp, msg_exp = _export_view_to_png(doc, dup, dest_png)
        if ok_exp:
            row_csv[u"estado"] = u"ok"
            row_csv[u"mensaje"] = u""
        else:
            row_csv[u"estado"] = u"error_export"
            row_csv[u"mensaje"] = msg_exp

        summary_rows.append(row_csv)

        txd = None
        try:
            txd = Transaction(doc, u"BTZ PNG | Eliminar vista temporal")
            txd.Start()
            doc.Delete(dup_id)
            txd.Commit()
        except Exception as ex_del:
            try:
                if txd is not None:
                    txd.RollBack()
            except Exception:
                pass
            row_csv[u"mensaje"] = (row_csv[u"mensaje"] + u" | " if row_csv[u"mensaje"] else u"") + _u(
                ex_del
            )

    fieldnames = [u"nivel_btz", u"valor_btz", u"nombre_vista", u"nombre_filtro", u"archivo_png", u"estado", u"mensaje"]
    try:
        _write_summary_csv(csv_path, fieldnames, summary_rows)
    except Exception as ex:
        forms.alert(u"No se pudo escribir el CSV:\n{0}".format(ex), title=__title__, warn_icon=True)

    n_ok = sum(1 for r in summary_rows if r.get(u"estado") == u"ok")
    forms.alert(
        u"Listo.\nPNG OK: {0} / {1}\nCarpeta:\n{2}\nCSV:\n{3}".format(
            n_ok,
            len(summary_rows),
            out_root,
            csv_path,
        ),
        title=__title__,
    )


if __name__ == u"__main__":
    main()
