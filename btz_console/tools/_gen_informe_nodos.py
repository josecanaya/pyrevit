# -*- coding: utf-8 -*-
"""One-off: informe nodos dibujados vs revit_btz_actual.csv + Excel maestro."""
from __future__ import print_function

import csv
import re
import sys
from collections import defaultdict

try:
    import openpyxl
except ImportError:
    openpyxl = None

DOT = r"C:\Users\Usuario\AppData\Roaming\pyRevit\Extensions\btz.extension\resources\nodos_dibujados_y_generales.dot"
REVIT = r"C:\Users\Usuario\AppData\Roaming\pyRevit\Extensions\btz.extension\public\_optional\revit_btz_actual.csv"
XLSX = r"C:\Users\Usuario\AppData\Roaming\pyRevit\Extensions\btz.extension\resources\2026-03-27 EQUIPOS ACTUALIZADOS.xlsx"
# El maestro Excel usa "Número Activo" (SAP/activo), no los códigos TE-/P10-/PP- del árbol.
# Cargarlo entero es lento y no aporta match por código; el informe usa descripción del .dot.
LOAD_EXCEL = False

SKIP_IDS = {"root", "n_PLANT_TE", "n_PLANT_P10", "n_PLANT_PP"}

GENERAL_PARENT_CODES = {
    "TE-TDM-GENERAL",
    "P10-HRN-SECADORES",
    "PP-HRN-GENERAL",
}


def plant_from_code(code):
    if code.startswith("TE-"):
        return "TE"
    if code.startswith("P10-"):
        return "P10"
    if code.startswith("PP-"):
        return "PP"
    return ""


def parse_dot(path):
    nodes = {}
    edges = []
    pat_node = re.compile(
        r'^\s*(?P<id>n_[A-Za-z0-9_]+)\s*\[label="(?P<label>[^"]*)"'
    )
    pat_edge = re.compile(
        r"^\s*(?P<a>n_[A-Za-z0-9_]+)\s*->\s*(?P<b>n_[A-Za-z0-9_]+)\s*;"
    )
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = pat_node.match(line)
            if m:
                nid = m.group("id")
                raw = m.group("label").replace("\\n", "\n")
                parts = raw.split("\n", 1)
                if len(parts) == 1:
                    single = parts[0].strip()
                    if re.match(r"^(TE|P10|PP)-", single):
                        desc = ""
                        code = single
                    else:
                        desc = single
                        code = ""
                else:
                    desc = parts[0].strip()
                    code = parts[1].strip()
                nodes[nid] = {"desc": desc, "code": code}
                continue
            m = pat_edge.match(line)
            if m:
                edges.append((m.group("a"), m.group("b")))
    children = defaultdict(list)
    parents = {}
    for a, b in edges:
        if a == b:
            continue
        children[a].append(b)
        parents[b] = a
    return nodes, children, parents


def load_excel_codes(path):
    if not openpyxl:
        return {}
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = {}
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        try:
            header = next(rows)
        except StopIteration:
            continue
        cols = [str(c).strip() if c is not None else "" for c in header]
        li = None
        for i, name in enumerate(cols):
            up = name.upper()
            if (
                "CODIGO" in up
                or "CÓDIGO" in up
                or up == "CODE"
                or up == "BTZ"
                or "NUMERO ACTIVO" in up
                or "NÚMERO ACTIVO" in up
            ):
                li = i
                break
        if li is None:
            continue
        di = None
        for i, name in enumerate(cols):
            up = name.upper()
            if (
                "DESCRIP" in up
                or up == "DESC"
                or "DESCRIPCION" in up
                or "DESCRIPCIÓN" in up
            ):
                di = i
                break
        for row in rows:
            if not row or li >= len(row):
                continue
            code = row[li]
            if code is None:
                continue
            code = str(code).strip()
            if not code or code.upper() == "CODE":
                continue
            d = ""
            if di is not None and di < len(row) and row[di] is not None:
                d = str(row[di]).strip()
            if code not in out and d:
                out[code] = d
    wb.close()
    return out


def load_revit(path):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows


def norm_cell(s):
    if s is None:
        return ""
    return str(s).strip()


def main():
    nodes, children, parents = parse_dot(DOT)
    excel_desc = load_excel_codes(XLSX) if LOAD_EXCEL and openpyxl else {}
    revit_rows = load_revit(REVIT)

    code_to_elements = defaultdict(list)
    all_btz_vals = set()
    for row in revit_rows:
        eid = norm_cell(row.get("element_id"))
        vals = []
        for k in ("btz_01", "btz_02", "btz_03", "btz_04"):
            v = norm_cell(row.get(k))
            if v:
                vals.append(v)
                all_btz_vals.add(v)
        for v in vals:
            code_to_elements[v].append(
                {"id": eid, "cols": vals, "row": row}
            )

    # Map node id -> sector heading (direct child of plant or logical sector)
    plant_nodes = {"n_PLANT_TE", "n_PLANT_P10", "n_PLANT_PP"}

    def sector_title_for(nid):
        """Primer grupo bajo la planta: hijo directo de n_PLANT_* en la cadena de padres."""
        cur = nid
        while cur:
            p = parents.get(cur)
            if p in plant_nodes:
                info = nodes.get(cur, {})
                return info.get("desc") or info.get("code") or cur
            if not p:
                break
            cur = p
        info = nodes.get(nid, {})
        return info.get("desc") or info.get("code") or ""

    def under_general(nid):
        cur = nid
        while cur:
            info = nodes.get(cur, {})
            c = info.get("code", "")
            if c in GENERAL_PARENT_CODES:
                return c
            cur = parents.get(cur)
        return ""

    expected = []
    for nid, info in sorted(nodes.items(), key=lambda x: x[0]):
        if nid in SKIP_IDS:
            continue
        code = info.get("code") or ""
        if not code:
            continue
        if code in GENERAL_PARENT_CODES:
            continue
        if nid.startswith("n_PLANT_"):
            continue
        desc = info.get("desc") or excel_desc.get(code, "")
        if not desc:
            desc = excel_desc.get(code, "")
        plant = plant_from_code(code)
        sector = sector_title_for(nid)
        gen = under_general(nid)
        expected.append(
            {
                "nid": nid,
                "code": code,
                "desc": desc,
                "plant": plant,
                "sector": sector,
                "general": gen,
            }
        )

    # Classify
    results = []
    for item in expected:
        code = item["code"]
        hits = code_to_elements.get(code, [])
        n = len(hits)
        plant = item["plant"]
        state = ""
        where = ""
        obs = ""

        if n == 0:
            if item["general"]:
                state = "ABSORBIDO EN GENERAL"
                where = "(sin coincidencia exacta en export BTZ)"
                obs = (
                    "Previsto bajo "
                    + item["general"]
                    + " en arbol; no aparece como codigo propio en revit_btz_actual.csv"
                )
            else:
                state = "NO ENCONTRADO EN MODELO"
                where = ""
                obs = "Codigo no aparece en btz_01..04 del export"
        elif n > 1:
            state = "EXISTE MAS DE UNA VEZ"
            where = ", ".join(sorted({h["id"] for h in hits[:8]}))
            if n > 8:
                where += ", ..."
            obs = "%s elementos con ese codigo en BTZ" % n
        else:
            h = hits[0]
            cols = h["cols"]
            where = "element_id=%s; BTZ=%s" % (h["id"], " | ".join(cols))
            col_plants = []
            for c in cols:
                if c in ("TE", "P10", "PP"):
                    col_plants.append(c)
                elif c.startswith("TE-"):
                    col_plants.append("TE")
                elif c.startswith("P10-"):
                    col_plants.append("P10")
                elif c.startswith("PP-"):
                    col_plants.append("PP")
            bad_plant = bool(col_plants and plant and not any(p == plant for p in col_plants))
            if bad_plant:
                state = "EXISTE PERO MAL CLASIFICADO"
                obs = "Planta esperada %s vs columnas BTZ" % plant
            else:
                state = "DIBUJADO OK"
                if item["general"]:
                    obs = "En arbol bajo bloque General; en modelo aparece codigo explicito"
                else:
                    obs = ""

        if n == 1 and state == "DIBUJADO OK":
            b1 = norm_cell(hits[0]["row"].get("btz_01"))
            if not b1 and plant:
                state = "DUDOSO / POSIBLE MATCH"
                obs = "btz_01 vacio en export"
            elif b1 and b1 not in ("TE", "P10", "PP"):
                if b1.startswith(plant + "-") and plant_from_code(b1) == plant:
                    state = "DUDOSO / POSIBLE MATCH"
                    obs = (
                        "btz_01 no es planta literal; valor=%s (jerarquia inconsistente?)"
                        % b1
                    )

        results.append(
            {
                **item,
                "state": state,
                "where": where,
                "obs": obs,
                "n": n,
            }
        )

    # Sobrantes: valores en modelo que look like full codes but not in expected set
    expected_codes = {x["code"] for x in expected}
    extra = []
    for v in sorted(all_btz_vals):
        if not re.match(r"^(TE|P10|PP)-", v):
            continue
        if v in ("TE", "P10", "PP"):
            continue
        if v not in expected_codes and v not in GENERAL_PARENT_CODES:
            extra.append(v)

    # Counts
    def tally(key):
        return sum(1 for r in results if r["state"] == key)

    states_order = [
        "DIBUJADO OK",
        "NO ENCONTRADO EN MODELO",
        "DUDOSO / POSIBLE MATCH",
        "ABSORBIDO EN GENERAL",
        "EXISTE PERO MAL CLASIFICADO",
        "EXISTE MAS DE UNA VEZ",
    ]
    summary = {s: tally(s) for s in states_order}

    out_lines = []
    out_lines.append("## A. Resumen general")
    out_lines.append(
        "- Nodos esperados (arbol): %s" % len(expected)
    )
    out_lines.append(
        "- DIBUJADO OK: %s" % summary["DIBUJADO OK"]
    )
    out_lines.append(
        "- NO ENCONTRADO EN MODELO: %s" % summary["NO ENCONTRADO EN MODELO"]
    )
    out_lines.append(
        "- DUDOSO / POSIBLE MATCH: %s" % summary["DUDOSO / POSIBLE MATCH"]
    )
    out_lines.append(
        "- ABSORBIDO EN GENERAL: %s" % summary["ABSORBIDO EN GENERAL"]
    )
    out_lines.append(
        "- EXISTE PERO MAL CLASIFICADO: %s" % summary["EXISTE PERO MAL CLASIFICADO"]
    )
    out_lines.append(
        "- EXISTE MAS DE UNA VEZ: %s" % summary["EXISTE MAS DE UNA VEZ"]
    )
    out_lines.append(
        "- Codigos en modelo tipo *-... no listados en arbol (sobrantes): %s"
        % len(extra)
    )
    out_lines.append("")
    out_lines.append(
        "_Fuente modelo: public/_optional/revit_btz_actual.csv (export BTZ). "
        "Si el proyecto cambio, reexportar antes de usar este informe._"
    )
    out_lines.append("")

    by_plant = defaultdict(lambda: defaultdict(list))
    for r in results:
        by_plant[r["plant"]][r["sector"]].append(r)

    plant_order = ["TE", "P10", "PP"]
    for pl in plant_order:
        out_lines.append("## %s" % pl)
        sectors = by_plant.get(pl, {})
        for sec in sorted(sectors.keys(), key=lambda x: (x or "").lower()):
            out_lines.append("### %s" % (sec or "(sin sector)"))
            for r in sorted(sectors[sec], key=lambda x: x["code"]):
                d = r["desc"] or excel_desc.get(r["code"], "") or "—"
                line = (
                    "- %s -> **%s** -- %s"
                    % (r["code"], r["state"], d)
                )
                if r["where"]:
                    line += " | *Donde:* %s" % r["where"]
                if r["obs"]:
                    line += " | *Obs:* %s" % r["obs"]
                out_lines.append(line)
            out_lines.append("")

    out_lines.append("---")
    out_lines.append("")
    out_lines.append("## 1. FALTAN DIBUJAR (solo codigos NO ENCONTRADO EN MODELO)")
    for r in sorted(
        [x for x in results if x["state"] == "NO ENCONTRADO EN MODELO"],
        key=lambda x: x["code"],
    ):
        out_lines.append("- " + r["code"])
    out_lines.append("")
    out_lines.append(
        "## 2. REVISAR CLASIFICACION (dudoso, mal clasificado, duplicado)"
    )
    for r in sorted(
        [
            x
            for x in results
            if x["state"]
            in (
                "DUDOSO / POSIBLE MATCH",
                "EXISTE PERO MAL CLASIFICADO",
                "EXISTE MAS DE UNA VEZ",
            )
        ],
        key=lambda x: x["code"],
    ):
        out_lines.append("- %s -- %s" % (r["code"], r["state"]))
    out_lines.append("")
    out_lines.append("## 3. YA ESTAN BIEN (DIBUJADO OK)")
    for r in sorted(
        [x for x in results if x["state"] == "DIBUJADO OK"],
        key=lambda x: x["code"],
    ):
        out_lines.append("- " + r["code"])
    out_lines.append("")
    out_lines.append("## Sobrantes en modelo (codigo BTZ no esta en arbol)")
    for v in extra:
        out_lines.append("- %s" % v)

    text = "\n".join(out_lines)
    sys.stdout.write(text.encode("utf-8", errors="replace").decode("utf-8"))
    try:
        sys.stdout.write("\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()