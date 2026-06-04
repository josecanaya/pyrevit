# -*- coding: utf-8 -*-
"""Detección de clusters de contenedor lógico (mismo sector en varios elementos Revit)."""
from __future__ import print_function

try:
    unicode
except NameError:
    unicode = str

PP_SRV_CAP_SINGLE_ELEMENT = 76
PP_SRV_MARKER = u"PP-SRV-LGC-SERVICIOS"


def _u(value):
    if value is None:
        return u""
    try:
        return unicode(value).strip()
    except Exception:
        try:
            return unicode(str(value)).strip()
        except Exception:
            return u""


def _norm_code(value):
    return _u(value).upper().rstrip(u".,:;)")


def _norm_path_key(path):
    p = _u(path).upper().replace(u" ", u"").replace(u"|", u">")
    while u">>" in p:
        p = p.replace(u">>", u">")
    return p.strip(u">")


def _path_compatible(paths, ancestor_used):
    paths = [_norm_path_key(p) for p in paths if _norm_path_key(p)]
    if not paths:
        return True
    if len(set(paths)) == 1:
        return True
    au = _norm_code(ancestor_used)
    return all(au in p for p in paths)


def _ancestor_signature_block(container, ancestor_used):
    """Bloques normalizados de BTZ_01..04 para comparar rol del sector."""
    row = container.get(u"_row", container)
    anc = _norm_code(ancestor_used)
    sig = []
    for i in range(1, 5):
        col = u"btz_description_{:02d}".format(i)
        sig.append(_norm_code(row.get(col)))
    if anc not in sig and _norm_code(row.get(u"btz_numero_activo")) != anc:
        return None
    return tuple(sig)


def logical_cluster_from_punctual_duplicate_hits(code, hits, plant_code):
    """Mismo criterio que ancestro: paths/firma BTZ coherentes y planta en modelo."""
    return logical_cluster_from_ancestor_hits(_norm_code(code), hits, plant_code)


def logical_cluster_from_ancestor_hits(ancestor_used, hits, plant_code):
    if len(hits) <= 1:
        return list(hits)
    plant_code = _u(plant_code).upper()
    paths = [_norm_path_key(c.get(u"btz_path_detectado")) for c in hits]
    if not _path_compatible(paths, ancestor_used):
        sigs = [_ancestor_signature_block(c, ancestor_used) for c in hits]
        if None in sigs or len(set(sigs)) != 1:
            return None
    for c in hits:
        row = c.get(u"_row", {})
        hay = u" ".join(_u(row.get(u"btz_description_{:02d}".format(i))) for i in range(1, 21))
        hay += u" " + _u(row.get(u"btz_numero_activo")) + u" " + _u(c.get(u"btz_path_detectado"))
        if plant_code and plant_code not in hay.upper():
            return None
    return hits


def count_free_slots_05_80(row_dict):
    n = 0
    for i in range(5, 81):
        col = u"btz_description_{:02d}".format(i)
        if not _u(row_dict.get(col)):
            n += 1
    return n


def ancestor_in_desc_03_or_04(container, ancestor_used):
    anc = _norm_code(ancestor_used)
    row = container.get(u"_row", container)
    for idx in (3, 4):
        col = u"btz_description_{:02d}".format(idx)
        if _norm_code(row.get(col)) == anc:
            return True
    return False


def category_rank(category):
    c = _u(category).lower()
    if u"generic" in c:
        return 0
    if u"model" in c and u"generic" in c:
        return 0
    if u"roof" in c or u"cubierta" in c or u"ceiling" in c:
        return 2
    if u"wall" in c or u"muro" in c:
        return 2
    if u"floor" in c or u"suelo" in c:
        return 2
    return 1


def pick_canonical_master(cluster, ancestor_used):
    def sort_key(c):
        try:
            eid = int(_u(c.get(u"element_id")) or 0)
        except Exception:
            eid = 999999999
        return (
            not ancestor_in_desc_03_or_04(c, ancestor_used),
            -count_free_slots_05_80(c.get(u"_row", {})),
            category_rank(c.get(u"category")),
            eid,
        )

    return sorted(cluster, key=sort_key)[0]


def cluster_element_ids_csv(cluster):
    raw_ids = []
    for c in cluster:
        try:
            raw_ids.append(int(_u(c.get(u"element_id"))))
        except Exception:
            continue
    raw_ids = sorted(set(raw_ids))
    return u";".join(unicode(i) for i in raw_ids)


def is_pp_srv_cluster_row(ancestor_used, container_path):
    blob = (_u(ancestor_used) + u" " + _u(container_path)).upper()
    return PP_SRV_MARKER in blob
