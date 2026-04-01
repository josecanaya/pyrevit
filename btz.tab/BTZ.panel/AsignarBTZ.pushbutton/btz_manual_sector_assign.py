# -*- coding: utf-8 -*-
from __future__ import print_function

import csv
import codecs

try:
    unicode
except NameError:
    unicode = str


CSV_REQUIRED_COLUMNS = [
    u"planta_codigo",
    u"sector_codigo",
    u"sector_nombre",
    u"nivel_manual",
    u"nombre_visible",
    u"codigo_lgc",
    u"description_destino",
    u"codigo_sector_lgc",
]


def _u(v):
    return unicode(v or u"").strip()


def _norm_header(h):
    return (
        _u(h)
        .replace(u"\ufeff", u"")
        .replace(u"\x00", u"")
        .strip()
        .lower()
    )


def _split_csv_line(line, delim):
    # parser simple robusto para IronPython; suficiente para este CSV sin escapados complejos
    parts = []
    buf = []
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == u'"':
            # doble comilla escapada
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


def load_manual_sector_csv(csv_path):
    """
    Carga CSV manual de sectores/subsectores.
    Retorna lista de filas normalizadas.
    """
    encodings = [
        u"utf-8-sig",
        u"utf-8",
        u"utf-16",
        u"utf-16-le",
        u"utf-16-be",
        u"cp1252",
        u"latin1",
    ]
    last_error = None
    last_headers = []
    for enc in encodings:
        try:
            with codecs.open(csv_path, u"r", enc) as fp:
                raw = fp.read()
            raw = raw.replace(u"\x00", u"")
            lines = [ln for ln in raw.splitlines() if _u(ln)]
            if not lines:
                raise ValueError(u"CSV manual vacío")

            # detectar separador por cabecera real
            header_line = lines[0]
            delim = u","
            counts = [
                (u",", header_line.count(u",")),
                (u";", header_line.count(u";")),
                (u"\t", header_line.count(u"\t")),
            ]
            counts.sort(key=lambda x: x[1], reverse=True)
            if counts[0][1] > 0:
                delim = counts[0][0]

            headers = [_u(x) for x in _split_csv_line(header_line, delim)]
            last_headers = headers
            index = {}
            for i, name in enumerate(headers):
                index[_norm_header(name)] = i

            missing = [c for c in CSV_REQUIRED_COLUMNS if _norm_header(c) not in index]
            if missing:
                raise ValueError(
                    u"CSV manual inválido: faltan columnas {0}. Encabezados detectados: {1}".format(
                        u", ".join(missing),
                        u", ".join(headers),
                    )
                )

            out = []
            for line in lines[1:]:
                cols = _split_csv_line(line, delim)
                if not cols:
                    continue
                n = {}
                for c in CSV_REQUIRED_COLUMNS:
                    pos = index[_norm_header(c)]
                    n[c] = _u(cols[pos]) if pos < len(cols) else u""
                lvl = n[u"nivel_manual"].upper()
                if lvl not in (u"SECTOR", u"SUBSECTOR"):
                    continue
                if not n[u"codigo_lgc"]:
                    continue
                out.append(n)

            if not out:
                raise ValueError(u"CSV manual sin filas útiles")
            return out
        except Exception as ex:
            last_error = ex
            continue

    raise ValueError(
        u"No se pudo leer CSV manual: {0} | archivo={1} | headers_detectados={2}".format(
            last_error,
            csv_path,
            u", ".join(last_headers) if last_headers else u"(sin cabecera)",
        )
    )


def build_sector_options(rows, planta_codigo=None):
    """
    Opciones para BTZ_Description_01 (SECTOR).
    """
    planta = _u(planta_codigo).upper()
    seen = set()
    out = []
    for r in rows:
        if _u(r.get(u"nivel_manual")).upper() != u"SECTOR":
            continue
        pl = _u(r.get(u"planta_codigo"))
        if planta and pl.upper() != planta:
            continue
        code = _u(r.get(u"codigo_lgc"))
        if not code or code in seen:
            continue
        seen.add(code)
        out.append({
            u"planta_codigo": pl,
            u"sector_codigo": _u(r.get(u"sector_codigo")),
            u"sector_nombre": _u(r.get(u"sector_nombre")),
            u"nombre_visible": _u(r.get(u"nombre_visible")),
            u"codigo_lgc": code,
            u"display": u"{0} | {1} | {2}".format(
                pl or u"-",
                _u(r.get(u"sector_codigo")) or u"-",
                _u(r.get(u"nombre_visible")) or _u(r.get(u"sector_nombre")) or u"-",
            ),
        })
    out.sort(key=lambda x: x[u"display"].lower())
    return out


def build_subsector_options(rows, sector_codigo_lgc):
    """
    Opciones para BTZ_Description_02 (SUBSECTOR) filtradas por sector padre.
    """
    sector_parent = _u(sector_codigo_lgc)
    seen = set()
    out = []
    for r in rows:
        if _u(r.get(u"nivel_manual")).upper() != u"SUBSECTOR":
            continue
        if _u(r.get(u"codigo_sector_lgc")) != sector_parent:
            continue
        code = _u(r.get(u"codigo_lgc"))
        if not code or code in seen:
            continue
        seen.add(code)
        out.append({
            u"nombre_visible": _u(r.get(u"nombre_visible")),
            u"codigo_lgc": code,
            u"codigo_sector_lgc": _u(r.get(u"codigo_sector_lgc")),
            u"display": _u(r.get(u"nombre_visible")) or code,
        })
    out.sort(key=lambda x: x[u"display"].lower())
    return out


def prompt_manual_sector_subsector_ui(rows, forms):
    """
    UI manual 2 niveles:
    - sector
    - subsector dependiente
    """
    plantas = sorted(list(set(_u(r.get(u"planta_codigo")) for r in rows if _u(r.get(u"planta_codigo")))))
    planta_filter = u""
    if len(plantas) > 1:
        options = [u"(Todas)"] + plantas
        picked = forms.SelectFromList.show(
            options,
            title=u"Filtro planta (opcional)",
            button_name=u"Usar planta",
            multiselect=False,
            width=500,
            height=420,
        )
        if picked is None:
            return None
        planta_filter = u"" if _u(picked) == u"(Todas)" else _u(picked)
    elif len(plantas) == 1:
        planta_filter = plantas[0]

    sectors = build_sector_options(rows, planta_filter)
    if not sectors:
        forms.alert(
            u"No hay sectores disponibles para la planta seleccionada.",
            title=u"Asignar BTZ manual",
            warn_icon=True,
        )
        return None

    sector_displays = [s[u"display"] for s in sectors]
    sector_pick = forms.SelectFromList.show(
        sector_displays,
        title=u"Elegir sector (BTZ_Description_01)",
        button_name=u"Usar sector",
        multiselect=False,
        width=900,
        height=640,
    )
    if not sector_pick:
        return None
    selected_sector = None
    for s in sectors:
        if s[u"display"] == sector_pick:
            selected_sector = s
            break
    if selected_sector is None:
        return None

    subsectors = build_subsector_options(rows, selected_sector[u"codigo_lgc"])
    subsector_code = u""
    if subsectors:
        sub_options = [u"(Sin subsector)"] + [x[u"display"] for x in subsectors]
        sub_pick = forms.SelectFromList.show(
            sub_options,
            title=u"Elegir subsector (BTZ_Description_02)",
            button_name=u"Usar subsector",
            multiselect=False,
            width=900,
            height=640,
        )
        if sub_pick is None:
            return None
        if _u(sub_pick) != u"(Sin subsector)":
            for x in subsectors:
                if x[u"display"] == sub_pick:
                    subsector_code = x[u"codigo_lgc"]
                    break

    return {
        u"planta_codigo": selected_sector[u"planta_codigo"],
        u"sector_display": selected_sector[u"display"],
        u"sector_code": selected_sector[u"codigo_lgc"],
        u"subsector_code": subsector_code,
        u"subsector_display": (
            next((x[u"display"] for x in subsectors if x[u"codigo_lgc"] == subsector_code), u"")
            if subsector_code
            else u""
        ),
    }


def apply_manual_sector_subsector(
    doc,
    elements,
    sector_code,
    subsector_code,
    set_text_parameter,
    get_current_value,
):
    """
    Escribe:
    - BTZ_Description_01 = sector_code
    - BTZ_Description_02 = subsector_code (o vacío)
    """
    result = {
        u"modified": 0,
        u"unchanged": 0,
        u"errors": [],
    }
    sub_val = _u(subsector_code)
    sec_val = _u(sector_code)

    for el in elements:
        eid = u"?"
        try:
            eid = unicode(el.Id)
        except Exception:
            pass

        current_sec = _u(get_current_value(el, u"BTZ_Description_01"))
        current_sub = _u(get_current_value(el, u"BTZ_Description_02"))
        if current_sec == sec_val and current_sub == sub_val:
            result[u"unchanged"] += 1
            continue

        ok1, err1 = set_text_parameter(el, u"BTZ_Description_01", sec_val)
        if not ok1:
            result[u"errors"].append(u"Id {0} BTZ_Description_01: {1}".format(eid, err1 or u"error"))
            continue
        ok2, err2 = set_text_parameter(el, u"BTZ_Description_02", sub_val)
        if not ok2:
            result[u"errors"].append(u"Id {0} BTZ_Description_02: {1}".format(eid, err2 or u"error"))
            continue
        result[u"modified"] += 1

    return result
