# -*- coding: utf-8 -*-
"""
Enriquecimiento de grupos base con blocks.csv ANTES del webhook/LLM.
Conservador: scores heurísticos, splits solo con evidencia (p. ej. nivel distinto).
"""
from __future__ import print_function

import codecs
import json
import os
import re

try:
    unicode
except NameError:
    unicode = str

from btz_element_metadata import (
    aggregate_semantic_text,
    semantic_keys_for_blob,
    unique_values_by_column,
)

# Texto máximo para heurística blocks (modelos enormes)
BLOB_MAX_CHARS = 12000
MASSIVE_GROUP_MIN_COUNT = 30
MAX_COMBO_SPLITS = 80

# --- Umbrales (alineados al pedido) ---
AUTO_TOP1_MIN = 0.75
AUTO_GAP_MIN = 0.20
REVIEW_TOP1_MIN = 0.55
SPLIT_GAP_MAX = 0.15
STRONG_MIN = 0.35


def _slug(s):
    s = (s or u"").strip()
    out = []
    for ch in s:
        if ch.isalnum() or ch in (u"-", u"_"):
            out.append(ch)
        else:
            out.append(u"_")
    t = u"".join(out)
    t = re.sub(u"_+", u"_", t).strip(u"_")
    return (t or u"UNK")[:80]


def _tokens(s):
    s = (s or u"").lower()
    return set(re.findall(u"[a-záéíóúñ0-9]{3,}", s, flags=re.UNICODE))


def _collect_existing_btz(rows_subset, all_btz_param_names):
    vals = set()
    for r in rows_subset:
        for p in all_btz_param_names:
            v = (r.get(p) or u"").strip()
            if v:
                vals.add(v)
    return sorted(vals)[:30]


def _score_block_row_for_group(group_blob, macro_lower, block_row):
    """
    Score heurístico fila blocks vs texto agregado del grupo (macro|cat|fam|tipo).
    """
    desc = (block_row.get(u"description") or u"").lower()
    code = (block_row.get(u"code") or u"").lower()
    flags = block_row.get(u"flags") or {}
    score = 0.0
    blob = group_blob.lower()

    for t in _tokens(desc):
        if len(t) < 4:
            continue
        if t in blob:
            score += 2.5
        elif t[:5] in blob:
            score += 1.0

    for t in _tokens(blob):
        if len(t) > 4 and t in desc:
            score += 1.5

    for col, val in flags.items():
        try:
            if int(val) != 1:
                continue
        except Exception:
            continue
        col_l = (col or u"").lower()
        for part in col_l.replace(u"_", u" ").split():
            if len(part) > 3 and part in blob:
                score += 1.2
            if len(part) > 3 and part in desc:
                score += 0.8

    if macro_lower == u"estructura":
        for kw in (u"estructura", u"column", u"pilar", u"cercha", u"cubierta", u"correa", u"montaje", u"fundaci", u"excav", u"metal"):
            if kw in desc:
                score += 1.0
    if macro_lower == u"obra_gris":
        for kw in (u"hormig", u"losa", u"muro", u"platea", u"zapata"):
            if kw in desc:
                score += 0.8
    if macro_lower == u"instalaciones":
        for kw in (u"electr", u"gas", u"sanit", u"duct", u"agua"):
            if kw in desc:
                score += 0.8

    if code and code in blob.replace(u" ", u""):
        score += 0.5

    return score


def _normalize_top_scores(raw_scores):
    """raw_scores: list of (row, score) sorted by score desc -> confidences 0-1"""
    if not raw_scores:
        return [], 0.0, 0.0, 1.0
    top = raw_scores[0][1]
    if top <= 0:
        return raw_scores, 0.0, 0.0, 1.0
    n1 = min(1.0, raw_scores[0][1] / (top + 1e-6))
    n2 = min(1.0, raw_scores[1][1] / (top + 1e-6)) if len(raw_scores) > 1 else 0.0
    amb = max(0.0, min(1.0, 1.0 - (n1 - n2)))
    return raw_scores, n1, n2, amb


def _rows_for_group_key(element_rows, gkey):
    return [r for r in element_rows if r.get(u"group_key") == gkey]


def enrich_groups_with_blocks(element_rows, groups, blocks_struct, all_btz_param_names, log_lines):
    """
    Perfil enriquecido por base_group_key usando blocks.csv.
    """
    rows_blocks = blocks_struct.get(u"rows") or []
    enriched = []

    for g in groups:
        gk = g[u"group_key"]
        macro = g[u"macro_group"]
        cat = g[u"category_name"]
        fam = g[u"family_name"]
        typ = g[u"type_name"]
        erows = _rows_for_group_key(element_rows, gk)
        sk = semantic_keys_for_blob()
        extra_txt = aggregate_semantic_text(erows, sk)
        group_blob = u" ".join([macro, cat, fam, typ])
        if extra_txt:
            group_blob = (group_blob + u" " + extra_txt).strip()
        if len(group_blob) > BLOB_MAX_CHARS:
            group_blob = group_blob[:BLOB_MAX_CHARS]
        macro_l = (macro or u"").lower()

        semantic_field_summary = unique_values_by_column(erows, sk)
        existing_btz = _collect_existing_btz(erows, all_btz_param_names)
        sample_ids = [int(x) for x in g[u"sample_element_ids"]]
        element_count = int(g[u"count"])

        raw_scored = []
        for br in rows_blocks:
            sc = _score_block_row_for_group(group_blob, macro_l, br)
            if sc > 0:
                raw_scored.append((br, sc))

        raw_scored.sort(key=lambda x: -x[1])
        scored, n1, n2, amb = _normalize_top_scores(raw_scored)

        candidate_btz = []
        dominant = None
        dom_conf = 0.0
        max_s = scored[0][1] if scored else 1.0
        for br, sc in scored[:8]:
            disp = u"{0} - {1}".format(br[u"code"], br[u"description"]).strip()
            fl = br.get(u"flags") or {}
            active_cols = [k for k, v in fl.items() if int(v) == 1]
            active_cols.sort()
            conf = min(1.0, sc / (max_s + 1e-6)) if scored else 0.0
            candidate_btz.append({
                u"matched_code": br[u"code"],
                u"suggested_value": br[u"description"],
                u"display_value": disp,
                u"matching_columns": active_cols[:12],
                u"confidence": round(conf, 4),
                u"reason": u"Heurístico blocks.csv vs texto de grupo",
            })
        if candidate_btz:
            dominant = candidate_btz[0]
        dom_conf = round(n1, 4)

        cand_cols = {}
        for br, _sc in scored[:12]:
            for k, v in (br.get(u"flags") or {}).items():
                if int(v) == 1:
                    cand_cols[k] = cand_cols.get(k, 0) + 1
        candidate_columns = [
            {u"column_name": k, u"weight": float(v)}
            for k, v in sorted(cand_cols.items(), key=lambda x: -x[1])[:15]
        ]

        should_split = False
        split_reason = u""

        if n1 >= AUTO_TOP1_MIN and (n1 - n2) >= AUTO_GAP_MIN:
            should_split = False
        elif len(scored) >= 2 and n1 >= STRONG_MIN and n2 >= STRONG_MIN and (n1 - n2) < SPLIT_GAP_MAX:
            should_split = True
            split_reason = u"dos+ candidatos fuertes con scores cercanos (Δ < {0})".format(SPLIT_GAP_MAX)
        elif (u"generic" in (cat or u"").lower()) or (cat or u"").strip() == u"Generic Models":
            should_split = True
            split_reason = u"categoría genérica (Generic Models / ambigua)"

        if not should_split and n1 >= REVIEW_TOP1_MIN and (n1 - n2) < AUTO_GAP_MIN:
            split_reason = u"revisión: top1 claro pero gap pequeño vs segundo"

        if should_split:
            log_lines.append(
                u"Grupo base {0} -> {1} filas blocks con score -> should_split=True ({2})".format(
                    gk[:90], len(scored), split_reason or u"—"
                )
            )

        supporting = []
        for br, sc in scored[:5]:
            supporting.append({
                u"code": br[u"code"],
                u"description": br[u"description"],
                u"score": round(sc, 3),
                u"active_flags": {k: v for k, v in (br.get(u"flags") or {}).items() if int(v) == 1},
            })

        enriched.append({
            u"base_group_key": gk,
            u"macro_group": macro,
            u"category_name": cat,
            u"family_name": fam,
            u"type_name": typ,
            u"element_count": element_count,
            u"sample_element_ids": sample_ids,
            u"semantic_field_summary": semantic_field_summary,
            u"existing_btz_values_detected": existing_btz,
            u"candidate_columns": candidate_columns,
            u"candidate_btz": candidate_btz,
            u"dominant_candidate": dominant,
            u"dominant_confidence": dom_conf,
            u"ambiguity_score": round(amb, 4),
            u"should_split": should_split,
            u"split_reason": split_reason,
            u"blocks_supporting_rows": supporting,
            u"_normalized_top1": n1,
            u"_normalized_top2": n2,
            u"_raw_scored_count": len(scored),
        })

    log_lines.append(
        u"Enriquecimiento blocks: {0} grupos base perfilados.".format(len(enriched))
    )
    return enriched


def split_ambiguous_groups(enriched, element_rows, log_lines):
    """
    Genera refined_group_key y reparte element_ids. Sin evidencia real → un solo refined + review.
    """
    refined_out = []
    manifest = {}
    split_digest = []

    for eg in enriched:
        base = eg[u"base_group_key"]
        # should_split ya incorpora reglas en enrich; no exigir 2 filas scored (p. ej. Generic Models)
        should = bool(eg.get(u"should_split"))
        erows = _rows_for_group_key(element_rows, base)
        id_list = [int(r[u"element_id"]) for r in erows]

        levels = {}
        for r in erows:
            lv = (r.get(u"level_name") or u"").strip() or u"(sin nivel)"
            levels.setdefault(lv, []).append(int(r[u"element_id"]))

        types = {}
        for r in erows:
            tn = (r.get(u"type_name") or u"").strip() or u"(sin tipo)"
            types.setdefault(tn, []).append(int(r[u"element_id"]))

        worksets = {}
        for r in erows:
            wn = (r.get(u"workset") or u"").strip() or u"(sin workset)"
            worksets.setdefault(wn, []).append(int(r[u"element_id"]))

        # Split forzado en grupos muy masivos con diversidad real (aunque should_split=False)
        combo_map = {}
        for r in erows:
            lv = (r.get(u"level_name") or u"").strip() or u"(sin nivel)"
            tn = (r.get(u"type_name") or u"").strip() or u"(sin tipo)"
            wn = (r.get(u"workset") or u"").strip() or u"(sin workset)"
            ck = (lv, tn, wn)
            combo_map.setdefault(ck, []).append(int(r[u"element_id"]))
        if (not should) and len(erows) >= MASSIVE_GROUP_MIN_COUNT and len(combo_map) > 1:
            should = True
            eg[u"split_reason"] = (
                u"grupo masivo ({0}) con {1} combinaciones nivel+tipo+workset".format(
                    len(erows), len(combo_map)
                )
            )
            log_lines.append(
                u"Grupo base {0}: split forzado por masividad/diversidad ({1} combos).".format(
                    base[:90], len(combo_map)
                )
            )

        refined_list = []

        if should and len(combo_map) > 1 and len(combo_map) <= MAX_COMBO_SPLITS:
            for (lv, tn, wn), ids in sorted(combo_map.items(), key=lambda x: -len(x[1])):
                rk = u"{0}||ref|lvtypws:{1}__{2}__{3}".format(base, _slug(lv), _slug(tn), _slug(wn))
                refined_list.append({
                    u"refined_group_key": rk,
                    u"group_origin": u"split",
                    u"element_ids": ids,
                    u"split_axis": u"level+type+workset",
                    u"split_value": u"{0} | {1} | {2}".format(lv, tn, wn),
                })
            _msg = u"SPLIT {0} -> {1} subgrupos por nivel+tipo+workset.".format(base[:60], len(refined_list))
            split_digest.append(_msg)
            log_lines.append(_msg)
        elif should and len(levels) > 1:
            for lv, ids in sorted(levels.items(), key=lambda x: x[0].lower()):
                rk = u"{0}||ref|lvl:{1}".format(base, _slug(lv))
                refined_list.append({
                    u"refined_group_key": rk,
                    u"group_origin": u"split",
                    u"element_ids": ids,
                    u"split_axis": u"level",
                    u"split_value": lv,
                })
            _msg = u"SPLIT {0} -> {1} subgrupos por nivel.".format(base[:60], len(refined_list))
            split_digest.append(_msg)
            log_lines.append(_msg)
        elif should and len(types) > 1 and len(levels) <= 1:
            for tn, ids in sorted(types.items(), key=lambda x: -len(x[1])):
                if len(ids) < 1:
                    continue
                rk = u"{0}||ref|typ:{1}".format(base, _slug(tn))
                refined_list.append({
                    u"refined_group_key": rk,
                    u"group_origin": u"split",
                    u"element_ids": ids,
                    u"split_axis": u"type_name",
                    u"split_value": tn,
                })
            if len(refined_list) > 1:
                _msg = u"SPLIT {0} -> {1} subgrupos por tipo.".format(base[:60], len(refined_list))
                split_digest.append(_msg)
                log_lines.append(_msg)
            else:
                refined_list = []
        elif (
            should
            and len(worksets) > 1
            and len(levels) <= 1
            and len(types) <= 1
        ):
            for wn, ids in sorted(worksets.items(), key=lambda x: x[0].lower()):
                rk = u"{0}||ref|ws:{1}".format(base, _slug(wn))
                refined_list.append({
                    u"refined_group_key": rk,
                    u"group_origin": u"split",
                    u"element_ids": ids,
                    u"split_axis": u"workset",
                    u"split_value": wn,
                })
            _msg = u"SPLIT {0} -> {1} subgrupos por workset.".format(
                base[:60], len(refined_list)
            )
            split_digest.append(_msg)
            log_lines.append(_msg)
        else:
            refined_list = []

        if not refined_list:
            rk = base
            refined_list = [{
                u"refined_group_key": rk,
                u"group_origin": u"base",
                u"element_ids": id_list,
                u"split_axis": u"",
                u"split_value": u"",
            }]
            if should and len(refined_list) == 1:
                _msg = (
                    u"REVIEW {0}: should_split pero sin evidencia (un nivel/tipo) -> 1 refined.".format(
                        base[:60]
                    )
                )
                split_digest.append(_msg)
                log_lines.append(_msg)

        for part in refined_list:
            rk = part[u"refined_group_key"]
            n1 = eg.get(u"_normalized_top1", 0)
            n2 = eg.get(u"_normalized_top2", 0)
            gap = n1 - n2

            if n1 >= AUTO_TOP1_MIN and gap >= AUTO_GAP_MIN:
                cls_hint = u"AUTO"
                st_hint = u"AUTO"
            elif n1 >= REVIEW_TOP1_MIN:
                cls_hint = u"REVIEW"
                st_hint = u"REVIEW"
            else:
                cls_hint = u"REVIEW"
                st_hint = u"REVIEW"

            if part.get(u"group_origin") == u"split" and st_hint == u"AUTO":
                st_hint = u"SPLIT_AUTO"

            src_hint = u"BLOCKS+LLM" if eg.get(u"candidate_btz") else u"LLM_ONLY"

            needs_rev = st_hint == u"REVIEW" or eg.get(u"ambiguity_score", 0) > 0.65

            entry = dict(eg)
            entry[u"refined_group_key"] = rk
            entry[u"group_origin"] = part[u"group_origin"]
            entry[u"element_ids"] = part[u"element_ids"]
            entry[u"element_count"] = len(part[u"element_ids"])
            entry[u"split_axis"] = part.get(u"split_axis") or u""
            entry[u"split_value"] = part.get(u"split_value") or u""
            entry[u"classification_hint"] = cls_hint
            entry[u"needs_review"] = needs_rev
            entry[u"group_summary"] = u"{0} | {1} elems | orig={2} | amb={3}".format(
                rk[:100],
                len(part[u"element_ids"]),
                part[u"group_origin"],
                eg.get(u"ambiguity_score"),
            )
            id_set = set(int(x) for x in part[u"element_ids"])
            subrows = [r for r in erows if int(r[u"element_id"]) in id_set]
            entry[u"semantic_field_summary"] = unique_values_by_column(
                subrows, semantic_keys_for_blob()
            )

            refined_out.append(entry)
            manifest[rk] = {
                u"base_group_key": base,
                u"classification_hint": cls_hint,
                u"btz_status_hint": st_hint,
                u"btz_source_hint": src_hint,
                u"dominant_code": (eg.get(u"dominant_candidate") or {}).get(u"matched_code") if eg.get(u"dominant_candidate") else u"",
                u"group_origin": part[u"group_origin"],
                u"needs_review": needs_rev,
            }

            dc = (eg.get(u"dominant_candidate") or {}).get(u"matched_code") if eg.get(u"dominant_candidate") else u"?"
            if needs_rev:
                log_lines.append(
                    u"Refined {0} -> review (ambig={1}) top_blocks={2}".format(
                        rk[:90], eg.get(u"ambiguity_score"), dc
                    )
                )
            else:
                log_lines.append(
                    u"Refined {0} -> top_blocks {1} conf {2} status_hint={3}".format(
                        rk[:90], dc, eg.get(u"dominant_confidence"), st_hint
                    )
                )

    log_lines.append(
        u"Refinamiento: {0} grupos refinados (desde {1} base).".format(
            len(refined_out), len(enriched)
        )
    )

    status_counts = {u"AUTO": 0, u"REVIEW": 0, u"SPLIT_AUTO": 0}
    for _rk, mv in manifest.items():
        st = unicode(mv.get(u"btz_status_hint") or u"AUTO").upper()
        if st == u"SPLIT_AUTO":
            status_counts[u"SPLIT_AUTO"] += 1
        elif st == u"REVIEW":
            status_counts[u"REVIEW"] += 1
        else:
            status_counts[u"AUTO"] += 1

    diagnostics = {
        u"base_groups_count": len(enriched),
        u"refined_groups_count": len(refined_out),
        u"split_lines": split_digest,
        u"status_hint_counts": status_counts,
    }
    return refined_out, manifest, diagnostics


def save_refined_group_key_element_ids(path, refined_list, log_lines):
    m = {}
    for r in refined_list:
        rk = r[u"refined_group_key"]
        m[rk] = [int(x) for x in r[u"element_ids"]]
    with codecs.open(path, u"w", u"utf-8") as fp:
        fp.write(json.dumps(m, ensure_ascii=False, indent=2))
    log_lines.append(u"Guardado mapa refined_group_key → ids: {0}".format(path))


def save_refined_groups_manifest(path, manifest, log_lines):
    with codecs.open(path, u"w", u"utf-8") as fp:
        fp.write(json.dumps(manifest, ensure_ascii=False, indent=2))
    log_lines.append(u"Guardado manifest refinado: {0}".format(path))


def save_grouping_pipeline_log(path, header_lines, log_lines):
    """Append diagnóstico de agrupación (enriquecimiento + split)."""
    block = []
    if header_lines:
        block.extend(header_lines)
    block.extend(log_lines)
    with codecs.open(path, u"a", u"utf-8") as fp:
        fp.write(u"\n" + u"=" * 72 + u"\n")
        fp.write(u"\n".join(block) + u"\n")
    log_lines.append(u"Log pipeline: {0}".format(path))


def _strip_internal_keys(d):
    return {k: v for k, v in d.items() if not k.startswith(u"_")}


def build_enriched_revit_groups_for_payload(refined_list):
    """Lista para JSON: estructura pedida + compatibilidad."""
    out = []
    for r in refined_list:
        r = _strip_internal_keys(r)
        out.append({
            u"base_group_key": r[u"base_group_key"],
            u"refined_group_key": r[u"refined_group_key"],
            u"group_origin": r.get(u"group_origin") or u"base",
            u"element_ids": [int(x) for x in r[u"element_ids"]],
            u"element_count": int(r[u"element_count"]),
            u"group_summary": r.get(u"group_summary") or u"",
            u"candidate_columns": r.get(u"candidate_columns") or [],
            u"candidate_btz": r.get(u"candidate_btz") or [],
            u"dominant_candidate": r.get(u"dominant_candidate"),
            u"dominant_confidence": r.get(u"dominant_confidence"),
            u"ambiguity_score": r.get(u"ambiguity_score"),
            u"needs_review": bool(r.get(u"needs_review")),
            u"should_split": bool(r.get(u"should_split")),
            u"split_reason": r.get(u"split_reason") or u"",
            u"classification_hint": r.get(u"classification_hint") or u"",
            u"blocks_supporting_rows": r.get(u"blocks_supporting_rows") or [],
            u"existing_btz_values_detected": r.get(u"existing_btz_values_detected") or [],
            u"macro_group": r.get(u"macro_group"),
            u"category_name": r.get(u"category_name"),
            u"family_name": r.get(u"family_name"),
            u"type_name": r.get(u"type_name"),
            u"split_axis": r.get(u"split_axis") or u"",
            u"split_value": r.get(u"split_value") or u"",
            u"semantic_field_summary": r.get(u"semantic_field_summary") or {},
        })
    return out
