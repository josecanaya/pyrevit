# -*- coding: utf-8 -*-
"""
pyRevit - Asignar BTZ manual jerarquico

Escribe unicamente:
- BTZ_Description_01 = planta
- BTZ_Description_02 = sector
- BTZ_Description_03 = subsector (opcional)
- BTZ_Description_04 = unidad (opcional)

Incluye modo reporte de uso (01/02/03) para auditoria.
"""
from __future__ import print_function

__title__ = "Asignar"
__doc__ = (
    "LEGACY manual: asignacion jerarquica BTZ "
    "(planta/sector/subsector/unidad) + reporte"
)
__author__ = "btz.extension"

import os
import sys
from glob import glob
import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import Transaction, CategoryType, GroupTypeId
from pyrevit import revit, forms

_bundle_dir = os.path.dirname(os.path.abspath(__file__))
if _bundle_dir not in sys.path:
    sys.path.insert(0, _bundle_dir)
_export_dir = os.path.normpath(
    os.path.join(_bundle_dir, u"..", u"..", u"ExportarGrupos.pushbutton")
)
if _export_dir not in sys.path:
    sys.path.insert(0, _export_dir)

from btz_manual_catalog import (
    load_manual_catalog,
    validate_hierarchy,
    upsert_sector,
    upsert_subsector,
    append_catalog_entries,
)
from btz_manual_usage import scan_model_usage, export_usage_report
from btz_manual_ui import pick_mode, pick_assignment
from btz_manual_apply import analyze_selection_state, apply_manual_hierarchy
from btz_paths import get_public_file


PARAM_BASE = u"BTZ_Description"
PARAM_01 = u"BTZ_Description_01"
PARAM_02 = u"BTZ_Description_02"
PARAM_03 = u"BTZ_Description_03"
PARAM_04 = u"BTZ_Description_04"
PARAM_NUMERIC = [
    u"BTZ_Description_01", u"BTZ_Description_02", u"BTZ_Description_03",
    u"BTZ_Description_04", u"BTZ_Description_05", u"BTZ_Description_06",
    u"BTZ_Description_07", u"BTZ_Description_08", u"BTZ_Description_09",
    u"BTZ_Description_10", u"BTZ_Description_11", u"BTZ_Description_12",
    u"BTZ_Description_13",
]
ALL_PARAMS = [PARAM_BASE] + PARAM_NUMERIC


def _u(v):
    return unicode(v or u"").strip()


def alert(msg, title=u"BTZ"):
    try:
        forms.alert(unicode(msg), title=title, warn_icon=False)
    except Exception:
        print(u"{0}: {1}".format(title, msg))


def _resolve_btz_extension_paths():
    found_txt = None
    try:
        from pyrevit import script
        bpaths = script.get_bundle_paths()
        if bpaths:
            for bp in bpaths:
                bp = os.path.abspath(bp)
                ext = os.path.normpath(os.path.join(bp, u"..", u"..", u".."))
                candidate = os.path.join(ext, u"resources", u"BTZ_SharedParameters.txt")
                if os.path.isfile(candidate):
                    found_txt = os.path.normpath(os.path.abspath(candidate))
                    break
    except Exception:
        pass
    if not found_txt:
        d = os.path.dirname(os.path.abspath(__file__))
        for _ in range(14):
            candidate = os.path.join(d, u"resources", u"BTZ_SharedParameters.txt")
            if os.path.isfile(candidate):
                found_txt = os.path.normpath(os.path.abspath(candidate))
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    if not found_txt:
        base = os.path.dirname(os.path.abspath(__file__))
        ext = os.path.normpath(os.path.abspath(os.path.join(base, u"..", u"..", u"..")))
        found_txt = os.path.normpath(os.path.join(ext, u"resources", u"BTZ_SharedParameters.txt"))
    res_dir = os.path.dirname(found_txt)
    ext_dir = os.path.dirname(res_dir)
    return ext_dir, res_dir, found_txt


EXT_DIR, RESOURCES_DIR, SHARED_PARAMS_FILE = _resolve_btz_extension_paths()
PUBLIC_DIR = os.path.normpath(os.path.join(EXT_DIR, u"public"))
REPORT_CSV_PATH = get_public_file(
    u"btz_manual_usage_report.csv", u"legacy", fallback=False
)
REPORT_TXT_PATH = get_public_file(
    u"btz_manual_usage_report.txt", u"legacy", fallback=False
)


def _catalog_candidate_paths():
    corrected_alt = os.path.join(PUBLIC_DIR, u"sectores_subsectores_btz_manual (2).csv")
    base = [
        corrected_alt,
        get_public_file(u"sectores_subsectores_btz_manual.csv", u"optional", fallback=True),
        os.path.join(RESOURCES_DIR, u"sectores_subsectores_btz_manual.csv"),
    ]
    base.extend(
        sorted(
            glob(
                os.path.join(
                    os.path.dirname(
                        get_public_file(
                            u"sectores_subsectores_btz_manual.csv",
                            u"optional",
                            fallback=False,
                        )
                    ),
                    u"sectores_subsectores_btz_manual*.csv",
                )
            )
        )
    )
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


def get_preselected_elements(doc, uidoc):
    ids = list(uidoc.Selection.GetElementIds())
    out = []
    for eid in ids:
        el = doc.GetElement(eid)
        if el:
            out.append(el)
    return out


def get_definition_map(def_file):
    defs = {}
    for group in def_file.Groups:
        for definition in group.Definitions:
            try:
                name = definition.Name
            except Exception:
                name = None
            if name:
                defs[name] = definition
    return defs


def build_model_category_set(doc):
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
        raise ValueError(u"No se pudo armar CategorySet de categorias de modelo.")
    return catset


def get_existing_binding_names(doc):
    names = set()
    it = doc.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        try:
            definition = it.Key
            if definition and definition.Name:
                names.add(definition.Name)
        except Exception:
            pass
    return names


def ensure_shared_parameters(doc, shared_params_path):
    if not shared_params_path or not os.path.isfile(shared_params_path):
        raise IOError(u"No se encontro TXT shared parameters: {0}".format(shared_params_path))

    app = doc.Application
    app.SharedParametersFilename = shared_params_path
    def_file = app.OpenSharedParameterFile()
    if def_file is None:
        raise IOError(u"Revit no pudo abrir el archivo de shared parameters.")

    definition_map = get_definition_map(def_file)
    missing = [name for name in ALL_PARAMS if name not in definition_map]
    if missing:
        raise ValueError(u"Faltan parametros en el TXT: {0}".format(u", ".join(missing)))

    catset = build_model_category_set(doc)
    creator = doc.Application.Create
    existing_names = get_existing_binding_names(doc)

    tx = Transaction(doc, u"BTZ | Vincular shared parameters")
    tx.Start()
    try:
        for name in ALL_PARAMS:
            definition = definition_map[name]
            binding = creator.NewInstanceBinding(catset)
            if name in existing_names:
                doc.ParameterBindings.ReInsert(definition, binding, GroupTypeId.Text)
            else:
                ok = doc.ParameterBindings.Insert(definition, binding, GroupTypeId.Text)
                if not ok:
                    doc.ParameterBindings.ReInsert(definition, binding, GroupTypeId.Text)
        tx.Commit()
    except Exception:
        tx.RollBack()
        raise


def set_text_parameter(element, param_name, value):
    p = element.LookupParameter(param_name)
    if not p:
        return False, u"sin_parametro"
    if p.IsReadOnly:
        return False, u"solo_lectura"
    try:
        p.Set(value)
        return True, None
    except Exception as ex:
        return False, unicode(ex)


def _param_value_as_string(element, param_name):
    p = element.LookupParameter(param_name)
    if p is None or not p.HasValue:
        return u""
    try:
        s = p.AsString()
        if s is not None:
            return unicode(s)
    except Exception:
        pass
    try:
        s2 = p.AsValueString()
        if s2 is not None:
            return unicode(s2)
    except Exception:
        pass
    return u""


def _format_selection_mix(selection_state):
    lines = []
    lines.append(u"La seleccion tiene mezcla de valores BTZ previos.")
    lines.append(u"Combinaciones detectadas:")
    combos = list(selection_state[u"unique_combos"].items())
    combos.sort(key=lambda x: -x[1])
    for (v1, v2, v3, v4), c in combos[:10]:
        lines.append(u"- {0} | {1} | {2} | {3} -> {4} el.".format(v1 or u"-", v2 or u"-", v3 or u"-", v4 or u"-", c))
    if len(combos) > 10:
        lines.append(u"... y {0} combinaciones mas".format(len(combos) - 10))
    return u"\n".join(lines)


def _run_report(doc, catalog_source):
    usage = scan_model_usage(doc)
    report = export_usage_report(usage, REPORT_CSV_PATH, REPORT_TXT_PATH)
    msg = [
        u"Reporte generado",
        u"Catalogo: {0}".format(catalog_source),
        u"CSV: {0}".format(report[u"csv_path"]),
        u"TXT: {0}".format(report[u"txt_path"]),
        u"Combinaciones: {0}".format(report[u"rows"]),
        u"Elementos escaneados: {0}".format(usage[u"elements_scanned"]),
        u"Elementos con BTZ 01/02/03: {0}".format(usage[u"elements_with_any_btz"]),
    ]
    alert(u"\n".join(msg), u"BTZ manual - Reporte")


def main():
    doc = revit.doc
    uidoc = revit.uidoc
    if not doc or not uidoc:
        alert(u"No hay documento activo.", u"BTZ")
        return

    catalog_paths = _catalog_candidate_paths()
    try:
        catalog = load_manual_catalog(catalog_paths)
    except Exception as ex:
        alert(
            u"No se pudo cargar catalogo manual.\n\n"
            u"Rutas esperadas (prioridad):\n- {0}\n\n{1}".format(
                u"\n- ".join(catalog_paths),
                ex,
            ),
            u"BTZ",
        )
        return

    mode = pick_mode(forms)
    if mode == u"cancel":
        return
    if mode == u"report":
        _run_report(doc, catalog.get(u"source_path", u""))
        return

    elements = get_preselected_elements(doc, uidoc)
    if not elements:
        alert(u"Primero selecciona uno o varios elementos y luego ejecuta Asignar.", u"BTZ")
        return

    try:
        ensure_shared_parameters(doc, SHARED_PARAMS_FILE)
    except Exception as ex:
        alert(u"No se pudieron vincular shared parameters.\n\n{0}".format(ex), u"BTZ")
        return

    usage = scan_model_usage(doc)
    picked = pick_assignment(catalog, usage, forms)
    if not picked:
        return

    # Alta manual en caliente (ej: PV / PV1) para que participe en validacion.
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

    ok, reason = validate_hierarchy(
        catalog=catalog,
        plant_code=picked[u"plant_code"],
        sector_key=picked[u"sector_key"],
        subsector_code=picked[u"subsector_code"],
        unit_code=picked.get(u"unit_code", u""),
    )
    if not ok:
        alert(reason, u"BTZ manual")
        return

    selection_state = analyze_selection_state(elements, _param_value_as_string)
    if selection_state[u"is_mixed"]:
        proceed = forms.CommandSwitchWindow.show(
            [u"Continuar", u"Cancelar"],
            message=_format_selection_mix(selection_state),
            title=u"BTZ manual - Advertencia",
        )
        if proceed != u"Continuar":
            return

    tx = Transaction(doc, u"BTZ | Asignar manual 01/02/03/04")
    tx.Start()
    try:
        result = apply_manual_hierarchy(
            elements=elements,
            plant_code=picked[u"plant_code"],
            sector_code=picked[u"sector_write_code"],
            subsector_code=picked[u"subsector_code"],
            unit_code=picked.get(u"unit_code", u""),
            overwrite=bool(picked.get(u"overwrite")),
            set_text_parameter=set_text_parameter,
            get_current_value=_param_value_as_string,
        )
        tx.Commit()
    except Exception as ex:
        tx.RollBack()
        alert(u"Error al escribir parametros.\n\n{0}".format(ex), u"BTZ")
        return

    # Persistimos nuevas altas manuales en el catalogo principal public.
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
            alert(u"Se asigno BTZ, pero no se pudo persistir alta manual en CSV.\n{0}".format(ex), u"BTZ manual")

    msg = [
        u"Catalogo usado: {0}".format(catalog.get(u"source_path", u"")),
        u"BTZ_Description_01 (planta): {0}".format(_u(picked[u"plant_code"]).upper()),
        u"BTZ_Description_02 (sector): {0}".format(_u(picked[u"sector_write_code"]).upper()),
        u"BTZ_Description_03 (subsector): {0}".format(_u(picked[u"subsector_code"]).upper() or u"(vacio)"),
        u"BTZ_Description_04 (unidad): {0}".format(_u(picked.get(u"unit_code", u"")).upper() or u"(vacio)"),
        u"Elementos modificados: {0} de {1}".format(result.get(u"modified", 0), len(elements)),
        u"Sin cambios: {0}".format(result.get(u"unchanged", 0)),
        u"Saltados por existentes (sin sobrescribir): {0}".format(result.get(u"skipped_existing", 0)),
    ]
    errors = result.get(u"errors") or []
    if errors:
        msg.append(u"")
        msg.append(u"Errores:")
        msg.append(u"\n".join(errors[:15]))
        if len(errors) > 15:
            msg.append(u"... y {0} mas".format(len(errors) - 15))

    alert(u"\n".join(msg), u"BTZ manual listo")


if __name__ == "__main__":
    main()
