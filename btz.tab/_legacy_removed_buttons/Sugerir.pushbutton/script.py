# -*- coding: utf-8 -*-
"""
Lanzador: sugerencias / resolver automático (CSV + modelo).
Script oficial: ResolverBTZAutomatico.pushbutton"""
from __future__ import print_function

import os
import runpy

_bundle = os.path.dirname(os.path.abspath(__file__))
_target = os.path.normpath(
    os.path.join(_bundle, u"..", u"ResolverBTZAutomatico.pushbutton", u"script.py")
)
if not os.path.isfile(_target):
    from pyrevit import forms
    forms.alert(
        u"No se encontro ResolverBTZAutomatico en:\n{0}".format(_target),
        title=u"Sugerir",
        warn_icon=True,
    )
else:
    runpy.run_path(_target, run_name="__main__")
