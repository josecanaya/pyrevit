# -*- coding: utf-8 -*-
"""
Replica la normalización de ExportarGrupos (raw_output + reparación JSON).
Uso: desde la carpeta public →  python verify_webhook_response.py
"""
from __future__ import print_function

import codecs
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
WEBHOOK_PATH = os.path.join(HERE, "webhook_response.json")
GK_PATH = os.path.join(HERE, "group_key_element_ids.json")


def _repair_duplicate_reason_confidence_in_json(s):
    pat = r'("reason"\s*:\s*"((?:[^"\\]|\\.)*)")\s*,\s*\n\s*"confidence"\s*:\s*[^,]+,\s*\n\s*"reason"\s*:\s*"\2"'
    prev = None
    while prev != s:
        prev = s
        s = re.sub(pat, r"\1\n        }", s)
    return s


def _parse_json_from_raw_output(raw, log_lines):
    raw_str = raw.strip() if isinstance(raw, str) else str(raw).strip()
    if not raw_str:
        return None
    try:
        return json.loads(raw_str)
    except Exception as ex:
        log_lines.append("raw_output: JSON inválido ({0}); reparando…".format(ex))
    try:
        repaired = _repair_duplicate_reason_confidence_in_json(raw_str)
        return json.loads(repaired)
    except Exception as ex2:
        log_lines.append("raw_output: sigue sin parsear: {0}".format(ex2))
        return None


def normalize_webhook_response(parsed, log_lines):
    if isinstance(parsed, list):
        if not parsed:
            raise ValueError("lista vacía en la raíz")
        merged = None
        for item in parsed:
            if not isinstance(item, dict):
                continue
            if merged is None:
                merged = dict(item)
            else:
                gm_a = merged.get("group_mappings") or []
                gm_b = item.get("group_mappings") or []
                if isinstance(gm_a, list) and isinstance(gm_b, list):
                    merged["group_mappings"] = gm_a + gm_b
        if merged is None:
            raise ValueError("lista sin objetos válidos")
        parsed = merged

    if not isinstance(parsed, dict):
        raise ValueError("no es un objeto JSON")

    gm = parsed.get("group_mappings")
    if gm is None:
        gm = []
    if not isinstance(gm, list):
        gm = []

    if len(gm) == 0:
        raw = parsed.get("raw_output")
        if raw:
            inner = _parse_json_from_raw_output(raw, log_lines)
            if isinstance(inner, list):
                inner = inner[0] if (len(inner) and isinstance(inner[0], dict)) else None
            if isinstance(inner, dict):
                gm2 = inner.get("group_mappings")
                if isinstance(gm2, list) and len(gm2) > 0:
                    log_lines.append(
                        "group_mappings vacío en raíz; se usó raw_output ({0} grupos).".format(
                            len(gm2)
                        )
                    )
                    out = {
                        "mode": inner.get("mode") or "group_btz_mapping_result",
                        "group_mappings": gm2,
                    }
                    if inner.get("project_name") is not None:
                        out["project_name"] = inner["project_name"]
                    return out

    return parsed


def load_group_mapping_response(parsed, log_lines):
    parsed = normalize_webhook_response(parsed, log_lines)
    mode = parsed.get("mode")
    if mode != "group_btz_mapping_result":
        raise ValueError("mode inesperado: {0}".format(mode))
    gm = parsed.get("group_mappings")
    if gm is None:
        raise ValueError("falta group_mappings")
    if not isinstance(gm, list):
        raise ValueError("group_mappings debe ser lista")
    return gm


def main():
    log_lines = []
    print("Archivo:", WEBHOOK_PATH)
    with codecs.open(WEBHOOK_PATH, "r", "utf-8-sig") as fp:
        root = json.loads(fp.read())

    gms = load_group_mapping_response(root, log_lines)
    print("\n".join(log_lines))
    print("---")
    print("Grupos en respuesta (tras normalizar):", len(gms))
    for i, g in enumerate(gms, 1):
        gk = g.get("group_key", "")
        ncb = len(g.get("candidate_btz") or [])
        print("  {0}. {1} | candidate_btz: {2}".format(i, gk[:70], ncb))

    if os.path.isfile(GK_PATH):
        with codecs.open(GK_PATH, "r", "utf-8-sig") as fp:
            gk_map = json.loads(fp.read())
        keys_revit = set(gk_map.keys())
        keys_n8n = set(g.get("group_key") for g in gms if g.get("group_key"))
        both = keys_revit & keys_n8n
        only_revit = keys_revit - keys_n8n
        only_n8n = keys_n8n - keys_revit
        print("---")
        print("group_key_element_ids.json: {0} claves".format(len(keys_revit)))
        print("Coinciden Revit y n8n (misma clave):", len(both))
        if only_n8n:
            print("Solo en n8n ({0}):".format(len(only_n8n)))
            for k in sorted(only_n8n)[:8]:
                print("   ", k[:75])
            if len(only_n8n) > 8:
                print("   …")
        if only_revit:
            print("Solo en export Revit ({0}):".format(len(only_revit)))
            for k in sorted(only_revit)[:8]:
                print("   ", k[:75])
            if len(only_revit) > 8:
                print("   …")
    else:
        print("---")
        print("(No hay group_key_element_ids.json para cruzar claves.)")


if __name__ == "__main__":
    main()
