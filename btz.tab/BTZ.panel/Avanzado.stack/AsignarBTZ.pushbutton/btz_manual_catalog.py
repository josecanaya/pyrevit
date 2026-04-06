# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import codecs
import csv

try:
    unicode
except NameError:
    unicode = str


NEW_REQUIRED = [
    u"planta_codigo",
    u"planta_nombre",
    u"sector_codigo",
    u"sector_nombre",
    u"sector_lgc",
    u"subsector_nombre",
    u"subsector_lgc",
]

LEGACY_REQUIRED = [
    u"planta_codigo",
    u"sector_codigo",
    u"sector_nombre",
    u"nivel_manual",
    u"nombre_visible",
    u"codigo_lgc",
    u"codigo_sector_lgc",
]

LEGACY_OPTIONAL = [
    u"codigo_subsector_lgc",
    u"codigo_unidad_manual",
    u"nombre_unidad_manual",
    u"description_destino",
]


def _u(v):
    return unicode(v or u"").strip()


def _norm(h):
    return _u(h).replace(u"\ufeff", u"").replace(u"\x00", u"").strip().lower()


def _split_csv_line(line, delim):
    parts = []
    buf = []
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == u'"':
            if in_quotes and i + 1 < len(line) and line[i + 1] == u'"':
                buf.append(u'"')
                i += 2
                continue
            in_quotes = not in_quotes
            i += 1
            continue
        if ch == delim and not in_quotes:
            parts.append(u"".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append(u"".join(buf))
    return parts


def _detect_delim(header_line):
    counts = [
        (u",", header_line.count(u",")),
        (u";", header_line.count(u";")),
        (u"\t", header_line.count(u"\t")),
    ]
    counts.sort(key=lambda x: x[1], reverse=True)
    if counts and counts[0][1] > 0:
        return counts[0][0]
    return u","


def _load_rows_with_schema(csv_path):
    if not os.path.isfile(csv_path):
        raise IOError(u"No existe archivo: {0}".format(csv_path))
    encodings = [u"utf-8-sig", u"utf-8", u"utf-16", u"utf-16-le", u"utf-16-be", u"cp1252", u"latin1"]
    last_error = None
    for enc in encodings:
        try:
            with codecs.open(csv_path, u"r", enc) as fp:
                raw = fp.read()
            raw = raw.replace(u"\x00", u"")
            lines = [ln for ln in raw.splitlines() if _u(ln)]
            if not lines:
                raise ValueError(u"CSV vacío")
            delim = _detect_delim(lines[0])
            headers = [_u(x) for x in _split_csv_line(lines[0], delim)]
            index = {_norm(h): i for i, h in enumerate(headers)}

            has_new = all(_norm(c) in index for c in NEW_REQUIRED)
            has_legacy = all(_norm(c) in index for c in LEGACY_REQUIRED)
            if not has_new and not has_legacy:
                raise ValueError(
                    u"Encabezado inválido. Esperado nuevo={0} o legado={1}. Detectado={2}".format(
                        u", ".join(NEW_REQUIRED),
                        u", ".join(LEGACY_REQUIRED),
                        u", ".join(headers),
                    )
                )

            rows = []
            for line in lines[1:]:
                cols = _split_csv_line(line, delim)
                rec = {}
                for k, pos in index.items():
                    rec[k] = _u(cols[pos]) if pos < len(cols) else u""
                rows.append(rec)
            if not rows:
                raise ValueError(u"CSV sin filas útiles")
            return rows, (u"new" if has_new else u"legacy")
        except Exception as ex:
            last_error = ex
    raise ValueError(u"No se pudo leer catálogo {0}: {1}".format(csv_path, last_error))


def _ensure_plant(catalog, plant_code, plant_name):
    pkey = _u(plant_code).upper()
    if not pkey:
        return None
    if pkey not in catalog[u"plants"]:
        catalog[u"plants"][pkey] = {
            u"code": pkey,
            u"name": _u(plant_name) or pkey,
            u"sectors": {},
        }
    elif not catalog[u"plants"][pkey].get(u"name"):
        catalog[u"plants"][pkey][u"name"] = _u(plant_name) or pkey
    return catalog[u"plants"][pkey]


def _ensure_sector(plant_obj, sector_key, sector_name, sector_write_code):
    skey = _u(sector_key).upper()
    if not skey:
        return None
    sectors = plant_obj[u"sectors"]
    if skey not in sectors:
        sectors[skey] = {
            u"key": skey,
            u"name": _u(sector_name) or skey,
            u"write_code": _u(sector_write_code).upper() or skey,
            u"subsectors": {},
        }
    else:
        if not sectors[skey].get(u"name"):
            sectors[skey][u"name"] = _u(sector_name) or skey
        if not sectors[skey].get(u"write_code"):
            sectors[skey][u"write_code"] = _u(sector_write_code).upper() or skey
    return sectors[skey]


def _add_subsector(sector_obj, subsector_name, subsector_write_code):
    sscode = _u(subsector_write_code).upper()
    if not sscode:
        return
    subs = sector_obj[u"subsectors"]
    if sscode not in subs:
        subs[sscode] = {
            u"code": sscode,
            u"name": _u(subsector_name) or sscode,
            u"units": {},
        }


def _add_unit(subsector_obj, unit_name, unit_write_code):
    ucode = _u(unit_write_code).upper()
    if not ucode:
        return
    units = subsector_obj.get(u"units")
    if units is None:
        units = {}
        subsector_obj[u"units"] = units
    if ucode not in units:
        units[ucode] = {
            u"code": ucode,
            u"name": _u(unit_name) or ucode,
        }


def _build_catalog_from_new(rows, source_path):
    catalog = {u"source_path": source_path, u"schema": u"new", u"plants": {}}
    for r in rows:
        plant = _u(r.get(_norm(u"planta_codigo"))).upper()
        if not plant:
            continue
        plant_name = _u(r.get(_norm(u"planta_nombre")))
        sector_key = _u(r.get(_norm(u"sector_codigo"))).upper()
        sector_name = _u(r.get(_norm(u"sector_nombre")))
        sector_lgc = _u(r.get(_norm(u"sector_lgc"))).upper()
        sub_name = _u(r.get(_norm(u"subsector_nombre")))
        sub_lgc = _u(r.get(_norm(u"subsector_lgc"))).upper()

        p = _ensure_plant(catalog, plant, plant_name)
        if p is None:
            continue
        s = _ensure_sector(p, sector_key or sector_lgc, sector_name, sector_lgc)
        if s is None:
            continue
        _add_subsector(s, sub_name, sub_lgc)
    return catalog


def _build_catalog_from_legacy(rows, source_path):
    catalog = {u"source_path": source_path, u"schema": u"legacy", u"plants": {}}
    pending_subs = []
    pending_units = []
    for r in rows:
        lvl = _u(r.get(_norm(u"nivel_manual"))).upper()
        plant = _u(r.get(_norm(u"planta_codigo"))).upper()
        if not plant:
            continue
        plant_name = plant
        p = _ensure_plant(catalog, plant, plant_name)
        if p is None:
            continue

        if lvl == u"SECTOR":
            sector_key = _u(r.get(_norm(u"sector_codigo"))).upper() or _u(r.get(_norm(u"codigo_lgc"))).upper()
            sector_name = _u(r.get(_norm(u"nombre_visible"))) or _u(r.get(_norm(u"sector_nombre")))
            sector_lgc = _u(r.get(_norm(u"codigo_lgc"))).upper()
            _ensure_sector(p, sector_key, sector_name, sector_lgc)
        elif lvl == u"SUBSECTOR":
            pending_subs.append(r)
        elif lvl == u"UNIDAD":
            pending_units.append(r)

    for r in pending_subs:
        plant = _u(r.get(_norm(u"planta_codigo"))).upper()
        p = catalog[u"plants"].get(plant)
        if p is None:
            continue
        parent_lgc = _u(r.get(_norm(u"codigo_sector_lgc"))).upper()
        candidate = None
        for s in p[u"sectors"].values():
            if _u(s.get(u"write_code")).upper() == parent_lgc:
                candidate = s
                break
        if candidate is None:
            continue
        sub_name = _u(r.get(_norm(u"nombre_visible")))
        sub_lgc = _u(r.get(_norm(u"codigo_lgc"))).upper()
        _add_subsector(candidate, sub_name, sub_lgc)

    for r in pending_units:
        plant = _u(r.get(_norm(u"planta_codigo"))).upper()
        p = catalog[u"plants"].get(plant)
        if p is None:
            continue
        parent_sector_lgc = _u(r.get(_norm(u"codigo_sector_lgc"))).upper()
        parent_sub_lgc = _u(r.get(_norm(u"codigo_subsector_lgc"))).upper()
        if not parent_sub_lgc:
            parent_sub_lgc = _u(r.get(_norm(u"codigo_lgc"))).upper()

        sector_obj = None
        for s in p[u"sectors"].values():
            if _u(s.get(u"write_code")).upper() == parent_sector_lgc:
                sector_obj = s
                break
        if sector_obj is None:
            continue

        sub_obj = sector_obj[u"subsectors"].get(parent_sub_lgc)
        if sub_obj is None:
            continue

        unit_code = _u(r.get(_norm(u"codigo_unidad_manual"))).upper() or _u(r.get(_norm(u"codigo_lgc"))).upper()
        unit_name = _u(r.get(_norm(u"nombre_unidad_manual"))) or _u(r.get(_norm(u"nombre_visible")))
        _add_unit(sub_obj, unit_name, unit_code)
    return catalog


def load_manual_catalog(csv_paths):
    checked = []
    for p in csv_paths:
        ap = os.path.abspath(p)
        checked.append(ap)
        if not os.path.isfile(ap):
            continue
        rows, schema = _load_rows_with_schema(ap)
        catalog = _build_catalog_from_new(rows, ap) if schema == u"new" else _build_catalog_from_legacy(rows, ap)
        if not catalog[u"plants"]:
            raise ValueError(u"Catálogo sin plantas útiles: {0}".format(ap))
        return catalog
    raise IOError(u"No se encontró catálogo manual. Rutas buscadas:\n- {0}".format(u"\n- ".join(checked)))


def list_plants(catalog):
    out = []
    for p in sorted(catalog[u"plants"].values(), key=lambda x: _u(x[u"code"])):
        out.append({
            u"code": _u(p[u"code"]).upper(),
            u"name": _u(p[u"name"]),
            u"display": u"{0} | {1}".format(_u(p[u"code"]).upper(), _u(p[u"name"]) or _u(p[u"code"]).upper()),
        })
    return out


def list_sectors(catalog, plant_code):
    p = catalog[u"plants"].get(_u(plant_code).upper())
    if p is None:
        return []
    out = []
    for s in sorted(p[u"sectors"].values(), key=lambda x: _u(x[u"key"])):
        out.append({
            u"key": _u(s[u"key"]).upper(),
            u"name": _u(s[u"name"]),
            u"write_code": _u(s[u"write_code"]).upper(),
            u"display": u"{0} | {1} | cod:{2}".format(
                _u(s[u"key"]).upper(),
                _u(s[u"name"]) or _u(s[u"key"]).upper(),
                _u(s[u"write_code"]).upper(),
            ),
        })
    return out


def list_subsectors(catalog, plant_code, sector_key):
    p = catalog[u"plants"].get(_u(plant_code).upper())
    if p is None:
        return []
    s = p[u"sectors"].get(_u(sector_key).upper())
    if s is None:
        return []
    out = []
    for ss in sorted(s[u"subsectors"].values(), key=lambda x: _u(x[u"code"])):
        out.append({
            u"code": _u(ss[u"code"]).upper(),
            u"name": _u(ss[u"name"]),
            u"display": u"{0} | {1}".format(_u(ss[u"code"]).upper(), _u(ss[u"name"]) or _u(ss[u"code"]).upper()),
        })
    return out


def list_units(catalog, plant_code, sector_key, subsector_code):
    p = catalog[u"plants"].get(_u(plant_code).upper())
    if p is None:
        return []
    s = p[u"sectors"].get(_u(sector_key).upper())
    if s is None:
        return []
    ss = s[u"subsectors"].get(_u(subsector_code).upper())
    if ss is None:
        return []
    units = ss.get(u"units") or {}
    out = []
    for uo in sorted(units.values(), key=lambda x: _u(x[u"code"])):
        out.append({
            u"code": _u(uo[u"code"]).upper(),
            u"name": _u(uo[u"name"]),
            u"display": u"{0} | {1}".format(_u(uo[u"code"]).upper(), _u(uo[u"name"]) or _u(uo[u"code"]).upper()),
        })
    return out


def validate_hierarchy(catalog, plant_code, sector_key, subsector_code, unit_code=u""):
    p = catalog[u"plants"].get(_u(plant_code).upper())
    if p is None:
        return False, u"La planta no existe en catálogo: {0}".format(plant_code)
    s = p[u"sectors"].get(_u(sector_key).upper())
    if s is None:
        return False, u"El sector no pertenece a la planta {0}: {1}".format(plant_code, sector_key)
    ss = _u(subsector_code).upper()
    if ss:
        if ss not in s[u"subsectors"]:
            return False, u"El subsector no pertenece al sector {0}: {1}".format(sector_key, subsector_code)
    uu = _u(unit_code).upper()
    if uu:
        if not ss:
            return False, u"No se puede seleccionar unidad sin subsector"
        sub_obj = s[u"subsectors"].get(ss) or {}
        units = sub_obj.get(u"units") or {}
        if uu not in units:
            return False, u"La unidad no pertenece al subsector {0}: {1}".format(subsector_code, unit_code)
    return True, u"ok"


def upsert_sector(catalog, plant_code, sector_key, sector_name, sector_write_code):
    p = _ensure_plant(catalog, plant_code, plant_code)
    if p is None:
        return None
    return _ensure_sector(p, sector_key, sector_name, sector_write_code)


def upsert_subsector(catalog, plant_code, sector_key, subsector_name, subsector_code):
    p = catalog[u"plants"].get(_u(plant_code).upper())
    if p is None:
        return False
    s = p[u"sectors"].get(_u(sector_key).upper())
    if s is None:
        return False
    _add_subsector(s, subsector_name, subsector_code)
    return True


def append_catalog_entries(
    catalog,
    output_csv_path,
    plant_code,
    plant_name,
    sector_key,
    sector_name,
    sector_write_code,
    subsector_code=u"",
    subsector_name=u"",
    unit_code=u"",
    unit_name=u"",
):
    parent = os.path.dirname(os.path.abspath(output_csv_path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)

    schema = _u(catalog.get(u"schema")).lower() or u"legacy"
    if schema == u"new":
        header = NEW_REQUIRED
    else:
        header = [
            u"planta_codigo",
            u"sector_codigo",
            u"sector_nombre",
            u"nivel_manual",
            u"nombre_visible",
            u"codigo_lgc",
            u"description_destino",
            u"codigo_sector_lgc",
            u"codigo_subsector_lgc",
            u"codigo_unidad_manual",
            u"nombre_unidad_manual",
        ]

    write_header = not os.path.isfile(output_csv_path) or os.path.getsize(output_csv_path) == 0
    with codecs.open(output_csv_path, u"a", u"utf-8-sig") as fp:
        writer = csv.writer(fp)
        if write_header:
            writer.writerow(header)

        if schema == u"new":
            # En esquema nuevo, cada fila representa sector+subsector.
            if _u(subsector_code):
                writer.writerow([
                    _u(plant_code).upper(),
                    _u(plant_name),
                    _u(sector_key).upper(),
                    _u(sector_name),
                    _u(sector_write_code).upper(),
                    _u(subsector_name),
                    _u(subsector_code).upper(),
                ])
            else:
                # sector sin subsector: dejamos subsector vacio
                writer.writerow([
                    _u(plant_code).upper(),
                    _u(plant_name),
                    _u(sector_key).upper(),
                    _u(sector_name),
                    _u(sector_write_code).upper(),
                    u"",
                    u"",
                ])
        else:
            # Esquema legacy: una fila de sector y opcional fila de subsector.
            writer.writerow([
                _u(plant_code).upper(),
                _u(sector_key).upper(),
                _u(sector_name),
                u"SECTOR",
                _u(sector_name),
                _u(sector_write_code).upper(),
                u"BTZ_Description_02",
                u"",
                u"",
                u"",
                u"",
            ])
            if _u(subsector_code):
                writer.writerow([
                    _u(plant_code).upper(),
                    _u(sector_key).upper(),
                    _u(sector_name),
                    u"SUBSECTOR",
                    _u(subsector_name) or _u(subsector_code).upper(),
                    _u(subsector_code).upper(),
                    u"BTZ_Description_03",
                    _u(sector_write_code).upper(),
                    _u(subsector_code).upper(),
                    u"",
                    u"",
                ])
            if _u(unit_code):
                writer.writerow([
                    _u(plant_code).upper(),
                    _u(sector_key).upper(),
                    _u(sector_name),
                    u"UNIDAD",
                    _u(unit_name) or _u(unit_code).upper(),
                    _u(unit_code).upper(),
                    u"BTZ_Description_04",
                    _u(sector_write_code).upper(),
                    _u(subsector_code).upper(),
                    _u(unit_code).upper(),
                    _u(unit_name) or _u(unit_code).upper(),
                ])
