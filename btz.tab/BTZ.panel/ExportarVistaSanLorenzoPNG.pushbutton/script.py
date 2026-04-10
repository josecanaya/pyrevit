# -*- coding: utf-8 -*-
"""
Exporta la vista activa en un PNG de alta calidad con estilo diagrama (terreno verde menta, modelo blanco, lineas negras).
"""
from __future__ import print_function

__title__ = u"Exportar vista SL"
__doc__ = (
    u"Duplica la vista, pone verde menta solo topografia/vias (pocas llamadas API, estable en Revit 2026). "
    u"El resto queda como lo ves en Revit. PNG en carpeta San Lorenzo."
)
__author__ = u"btz.extension"

import datetime
import os
import re
import shutil
import clr
import uuid

clr.AddReference("RevitAPI")
clr.AddReference("System")

from Autodesk.Revit.DB import (  # noqa: E402
    BuiltInCategory,
    Category,
    Color,
    ElementId,
    ExportRange,
    FillPatternElement,
    FilteredElementCollector,
    ImageExportOptions,
    ImageFileType,
    ImageResolution,
    OverrideGraphicSettings,
    Transaction,
    View,
    ViewDuplicateOption,
    ZoomType,
)
from System import Byte  # noqa: E402
from System.Collections.Generic import List  # noqa: E402
from pyrevit import forms, revit  # noqa: E402


# Carpeta fija pedida por el usuario
OUTPUT_DIR = u"C:/Users/Usuario/Desktop/Jose/maintence/activos dibujables/San Lorenzo"

# Solo topografia/vias: el bucle global por TODAS las categorias blancas tumba Revit 2026 en modelos grandes.
RGB_TOPO_MINT = (225, 245, 225)
RGB_LINE_BLACK = (0, 0, 0)
LINE_WEIGHT_DIAGRAM = 1


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


def _site_green_category_ids(doc):
    """Topografia y vias para terreno verde menta (como plano de sitio)."""
    out = []
    for bic in (BuiltInCategory.OST_Topography, BuiltInCategory.OST_Roads):
        try:
            c = Category.GetCategory(doc, bic)
            if c is not None:
                out.append(c.Id)
        except Exception:
            pass
    return out


def _apply_site_green_only(view, doc, solid_id):
    """
    Solo 1-2 categorias (topografia, vias). Evita cientos de SetCategoryOverrides que cierran Revit 2026.
    """
    black = Color(Byte(RGB_LINE_BLACK[0]), Byte(RGB_LINE_BLACK[1]), Byte(RGB_LINE_BLACK[2]))
    mint = Color(Byte(RGB_TOPO_MINT[0]), Byte(RGB_TOPO_MINT[1]), Byte(RGB_TOPO_MINT[2]))

    for gid in _site_green_category_ids(doc):
        try:
            if gid is None or gid == ElementId.InvalidElementId:
                continue
            ogs = OverrideGraphicSettings()
            ogs.SetHalftone(False)
            ogs.SetProjectionLineColor(black)
            ogs.SetCutLineColor(black)
            try:
                ogs.SetProjectionLineWeight(LINE_WEIGHT_DIAGRAM)
            except Exception:
                pass
            try:
                ogs.SetCutLineWeight(LINE_WEIGHT_DIAGRAM)
            except Exception:
                pass
            if solid_id is not None:
                try:
                    ogs.SetSurfaceForegroundPatternId(solid_id)
                    ogs.SetSurfaceForegroundPatternColor(mint)
                except Exception:
                    pass
            view.SetCategoryOverrides(gid, ogs)
        except Exception:
            continue


# Revit rechaza en View.Name: \ : { } [ ] | ; < > ? ` ~ y similares
_REVIT_VIEW_NAME_FORBIDDEN = re.compile(
    ur'[\\{}[\]|;<>?`~:#\t\n\r\x00-\x1f\u2018\u2019\u201c\u201d]'
)


def _sanitize_revit_view_name(name, max_len=100):
    s = _u(name).strip()
    s = _REVIT_VIEW_NAME_FORBIDDEN.sub(u"_", s)
    s = re.sub(ur"[\"']", u"_", s)
    s = re.sub(ur"[>]{2,}", u"_", s)
    s = re.sub(ur"[<>=]{1,}", u"_", s)
    s = re.sub(ur"\s+", u"_", s)
    s = re.sub(ur"_+", u"_", s).strip(u"_")
    if not s:
        s = u"VistaExport"
    if len(s) > max_len:
        s = s[:max_len].rstrip(u"_")
    return s


def _sanitize_filename_stem(name):
    s = _sanitize_revit_view_name(name, max_len=120)
    s = re.sub(ur'[<>:"/\\|?*]', u"_", s)
    return s[:120] if len(s) > 120 else s


def _unique_temp_view_name(doc, base):
    stem = _sanitize_revit_view_name(base, max_len=100)
    stem = stem[:100] if len(stem) > 100 else stem
    name = stem
    n = 1
    existing = {_u(v.Name).upper() for v in FilteredElementCollector(doc).OfClass(View)}
    while _u(name).upper() in existing:
        n += 1
        suffix = u"_{0}".format(n)
        name = (stem[: 100 - len(suffix)] + suffix) if len(stem) + len(suffix) > 100 else stem + suffix
    return name


def _export_view_highres_png(doc, view, dest_png_path):
    """
    Empieza por resoluciones moderadas (Revit 2026 + 3D grande = crash con 3k-4k px).
    """
    pixel_try = (2400, 1920, 1600, 1280)
    last_err = u""
    for px in pixel_try:
        ok, err = _export_view_png_once(doc, view, dest_png_path, px)
        if ok:
            return True, u""
        last_err = err
    return False, last_err or u"ExportImage fallo"


def _export_view_png_once(doc, view, dest_png_path, pixel_size):
    folder = os.path.join(os.path.dirname(dest_png_path), u"_tmp_exp_" + _u(uuid.uuid4().hex)[:12])
    if not os.path.isdir(folder):
        os.makedirs(folder)
    trail = folder if folder.endswith(os.sep) else folder + os.sep

    opts = ImageExportOptions()
    opts.FilePath = trail
    opts.ExportRange = ExportRange.SetOfViews
    ids = List[ElementId]()
    ids.Add(view.Id)
    opts.SetViewsAndSheets(ids)
    try:
        opts.ImageResolution = ImageResolution.DPI_150
    except Exception:
        pass
    try:
        opts.PixelSize = int(pixel_size)
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

    try:
        doc.ExportImage(opts)
    except Exception as ex:
        shutil.rmtree(folder, ignore_errors=True)
        return False, _u(ex)

    pngs = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(u".png"):
                pngs.append(os.path.join(root, f))
    if not pngs:
        shutil.rmtree(folder, ignore_errors=True)
        return False, u"No se genero PNG."

    pngs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    src = pngs[0]
    try:
        dest_dir = os.path.dirname(dest_png_path)
        if dest_dir and not os.path.isdir(dest_dir):
            os.makedirs(dest_dir)
        if os.path.isfile(dest_png_path):
            os.remove(dest_png_path)
        shutil.move(src, dest_png_path)
    except Exception as ex:
        shutil.rmtree(folder, ignore_errors=True)
        return False, _u(ex)

    shutil.rmtree(folder, ignore_errors=True)
    return True, u""


def _is_view_exportable(view):
    if view is None or view.IsTemplate:
        return False
    vt = view.ViewType.ToString()
    if vt in (u"Schedule", u"DrawingSheet", u"Legend"):
        return False
    return True


def main():
    doc = revit.doc
    view = doc.ActiveView if doc else None
    if doc is None or not _is_view_exportable(view):
        forms.alert(
            u"Vista activa no valida para exportar (plantilla, planilla, leyenda, etc.).",
            title=__title__,
            warn_icon=True,
        )
        return

    try:
        _main_export(doc, view)
    except Exception as ex:
        forms.alert(
            u"Error inesperado (no deberia cerrar Revit; si se cerro, avisá):\n{0}".format(_u(ex)),
            title=__title__,
            warn_icon=True,
        )


def _main_export(doc, view):
    solid_id = _get_solid_fill_pattern_id(doc)
    if solid_id is None:
        forms.alert(
            u"No hay patron solido en el proyecto; el resultado puede verse sin relleno.",
            title=__title__,
            warn_icon=True,
        )

    ts = datetime.datetime.now().strftime(u"%Y%m%d_%H%M%S")
    stem = _sanitize_filename_stem(view.Name)
    out_name = u"{0}_{1}.png".format(stem, ts)
    dest_png = os.path.join(OUTPUT_DIR, out_name)

    dup_id = None
    tx = None
    try:
        tx = Transaction(doc, u"BTZ | Exportar vista estilo San Lorenzo")
        tx.Start()
        dup_id = view.Duplicate(ViewDuplicateOption.Duplicate)
        dup = doc.GetElement(dup_id)
        if dup is None:
            raise Exception(u"No se pudo duplicar la vista.")

        dup.Name = _unique_temp_view_name(doc, u"EXP_SL_" + stem)
        # No tocar DisplayStyle: la duplicata hereda el estilo de la vista activa (p. ej. Hidden Line).
        _apply_site_green_only(dup, doc, solid_id)
        tx.Commit()
    except Exception as ex:
        try:
            if tx is not None:
                tx.RollBack()
        except Exception:
            pass
        forms.alert(u"Error: {0}".format(_u(ex)), title=__title__, warn_icon=True)
        return

    try:
        doc.Regenerate()
    except Exception:
        pass

    dup = doc.GetElement(dup_id)
    if dup is None:
        forms.alert(u"La vista duplicada ya no existe.", title=__title__, warn_icon=True)
        return
    ok, msg = _export_view_highres_png(doc, dup, dest_png)

    txd = None
    try:
        txd = Transaction(doc, u"BTZ | Quitar vista temporal export")
        txd.Start()
        doc.Delete(dup_id)
        txd.Commit()
        dup_id = None
    except Exception:
        try:
            if txd is not None:
                txd.RollBack()
        except Exception:
            pass

    if ok:
        extra = u""
        if dup_id is not None:
            extra = u"\n\n(No se pudo borrar la vista temporal; borrala a mano en el Navegador.)"
        forms.alert(
            u"PNG guardado:\n{0}{1}".format(dest_png, extra),
            title=__title__,
        )
    else:
        forms.alert(u"Fallo exportacion:\n{0}".format(msg), title=__title__, warn_icon=True)


if __name__ == u"__main__":
    main()
