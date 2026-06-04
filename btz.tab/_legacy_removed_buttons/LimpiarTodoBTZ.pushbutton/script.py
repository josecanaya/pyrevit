# -*- coding: utf-8 -*-
"""
Lanzador: quitar BTZ de elementos (selección o pick).
Script en Avanzado → QuitarBTZ.
"""
from __future__ import print_function

import os
import runpy

_bundle = os.path.dirname(os.path.abspath(__file__))
_target = os.path.normpath(
    os.path.join(
        _bundle,
        u"..",
        u"Avanzado.stack",
        u"QuitarBTZ.pushbutton",
        u"script.py",
    )
)
if not os.path.isfile(_target):
    from pyrevit import forms
    forms.alert(
        u"No se encontro QuitarBTZ en:\n{0}".format(_target),
        title=u"LimpiarTodoBTZ",
        warn_icon=True,
    )
else:
    runpy.run_path(_target, run_name="__main__")
