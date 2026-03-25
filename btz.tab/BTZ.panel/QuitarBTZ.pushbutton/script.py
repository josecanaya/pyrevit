# -*- coding: utf-8 -*-
"""
pyRevit - Quitar BTZ

Quita los valores de BTZ_Description y BTZ_Description_01..13
de los elementos seleccionados (los deja vacíos).
"""
from __future__ import print_function

__title__ = "BTZ Quitar"
__doc__ = "Quita los valores BTZ de los elementos seleccionados"
__author__ = "btz.extension"

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import Transaction
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms


PARAM_BASE = "BTZ_Description"
PARAM_NUMERIC = [
    "BTZ_Description_01", "BTZ_Description_02", "BTZ_Description_03",
    "BTZ_Description_04", "BTZ_Description_05", "BTZ_Description_06",
    "BTZ_Description_07", "BTZ_Description_08", "BTZ_Description_09",
    "BTZ_Description_10", "BTZ_Description_11", "BTZ_Description_12",
    "BTZ_Description_13",
]
ALL_PARAMS = [PARAM_BASE] + PARAM_NUMERIC


def get_elements(doc, uidoc):
    """Obtiene elementos: selección actual o pick."""
    ids = list(uidoc.Selection.GetElementIds())
    if ids:
        elements = [doc.GetElement(eid) for eid in ids if doc.GetElement(eid)]
        if elements:
            return elements
    try:
        refs = uidoc.Selection.PickObjects(ObjectType.Element, "Seleccioná uno o varios elementos")
        return [doc.GetElement(r.ElementId) for r in refs if doc.GetElement(r.ElementId)]
    except OperationCanceledException:
        return []


def clear_param(element, param_name):
    """Borra el valor del parámetro (lo deja vacío)."""
    param = element.LookupParameter(param_name)
    if not param or param.IsReadOnly:
        return False
    try:
        param.Set("")
        return True
    except Exception:
        return False


def main():
    doc = revit.doc
    uidoc = revit.uidoc
    if not doc or not uidoc:
        forms.alert("No hay documento activo.", title="BTZ Quitar")
        return

    elements = get_elements(doc, uidoc)
    if not elements:
        forms.alert("No seleccionaste elementos.", title="BTZ Quitar")
        return

    tx = Transaction(doc, "BTZ | Quitar descripciones")
    tx.Start()
    try:
        cleared = 0
        for el in elements:
            for pname in ALL_PARAMS:
                if clear_param(el, pname):
                    cleared += 1
        tx.Commit()
        forms.alert("BTZ quitados en %s elementos.\nParámetros vaciados: %s." % (len(elements), cleared), title="BTZ Quitar")
    except Exception as ex:
        tx.RollBack()
        forms.alert("Error:\n%s" % ex, title="BTZ Quitar")


if __name__ == "__main__":
    main()
