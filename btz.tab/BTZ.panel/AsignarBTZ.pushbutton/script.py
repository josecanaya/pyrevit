# -*- coding: utf-8 -*-
"""
pyRevit - Asignar BTZ desde CSV

Flujo:
1) Verifica que haya elementos preseleccionados.
2) Carga y vincula los shared parameters BTZ al proyecto.
3) Muestra botonera para elegir qué parámetro BTZ completar.
4) Muestra lista de bloques desde blocks.csv (con filtro por categoría).
5) Escribe en el parámetro elegido el valor de la columna description.
6) Escribe automáticamente BTZ_Description = "*".

Solo trabaja con elementos PRESELECCIONADOS. Sin selección manual posterior.
"""
from __future__ import print_function

__title__ = "Asignar"
__doc__ = "Asigna BTZ_Description_x a elementos preseleccionados usando description de blocks.csv"
__author__ = "btz.extension"

import os
import csv
import codecs
import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import Transaction, CategoryType, GroupTypeId
from pyrevit import revit, forms


# -----------------------------------------------------------------------------
# CONFIGURACION
# pyRevit puede ejecutar desde %TEMP%; get_bundle_paths() localiza la extensión real.
# -----------------------------------------------------------------------------
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
BLOCKS_CSV_FILE = os.path.normpath(os.path.join(RESOURCES_DIR, u"blocks.csv"))

PARAM_BASE = "BTZ_Description"
PARAM_NUMERIC = [
    "BTZ_Description_01", "BTZ_Description_02", "BTZ_Description_03",
    "BTZ_Description_04", "BTZ_Description_05", "BTZ_Description_06",
    "BTZ_Description_07", "BTZ_Description_08", "BTZ_Description_09",
    "BTZ_Description_10", "BTZ_Description_11", "BTZ_Description_12",
    "BTZ_Description_13",
]
ALL_PARAMS = [PARAM_BASE] + PARAM_NUMERIC

CSV_CODE_COL = "code"
CSV_DESC_COL = "description"
CSV_CATEGORY_COLS_AFTER = "displacement_date"
CSV_VALUE_MODE = "description"


def alert(msg, title="BTZ"):
    try:
        forms.alert(str(msg), title=title, warn_icon=False)
    except Exception:
        print("%s: %s" % (title, msg))


# -----------------------------------------------------------------------------
# PRESELECCION (solo elementos ya seleccionados, sin PickObject/PickObjects)
# -----------------------------------------------------------------------------
def get_preselected_elements(doc, uidoc):
    """Obtiene SOLO los elementos ya preseleccionados. No abre modo de selección."""
    ids = list(uidoc.Selection.GetElementIds())
    if not ids:
        return []
    elements = []
    for eid in ids:
        el = doc.GetElement(eid)
        if el:
            elements.append(el)
    return elements


# -----------------------------------------------------------------------------
# CSV
# -----------------------------------------------------------------------------
def load_blocks(csv_path):
    """
    Carga bloques desde CSV.
    Columnas: code, description, start_date, end_date, displacement_date, [categorias...]
    Las columnas despues de displacement_date son categorias: si tiene 1, el bloque pertenece.
    Retorna: {'items': [...], 'categories': [...]}
    """
    if not csv_path or not os.path.isfile(csv_path):
        raise IOError("No se encontro el CSV: %s" % csv_path)

    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin1"]
    last_error = None

    for enc in encodings:
        try:
            with codecs.open(csv_path, "r", enc) as fp:
                sample = fp.read(4096)
                fp.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=";,")
                    delimiter = dialect.delimiter
                except Exception:
                    delimiter = ";" if sample.count(";") > sample.count(",") else ","

                reader = csv.DictReader(fp, delimiter=delimiter)
                if not reader.fieldnames:
                    continue

                fields = [f.strip() for f in reader.fieldnames]
                code_field = None
                desc_field = None
                category_cols = []

                for i, f in enumerate(fields):
                    low = f.lower().strip()
                    if low == CSV_CODE_COL:
                        code_field = f
                    if low == CSV_DESC_COL:
                        desc_field = f
                    if low == CSV_CATEGORY_COLS_AFTER.lower():
                        category_cols = [fields[j] for j in range(i + 1, len(fields)) if fields[j]]
                        break

                if not desc_field:
                    raise ValueError("El CSV no tiene columna description")

                items = []
                seen = set()
                for row in reader:
                    code = (row.get(code_field, "") if code_field else "").strip()
                    desc = (row.get(desc_field, "") if desc_field else "").strip()
                    if not desc:
                        continue

                    if CSV_VALUE_MODE == "code - description" and code:
                        value = "%s - %s" % (code, desc)
                    else:
                        value = desc

                    display = ("%s - %s" % (code, desc)).strip(" -") if code else desc
                    key = (display, value)
                    if key in seen:
                        continue
                    seen.add(key)

                    categories = []
                    for col in category_cols:
                        val = (row.get(col, "") or "").strip()
                        if val == "1":
                            categories.append(col)

                    items.append({
                        "display": display,
                        "value": value,
                        "code": code,
                        "description": desc,
                        "categories": categories,
                    })

                items.sort(key=lambda x: x["display"].lower())
                if not items:
                    raise ValueError("El CSV no tiene filas utiles")
                return {"items": items, "categories": category_cols}
        except Exception as ex:
            last_error = ex
            continue

    raise ValueError("No se pudo leer el CSV. Error: %s" % last_error)


# -----------------------------------------------------------------------------
# SHARED PARAMETERS
# -----------------------------------------------------------------------------
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
        raise ValueError("No se pudo armar un CategorySet de categorias de modelo.")
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
        raise IOError("No se encontro el TXT de shared parameters: %s" % shared_params_path)

    app = doc.Application
    app.SharedParametersFilename = shared_params_path
    def_file = app.OpenSharedParameterFile()
    if def_file is None:
        raise IOError("Revit no pudo abrir el archivo de shared parameters.")

    definition_map = get_definition_map(def_file)
    missing = [name for name in ALL_PARAMS if name not in definition_map]
    if missing:
        raise ValueError("Faltan parametros en el TXT: %s" % ", ".join(missing))

    catset = build_model_category_set(doc)
    creator = doc.Application.Create
    existing_names = get_existing_binding_names(doc)

    tx = Transaction(doc, "BTZ | Vincular shared parameters")
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


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
def choose_parameter():
    chosen = forms.SelectFromList.show(
        PARAM_NUMERIC,
        title="Elegir parametro BTZ",
        button_name="Usar parametro",
        multiselect=False,
        width=500,
        height=500,
    )
    return chosen


def choose_block(blocks_data):
    items = blocks_data["items"]
    categories = blocks_data.get("categories", [])

    filtered = items
    if categories:
        filter_opts = ["(Todas)"] + sorted(categories)
        cat_chosen = forms.SelectFromList.show(
            filter_opts,
            title="Filtrar por categoria (1 = bloque pertenece)",
            button_name="Aplicar filtro",
            multiselect=True,
            width=500,
            height=400,
        )
        if cat_chosen is None:
            return None
        sel = cat_chosen if isinstance(cat_chosen, (list, tuple)) else [cat_chosen] if cat_chosen else []
        selected_cats = [c for c in sel if c and c != "(Todas)"]
        if selected_cats:
            filtered = [b for b in items if any(c in (b.get("categories") or []) for c in selected_cats)]
            if not filtered:
                alert("No hay bloques en las categorias seleccionadas.", "BTZ")
                return None

    options = [b["display"] for b in filtered]
    chosen = forms.SelectFromList.show(
        options,
        title="Elegir bloque (%s en lista)" % len(filtered),
        button_name="Usar bloque",
        multiselect=False,
        width=900,
        height=700,
    )
    if not chosen:
        return None

    for block in filtered:
        if block["display"] == chosen:
            return block
    return None


# -----------------------------------------------------------------------------
# ESCRITURA
# -----------------------------------------------------------------------------
def set_text_parameter(element, param_name, value):
    param = element.LookupParameter(param_name)
    if not param:
        return False, "sin_parametro"
    if param.IsReadOnly:
        return False, "solo_lectura"
    try:
        param.Set(value)
        return True, None
    except Exception as ex:
        return False, str(ex)


def apply_to_elements(doc, elements, target_param, block_value):
    """
    Escribe block_value en target_param y SIEMPRE BTZ_Description = "*".
    """
    if not elements:
        raise ValueError("No hay elementos para procesar.")

    ok_count = 0
    fail_rows = []

    tx = Transaction(doc, "BTZ | Asignar valor")
    tx.Start()
    try:
        for el in elements:
            try:
                set_text_parameter(el, PARAM_BASE, "*")
                ok, error = set_text_parameter(el, target_param, block_value)
                if ok:
                    ok_count += 1
                else:
                    cat_name = "<sin categoria>"
                    try:
                        if el.Category:
                            cat_name = el.Category.Name
                    except Exception:
                        pass
                    fail_rows.append("Id %s | Categoria: %s | Motivo: %s" % (el.Id, cat_name, error))
            except Exception as ex:
                cat_name = "<sin categoria>"
                try:
                    if el.Category:
                        cat_name = el.Category.Name
                except Exception:
                    pass
                fail_rows.append("Id %s | Categoria: %s | Error: %s" % (el.Id, cat_name, ex))
        tx.Commit()
    except Exception:
        tx.RollBack()
        raise

    return ok_count, fail_rows


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    doc = revit.doc
    uidoc = revit.uidoc
    if not doc or not uidoc:
        alert("No hay documento activo.", "BTZ")
        return

    elements = get_preselected_elements(doc, uidoc)
    if not elements:
        alert("Primero preseleccioná uno o varios elementos y luego ejecutá el comando.", "BTZ")
        return

    if not SHARED_PARAMS_FILE or not os.path.isfile(SHARED_PARAMS_FILE):
        alert("No se encontro BTZ_Description.txt en:\n%s" % SHARED_PARAMS_FILE, "BTZ")
        return

    if not BLOCKS_CSV_FILE or not os.path.isfile(BLOCKS_CSV_FILE):
        alert("No se encontro blocks.csv en:\n%s" % BLOCKS_CSV_FILE, "BTZ")
        return

    try:
        ensure_shared_parameters(doc, SHARED_PARAMS_FILE)
    except Exception as ex:
        alert("No se pudieron vincular los shared parameters.\n\n%s" % ex, "BTZ")
        return

    try:
        blocks_data = load_blocks(BLOCKS_CSV_FILE)
    except Exception as ex:
        alert("No se pudo leer blocks.csv.\n\n%s" % ex, "BTZ")
        return

    target_param = choose_parameter()
    if not target_param:
        return

    block = choose_block(blocks_data)
    if not block:
        return

    try:
        ok_count, fail_rows = apply_to_elements(doc, elements, target_param, block["value"])
    except Exception as ex:
        alert("Error al escribir parametros.\n\n%s" % ex, "BTZ")
        return

    msg = []
    msg.append("Parametro: %s" % target_param)
    msg.append("Valor: %s" % block["value"])
    msg.append("BTZ_Description = '*' (automatico)")
    msg.append("Elementos actualizados: %s de %s" % (ok_count, len(elements)))
    if fail_rows:
        preview = "\n".join(fail_rows[:12])
        msg.append("")
        msg.append("No se pudieron actualizar:")
        msg.append(preview)
        if len(fail_rows) > 12:
            msg.append("... y %s mas" % (len(fail_rows) - 12))

    alert("\n".join(msg), "BTZ listo")


if __name__ == "__main__":
    main()
