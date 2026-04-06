# -*- coding: utf-8 -*-
"""
Resolucion centralizada de rutas BTZ.

Official runtime: resolver_btz_automatico.
- Core permanece en public/ raiz.
- Debug en public/_debug.
- Flujos viejos/paralelos en public/_legacy.
- Soporte no-core en public/_optional.
"""
from __future__ import print_function

import os

try:
    unicode
except NameError:
    unicode = str


def _u(v):
    if v is None:
        return u""
    try:
        return unicode(v)
    except Exception:
        try:
            return unicode(str(v))
        except Exception:
            return u""


def _resolve_extension_root_and_source():
    """Encuentra raiz de extension y origen de resolucion."""
    path_source = u""

    # 1) pyRevit bundle path (ruta real de la extension)
    try:
        from pyrevit import script

        bpaths = script.get_bundle_paths() or []
        for bp in bpaths:
            bp = os.path.abspath(bp)
            ext = os.path.normpath(os.path.join(bp, u"..", u"..", u".."))
            marker = os.path.join(ext, u"resources", u"BTZ_SharedParameters.txt")
            if os.path.isfile(marker):
                path_source = u"pyrevit.script.get_bundle_paths() -> {0}".format(_u(bp))
                return ext, path_source
    except Exception:
        pass

    # 2) Subir desde __file__
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(14):
        ext = os.path.normpath(os.path.join(d, u"..", u"..", u".."))
        marker = os.path.join(ext, u"resources", u"BTZ_SharedParameters.txt")
        if os.path.isfile(marker):
            path_source = u"walk __file__ -> {0}".format(_u(d))
            return ext, path_source
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent

    # 3) fallback fijo
    base = os.path.dirname(os.path.abspath(__file__))
    ext = os.path.normpath(os.path.abspath(os.path.join(base, u"..", u"..", u"..")))
    path_source = u"fallback 3 niveles desde __file__"
    return ext, path_source


EXT_DIR, PATH_SOURCE = _resolve_extension_root_and_source()
RESOURCES_DIR = os.path.normpath(os.path.join(EXT_DIR, u"resources"))
PUBLIC_DIR = os.path.normpath(os.path.join(EXT_DIR, u"public"))

PUBLIC_DEBUG_DIR = os.path.join(PUBLIC_DIR, u"_debug")
PUBLIC_OPTIONAL_DIR = os.path.join(PUBLIC_DIR, u"_optional")
PUBLIC_LEGACY_DIR = os.path.join(PUBLIC_DIR, u"_legacy")

RESOURCES_OPTIONAL_DIR = os.path.join(RESOURCES_DIR, u"_optional")
RESOURCES_LEGACY_DIR = os.path.join(RESOURCES_DIR, u"_legacy")

SHARED_PARAMS_FILE = os.path.join(RESOURCES_DIR, u"BTZ_SharedParameters.txt")

CORE_FILES = {
    u"public": [
        u"asociacion_por_ancestro_dibujado.csv",
        u"asignacion_automatica_sugerida.csv",
        u"resolver_btz_automatico_results.csv",
        u"resolver_btz_automatico_summary.txt",
    ],
    u"resources": [u"BTZ_SharedParameters.txt"],
}


def ensure_public_layout():
    for d in [PUBLIC_DIR, PUBLIC_DEBUG_DIR, PUBLIC_OPTIONAL_DIR, PUBLIC_LEGACY_DIR]:
        if not os.path.isdir(d):
            os.makedirs(d)


def ensure_resources_layout():
    for d in [RESOURCES_DIR, RESOURCES_OPTIONAL_DIR, RESOURCES_LEGACY_DIR]:
        if not os.path.isdir(d):
            os.makedirs(d)


def _public_bucket_dir(bucket_preferido):
    b = _u(bucket_preferido).strip().lower()
    if b in (u"", u"core"):
        return PUBLIC_DIR
    if b == u"debug":
        return PUBLIC_DEBUG_DIR
    if b == u"optional":
        return PUBLIC_OPTIONAL_DIR
    if b == u"legacy":
        return PUBLIC_LEGACY_DIR
    return PUBLIC_DIR


def _resource_bucket_dir(bucket_preferido):
    b = _u(bucket_preferido).strip().lower()
    if b in (u"", u"core"):
        return RESOURCES_DIR
    if b == u"optional":
        return RESOURCES_OPTIONAL_DIR
    if b == u"legacy":
        return RESOURCES_LEGACY_DIR
    return RESOURCES_DIR


def get_public_file(name, bucket_preferido=None, fallback=True):
    """
    Lectura: primero bucket nuevo y luego fallback (raiz/debug/optional/legacy).
    Escritura: usar fallback=False para forzar bucket nuevo.
    """
    fname = _u(name).strip()
    preferred_dir = _public_bucket_dir(bucket_preferido)
    preferred_path = os.path.join(preferred_dir, fname)
    if not fallback:
        return preferred_path

    candidates = [preferred_path]
    candidates.extend(
        [
            os.path.join(PUBLIC_DIR, fname),
            os.path.join(PUBLIC_DEBUG_DIR, fname),
            os.path.join(PUBLIC_OPTIONAL_DIR, fname),
            os.path.join(PUBLIC_LEGACY_DIR, fname),
        ]
    )

    seen = set()
    for p in candidates:
        np = os.path.normpath(p)
        if np in seen:
            continue
        seen.add(np)
        if os.path.isfile(np):
            return np
    return preferred_path


def get_resource_file(name, bucket_preferido=None, fallback=True):
    """
    Lectura: primero bucket nuevo y luego fallback.
    Escritura: usar fallback=False para forzar bucket nuevo.
    """
    fname = _u(name).strip()
    preferred_dir = _resource_bucket_dir(bucket_preferido)
    preferred_path = os.path.join(preferred_dir, fname)
    if not fallback:
        return preferred_path

    candidates = [preferred_path]
    candidates.extend(
        [
            os.path.join(RESOURCES_DIR, fname),
            os.path.join(RESOURCES_OPTIONAL_DIR, fname),
            os.path.join(RESOURCES_LEGACY_DIR, fname),
        ]
    )

    seen = set()
    for p in candidates:
        np = os.path.normpath(p)
        if np in seen:
            continue
        seen.add(np)
        if os.path.isfile(np):
            return np
    return preferred_path
