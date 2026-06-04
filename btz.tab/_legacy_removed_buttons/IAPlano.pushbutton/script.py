# -*- coding: utf-8 -*-
"""
Lanzador: el botón del panel apunta aquí; el script real vive en FILTRAR.pushbutton.
Misma lógica que FILTRAR | Navegación BTZ (evita carpeta vacía → PyRevitLoader error).
"""
from __future__ import print_function

import os
import runpy

_bundle = os.path.dirname(os.path.abspath(__file__))
_target = os.path.normpath(os.path.join(_bundle, u"..", u"FILTRAR.pushbutton", u"script.py"))
if not os.path.isfile(_target):
    from pyrevit import forms
    forms.alert(
        u"No se encontro el script de FILTRAR en:\n{0}".format(_target),
        title=u"IAPlano / FILTRAR",
        warn_icon=True,
    )
else:
    runpy.run_path(_target, run_name="__main__")
