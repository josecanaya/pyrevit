# -*- coding: utf-8 -*-
"""
pyRevit — Limpiar todo BTZ en el modelo

Vacía BTZ_Description, BTZ_Description_01…13 y BTZ_Status / BTZ_Source / BTZ_Confidence
en todos los elementos de instancia del documento actual.
"""
from __future__ import print_function

__title__ = "Limpiar todo BTZ"
__doc__ = (
    "Vacía todos los parámetros BTZ en todo el modelo (confirmación previa). "
    "Puede tardar en proyectos grandes."
)
__author__ = "btz.extension"

import clr
clr.AddReference("RevitAPI")

from Autodesk.Revit.DB import FilteredElementCollector, Transaction

from pyrevit import revit, forms


PARAM_BASE = "BTZ_Description"
PARAM_NUMERIC = [
    "BTZ_Description_01",
    "BTZ_Description_02",
    "BTZ_Description_03",
    "BTZ_Description_04",
    "BTZ_Description_05",
    "BTZ_Description_06",
    "BTZ_Description_07",
    "BTZ_Description_08",
    "BTZ_Description_09",
    "BTZ_Description_10",
    "BTZ_Description_11",
    "BTZ_Description_12",
    "BTZ_Description_13",
]
# Mismos metadatos que Exportar grupos (sugerencia IA)
PARAM_EXTRA = [
    "BTZ_Status",
    "BTZ_Source",
    "BTZ_Confidence",
]
ALL_PARAMS = [PARAM_BASE] + PARAM_NUMERIC + PARAM_EXTRA


def clear_param(element, param_name):
    """Deja el parámetro de texto vacío. Devuelve True si se pudo escribir."""
    param = element.LookupParameter(param_name)
    if param is None or param.IsReadOnly:
        return False
    try:
        param.Set("")
        return True
    except Exception:
        return False


def main():
    doc = revit.doc
    if not doc:
        forms.alert("No hay documento activo.", title="Limpiar todo BTZ")
        return

    msg = (
        "Se van a VACIAR en TODO el modelo los parámetros:\n\n"
        "• BTZ_Description\n"
        "• BTZ_Description_01 … BTZ_Description_13\n"
        "• BTZ_Status, BTZ_Source, BTZ_Confidence\n\n"
        "Operación global: puede tardar en proyectos grandes.\n\n"
        "¿Continuar?"
    )
    opts = ["Sí, vaciar todo el modelo", "Cancelar"]
    sel = forms.CommandSwitchWindow.show(
        opts,
        message=msg,
        title="Limpiar todo BTZ",
    )
    if sel != "Sí, vaciar todo el modelo":
        return

    col = FilteredElementCollector(doc).WhereElementIsNotElementType()
    elements = list(col)

    tx = Transaction(doc, "BTZ | Limpiar todo el modelo")
    tx.Start()
    try:
        elements_touched = 0
        params_cleared = 0
        for el in elements:
            touched = False
            for pname in ALL_PARAMS:
                if clear_param(el, pname):
                    params_cleared += 1
                    touched = True
            if touched:
                elements_touched += 1
        tx.Commit()
    except Exception as ex:
        try:
            tx.RollBack()
        except Exception:
            pass
        forms.alert("Error:\n%s" % ex, title="Limpiar todo BTZ", warn_icon=True)
        return

    forms.alert(
        "Listo.\n\n"
        "Elementos con al menos un BTZ vaciado: %s\n"
        "Total de parámetros vaciados (escrituras): %s\n"
        "Elementos revisados: %s"
        % (elements_touched, params_cleared, len(elements)),
        title="Limpiar todo BTZ",
        warn_icon=False,
    )


if __name__ == "__main__":
    main()
