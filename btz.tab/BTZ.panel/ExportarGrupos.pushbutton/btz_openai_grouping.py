# -*- coding: utf-8 -*-
"""
Etapa de agrupacion inteligente con OpenAI para grupos Revit.

Flujo:
- build_grouping_scenarios(...)
- analyze_grouping_with_openai(...)
- build_refined_groups_from_ai(...)
"""
from __future__ import print_function

import csv
import codecs
import json
import os
import re

try:
    unicode
except NameError:
    unicode = str


OPENAI_GROUPING_RESPONSE_SCHEMA = {
    "name": "revit_grouping_decision",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "base_group_key",
            "should_split",
            "group_count",
            "groups",
            "unassigned_element_ids",
            "confidence",
            "summary",
        ],
        "properties": {
            "base_group_key": {"type": "string"},
            "should_split": {"type": "boolean"},
            "group_count": {"type": "integer", "minimum": 1},
            "groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "refined_group_key",
                        "label",
                        "reason",
                        "element_ids",
                    ],
                    "properties": {
                        "refined_group_key": {"type": "string"},
                        "label": {"type": "string"},
                        "reason": {"type": "string"},
                        "element_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            "unassigned_element_ids": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "summary": {"type": "string"},
        },
    },
}


def _norm_text(value):
    return unicode(value or u"").strip()


def _clip_text(value, max_chars):
    txt = _norm_text(value)
    try:
        lim = int(max_chars or 0)
    except Exception:
        lim = 0
    if lim <= 0:
        return txt
    if len(txt) <= lim:
        return txt
    return txt[: max(1, lim - 1)] + u"…"


def _tokens(value):
    text = _norm_text(value).lower()
    return set(re.findall(u"[a-z0-9áéíóúñ]{3,}", text, flags=re.UNICODE))


def _slug(value):
    value = _norm_text(value)
    chars = []
    for ch in value:
        if ch.isalnum() or ch in (u"-", u"_"):
            chars.append(ch.lower())
        else:
            chars.append(u"_")
    out = re.sub(u"_+", u"_", u"".join(chars)).strip(u"_")
    return out or u"group"


def _to_int(value):
    try:
        return int(value)
    except Exception:
        return None


def _parse_active_tags(raw):
    text = _norm_text(raw)
    if not text:
        return []
    out = []
    for token in text.split(u"|"):
        t = _norm_text(token)
        if t:
            out.append(t)
    return out


def _group_elements_map(revit_elements):
    grouped = {}
    for row in revit_elements:
        gk = _norm_text(row.get(u"group_key"))
        if not gk:
            continue
        grouped.setdefault(gk, []).append(row)
    return grouped


def load_normalized_blocks_csv(csv_path, log_lines=None):
    """
    Carga public/blocks_normalized.csv preservando semantica util para IA.
    """
    if not csv_path or not os.path.isfile(csv_path):
        raise IOError(u"No se encontro blocks_normalized.csv: {0}".format(csv_path))

    encodings = [u"utf-8-sig", u"utf-8", u"cp1252", u"latin1"]
    last_error = None
    for enc in encodings:
        try:
            with codecs.open(csv_path, u"r", enc) as fp:
                sample = fp.read(4096)
                fp.seek(0)
                delimiter = u","
                try:
                    delimiter = csv.Sniffer().sniff(sample, delimiters=u";,").delimiter
                except Exception:
                    if sample.count(u";") > sample.count(u","):
                        delimiter = u";"
                reader = csv.DictReader(fp, delimiter=delimiter)
                fields = [unicode(f).strip() for f in (reader.fieldnames or [])]
                if not fields:
                    raise ValueError(u"CSV sin cabecera")

                required = [u"code", u"description", u"description_name", u"active_tags"]
                missing = [f for f in required if f not in fields]
                if missing:
                    raise ValueError(
                        u"Faltan columnas requeridas en blocks_normalized.csv: {0}".format(
                            u", ".join(missing)
                        )
                    )

                out = []
                for row in reader:
                    code = _norm_text(row.get(u"code"))
                    description = _norm_text(row.get(u"description"))
                    if not code and not description:
                        continue
                    active_tags = _parse_active_tags(row.get(u"active_tags"))
                    out.append(
                        {
                            u"code": code,
                            u"description": description,
                            u"description_prefix": _norm_text(
                                row.get(u"description_prefix")
                            ),
                            u"description_name": _norm_text(row.get(u"description_name")),
                            u"active_tags": active_tags,
                            u"active_tags_count": len(active_tags),
                        }
                    )
                if not out:
                    raise ValueError(u"CSV sin filas utiles")
                if log_lines is not None:
                    log_lines.append(
                        u"blocks_normalized.csv: {0} filas utiles (encoding={1}).".format(
                            len(out), enc
                        )
                    )
                return out
        except Exception as ex:
            last_error = ex
            continue

    raise ValueError(
        u"No se pudo leer blocks_normalized.csv. Error: {0}".format(last_error)
    )


def _score_block_candidate(block, summary_text, block_tokens):
    score = 0.0
    desc = _norm_text(block.get(u"description"))
    desc_name = _norm_text(block.get(u"description_name"))
    prefix = _norm_text(block.get(u"description_prefix"))

    for t in _tokens(desc + u" " + desc_name):
        if t in block_tokens:
            score += 2.0
    for t in _tokens(prefix):
        if t in block_tokens:
            score += 1.2
    for tag in block.get(u"active_tags") or []:
        for t in _tokens(tag):
            if t in block_tokens:
                score += 1.5
    if _norm_text(block.get(u"code")).lower() in summary_text.lower().replace(u" ", u""):
        score += 0.5
    return score


def build_grouping_scenarios(
    base_groups,
    revit_elements,
    normalized_blocks,
    max_elements_per_group=200,
    max_candidate_blocks=12,
    max_comment_chars=220,
    max_group_summary_chars=360,
    log_lines=None,
):
    """
    Construye escenarios por base_group_key para enviar al modelo.
    """
    grouped = _group_elements_map(revit_elements)
    scenarios = []

    for bg in base_groups:
        base_key = _norm_text(bg.get(u"group_key"))
        rows = grouped.get(base_key, [])
        max_elems = max(1, int(max_elements_per_group or 200))
        selected_rows = rows[:max_elems]
        selected_ids = set()

        elements_payload = []
        levels = set()
        types = set()
        categories = set()
        existing_btz_keys = set()
        for r in selected_rows:
            eid = _norm_text(r.get(u"element_id"))
            if not eid:
                continue
            selected_ids.add(eid)
            lvl = _norm_text(r.get(u"level_name"))
            typ = _norm_text(r.get(u"type_name"))
            cat = _norm_text(r.get(u"category_name"))
            levels.add(lvl or u"(sin nivel)")
            types.add(typ or u"(sin tipo)")
            categories.add(cat or u"(sin categoria)")

            btz_existing = {}
            for k, v in r.items():
                ku = _norm_text(k)
                if ku.upper().startswith(u"BTZ_"):
                    vv = _norm_text(v)
                    if vv:
                        btz_existing[ku] = vv
                        existing_btz_keys.add(ku)

            elements_payload.append(
                {
                    u"element_id": eid,
                    u"level": lvl,
                    u"family_name": _norm_text(r.get(u"family_name")),
                    u"type_name": typ,
                    u"category_name": cat,
                    u"type_comments": _clip_text(
                        r.get(u"type_comments"), max_comment_chars
                    ),
                    u"comments": _clip_text(r.get(u"comments"), max_comment_chars),
                    u"mark": _norm_text(r.get(u"mark")),
                    u"existing_btz": btz_existing,
                }
            )

        summary_text = u" ".join(
            [
                _norm_text(bg.get(u"macro_group")),
                _norm_text(bg.get(u"category_name")),
                _norm_text(bg.get(u"family_name")),
                _norm_text(bg.get(u"type_name")),
                u" ".join([_norm_text(x.get(u"comments")) for x in elements_payload[:30]]),
                u" ".join(
                    [_norm_text(x.get(u"type_comments")) for x in elements_payload[:30]]
                ),
            ]
        ).strip()
        summary_tokens = _tokens(summary_text)

        scored = []
        for block in normalized_blocks:
            sc = _score_block_candidate(block, summary_text, summary_tokens)
            if sc > 0:
                scored.append((block, sc))
        scored.sort(key=lambda x: -x[1])

        candidate_blocks = []
        candidate_prefixes = []
        candidate_tags = []
        seen_prefixes = set()
        seen_tags = set()
        max_blocks = max(1, int(max_candidate_blocks or 12))
        for block, score in scored[:max_blocks]:
            candidate_blocks.append(
                {
                    u"code": _norm_text(block.get(u"code")),
                    u"description_name": _norm_text(block.get(u"description_name")),
                    u"description_prefix": _norm_text(
                        block.get(u"description_prefix")
                    ),
                    u"active_tags": list(block.get(u"active_tags") or []),
                    u"score_hint": round(float(score), 4),
                }
            )
            prefix = _norm_text(block.get(u"description_prefix"))
            if prefix and prefix not in seen_prefixes:
                seen_prefixes.add(prefix)
                candidate_prefixes.append(prefix)
            for tag in block.get(u"active_tags") or []:
                t = _norm_text(tag)
                if t and t not in seen_tags:
                    seen_tags.add(t)
                    candidate_tags.append(t)

        ambiguity_hints = []
        if len(levels) > 1:
            ambiguity_hints.append(
                u"multiples niveles detectados ({0})".format(len(levels))
            )
        if len(types) > 1:
            ambiguity_hints.append(
                u"multiples tipos detectados ({0})".format(len(types))
            )
        if len(categories) > 1:
            ambiguity_hints.append(
                u"multiples categorias detectadas ({0})".format(len(categories))
            )
        if not candidate_blocks:
            ambiguity_hints.append(
                u"sin bloques candidatos evidentes desde blocks_normalized.csv"
            )
        if len(rows) > max_elems:
            ambiguity_hints.append(
                u"grupo truncado para IA: {0}/{1} elementos".format(max_elems, len(rows))
            )

        scenario = {
            u"base_group_key": base_key,
            u"macro_group": _norm_text(bg.get(u"macro_group")),
            u"category_name": _norm_text(bg.get(u"category_name")),
            u"family_name": _norm_text(bg.get(u"family_name")),
            u"type_name": _norm_text(bg.get(u"type_name")),
            u"element_count": int(bg.get(u"count") or len(rows)),
            u"elements": elements_payload,
            u"candidate_blocks": candidate_blocks,
            u"candidate_prefixes": candidate_prefixes,
            u"candidate_tags": candidate_tags,
            u"ambiguity_hints": ambiguity_hints,
            u"group_summary": _clip_text(
                u"{0} | {1} elems | niveles={2} | tipos={3} | btz_existentes={4}".format(
                    base_key[:110], len(rows), len(levels), len(types), len(existing_btz_keys)
                ),
                max_group_summary_chars,
            ),
        }
        scenarios.append(scenario)

    if log_lines is not None:
        log_lines.append(
            u"Escenarios IA construidos: {0} grupos base.".format(len(scenarios))
        )
    return scenarios


def _base_no_split_result(base_group_key, element_ids, reason):
    return {
        u"base_group_key": _norm_text(base_group_key),
        u"should_split": False,
        u"group_count": 1,
        u"groups": [
            {
                u"refined_group_key": u"",
                u"label": u"base",
                u"reason": _norm_text(reason),
                u"element_ids": sorted([_norm_text(x) for x in element_ids]),
            }
        ],
        u"unassigned_element_ids": [],
        u"confidence": 0.0,
        u"summary": _norm_text(reason),
    }


def _extract_output_text_from_response(response):
    txt = _norm_text(getattr(response, "output_text", u""))
    if txt:
        return txt
    output = getattr(response, "output", None)
    if not output:
        return u""
    texts = []
    for item in output:
        content = getattr(item, "content", None) or []
        for c in content:
            ctext = _norm_text(getattr(c, "text", u""))
            if ctext:
                texts.append(ctext)
    return u"\n".join(texts).strip()


def _normalize_ai_result_structure(raw_result, base_group_key):
    if not isinstance(raw_result, dict):
        return None
    out = {
        u"base_group_key": _norm_text(
            raw_result.get(u"base_group_key") or base_group_key
        ),
        u"should_split": bool(raw_result.get(u"should_split")),
        u"group_count": int(raw_result.get(u"group_count") or 0),
        u"groups": [],
        u"unassigned_element_ids": [],
        u"confidence": 0.0,
        u"summary": _norm_text(raw_result.get(u"summary")),
    }
    try:
        out[u"confidence"] = float(raw_result.get(u"confidence") or 0.0)
    except Exception:
        out[u"confidence"] = 0.0
    if out[u"confidence"] < 0.0:
        out[u"confidence"] = 0.0
    if out[u"confidence"] > 1.0:
        out[u"confidence"] = 1.0

    for gid in raw_result.get(u"unassigned_element_ids") or []:
        s = _norm_text(gid)
        if s:
            out[u"unassigned_element_ids"].append(s)

    for g in raw_result.get(u"groups") or []:
        if not isinstance(g, dict):
            continue
        el_ids = []
        for eid in g.get(u"element_ids") or []:
            e = _norm_text(eid)
            if e:
                el_ids.append(e)
        out[u"groups"].append(
            {
                u"refined_group_key": _norm_text(g.get(u"refined_group_key")),
                u"label": _norm_text(g.get(u"label")),
                u"reason": _norm_text(g.get(u"reason")),
                u"element_ids": el_ids,
            }
        )
    if out[u"group_count"] <= 0:
        out[u"group_count"] = len(out[u"groups"]) if out[u"groups"] else 1
    return out


def _validate_ai_result_ids(ai_result, group_scenario):
    """
    Reglas duras:
    - no ids inexistentes
    - no ids duplicados
    - no ids faltantes sin justificar en unassigned_element_ids
    - no respuesta vacia
    """
    if not ai_result:
        return False, u"respuesta vacia"

    scenario_ids = set()
    for e in group_scenario.get(u"elements") or []:
        eid = _norm_text(e.get(u"element_id"))
        if eid:
            scenario_ids.add(eid)
    if not scenario_ids:
        return False, u"escenario sin element_ids"

    groups = ai_result.get(u"groups") or []
    if not groups:
        return False, u"respuesta sin groups"

    assigned = []
    for g in groups:
        for eid in g.get(u"element_ids") or []:
            assigned.append(_norm_text(eid))
    assigned = [x for x in assigned if x]
    if not assigned:
        return False, u"groups sin element_ids"

    seen = set()
    duplicated = []
    for eid in assigned:
        if eid in seen:
            duplicated.append(eid)
        seen.add(eid)
    if duplicated:
        return False, u"ids duplicados detectados"

    invalid = [eid for eid in assigned if eid not in scenario_ids]
    if invalid:
        return False, u"ids inexistentes detectados"

    unassigned = set(
        _norm_text(x) for x in (ai_result.get(u"unassigned_element_ids") or []) if _norm_text(x)
    )
    invalid_unassigned = [eid for eid in unassigned if eid not in scenario_ids]
    if invalid_unassigned:
        return False, u"unassigned_element_ids contiene ids inexistentes"

    missing = scenario_ids - set(assigned)
    if missing and not missing.issubset(unassigned):
        return False, u"ids faltantes sin justificar en unassigned_element_ids"

    return True, u"ok"


def analyze_grouping_with_openai(
    group_scenario,
    client=None,
    model=u"gpt-5.4",
    timeout_sec=60,
    log_lines=None,
):
    """
    Llama Responses API y devuelve JSON validado.
    Ante error/estructura invalida -> fallback conservador (no split).
    """
    base_key = _norm_text(group_scenario.get(u"base_group_key"))
    project_context = group_scenario.get(u"project_context") or {}
    project_prompt = _norm_text(project_context.get(u"project_prompt"))
    scenario_ids = [
        _norm_text(e.get(u"element_id")) for e in (group_scenario.get(u"elements") or [])
    ]
    scenario_ids = [x for x in scenario_ids if x]

    if not scenario_ids:
        return _base_no_split_result(base_key, [], u"fallback: escenario sin elementos")

    if client is None:
        api_key = _norm_text(os.environ.get(u"OPENAI_API_KEY"))
        if not api_key:
            if log_lines is not None:
                log_lines.append(
                    u"[IA grouping] OPENAI_API_KEY ausente en entorno; fallback no split."
                )
            return _base_no_split_result(
                base_key, scenario_ids, u"fallback: OPENAI_API_KEY ausente"
            )
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, timeout=float(timeout_sec or 60))
        except Exception as ex:
            if log_lines is not None:
                log_lines.append(
                    u"[IA grouping] no se pudo crear cliente OpenAI: {0}".format(ex)
                )
            return _base_no_split_result(
                base_key, scenario_ids, u"fallback: cliente OpenAI no disponible"
            )

    system_text = (
        u"Eres un analizador de agrupacion de elementos Revit para clasificacion BTZ. "
        u"Debes decidir si un grupo tecnico base debe mantenerse o subdividirse en subgrupos semanticos. "
        u"El campo 'code' en candidate_blocks es un ID. "
        u"La semantica principal esta en description_name, description_prefix y active_tags. "
        u"No inventes elementos ni ids. Solo puedes usar element_ids presentes en el escenario. "
        u"Si no hay evidencia suficiente para dividir, debes mantener el grupo unido."
    )
    if project_prompt:
        system_text += (
            u"\n\nContexto especifico del proyecto (prioritario):\n{0}".format(
                project_prompt
            )
        )
    user_text = (
        u"Analiza el siguiente escenario y devuelve JSON estricto con el schema requerido.\n"
        u"Reglas duras:\n"
        u"- No inventar element_ids.\n"
        u"- Todos los element_ids deben salir del escenario recibido.\n"
        u"- Si no hay evidencia, should_split=false y un unico grupo.\n"
        u"- Si divides, cada elemento debe pertenecer a un solo grupo.\n\n"
        u"Contexto de proyecto (detected_tokens/conflicts/penalties):\n{0}".format(
            json.dumps(project_context, ensure_ascii=False, indent=2),
        )
    )
    user_text += (
        u"\nEscenario:\n{0}".format(
            json.dumps(group_scenario, ensure_ascii=False, indent=2)
        )
    )

    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_text}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_text}],
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": OPENAI_GROUPING_RESPONSE_SCHEMA["name"],
                    "schema": OPENAI_GROUPING_RESPONSE_SCHEMA["schema"],
                    "strict": True,
                }
            },
            max_output_tokens=1600,
            timeout=float(timeout_sec or 60),
        )
    except Exception as ex:
        if log_lines is not None:
            log_lines.append(
                u"[IA grouping] error OpenAI base_group_key={0}: {1}".format(
                    base_key[:80], ex
                )
            )
        return _base_no_split_result(
            base_key, scenario_ids, u"fallback: error en llamada OpenAI"
        )

    raw_text = _extract_output_text_from_response(response)
    if not raw_text:
        if log_lines is not None:
            log_lines.append(
                u"[IA grouping] respuesta vacia base_group_key={0}".format(base_key[:80])
            )
        return _base_no_split_result(
            base_key, scenario_ids, u"fallback: respuesta vacia del modelo"
        )

    try:
        raw_result = json.loads(raw_text)
    except Exception as ex:
        if log_lines is not None:
            log_lines.append(
                u"[IA grouping] JSON invalido base_group_key={0}: {1}".format(
                    base_key[:80], ex
                )
            )
        return _base_no_split_result(
            base_key, scenario_ids, u"fallback: JSON invalido del modelo"
        )

    ai_result = _normalize_ai_result_structure(raw_result, base_key)
    ok, reason = _validate_ai_result_ids(ai_result, group_scenario)
    if not ok:
        if log_lines is not None:
            log_lines.append(
                u"[IA grouping] validacion fallida {0}: {1}. Fallback no split.".format(
                    base_key[:80], reason
                )
            )
        return _base_no_split_result(
            base_key, scenario_ids, u"fallback: {0}".format(reason)
        )

    if log_lines is not None:
        log_lines.append(
            u"[IA grouping] OK {0}: should_split={1}, groups={2}, confidence={3}".format(
                base_key[:80],
                bool(ai_result.get(u"should_split")),
                len(ai_result.get(u"groups") or []),
                ai_result.get(u"confidence"),
            )
        )
    return ai_result


def build_refined_groups_from_ai(ai_result, base_group, elements_by_id, log_lines=None):
    """
    Convierte decision IA en grupos refinados trazables para el pipeline.
    """
    base_key = _norm_text(base_group.get(u"group_key"))
    base_ids = []
    for eid, row in elements_by_id.items():
        if _norm_text(row.get(u"group_key")) == base_key:
            base_ids.append(_norm_text(eid))
    base_ids = sorted(set([x for x in base_ids if x]))
    base_id_set = set(base_ids)

    if not base_ids:
        return []

    if not ai_result:
        ai_result = _base_no_split_result(base_key, base_ids, u"fallback sin ai_result")

    should_split = bool(ai_result.get(u"should_split"))
    ai_groups = ai_result.get(u"groups") or []
    confidence = float(ai_result.get(u"confidence") or 0.0)
    summary = _norm_text(ai_result.get(u"summary"))

    assigned = set()
    refined = []
    idx = 1
    for g in ai_groups:
        ids = []
        for raw in g.get(u"element_ids") or []:
            eid_s = _norm_text(raw)
            if (not eid_s) or (eid_s in assigned):
                continue
            if eid_s not in base_id_set:
                continue
            assigned.add(eid_s)
            ids.append(eid_s)
        if not ids:
            continue

        label = _norm_text(g.get(u"label")) or u"subgrupo_{0}".format(idx)
        reason = _norm_text(g.get(u"reason"))
        refined_key_hint = _norm_text(g.get(u"refined_group_key"))
        if refined_key_hint:
            refined_key = u"{0}||ai|{1}".format(base_key, _slug(refined_key_hint))
        else:
            refined_key = u"{0}||ai|{1:02d}_{2}".format(base_key, idx, _slug(label))

        origin = u"ai_split" if should_split else u"base"
        if not should_split:
            refined_key = base_key
            origin = u"base"

        refined.append(
            {
                u"base_group_key": base_key,
                u"refined_group_key": refined_key,
                u"group_origin": origin,
                u"element_ids": [int(x) for x in ids],
                u"element_count": len(ids),
                u"macro_group": _norm_text(base_group.get(u"macro_group")),
                u"category_name": _norm_text(base_group.get(u"category_name")),
                u"family_name": _norm_text(base_group.get(u"family_name")),
                u"type_name": _norm_text(base_group.get(u"type_name")),
                u"group_summary": summary or _norm_text(base_group.get(u"group_key")),
                u"split_reason": reason,
                u"should_split": should_split,
                u"needs_review": confidence < 0.55,
                u"classification_hint": u"REVIEW" if confidence < 0.55 else u"AUTO",
                u"candidate_columns": [],
                u"candidate_btz": [],
                u"dominant_candidate": None,
                u"dominant_confidence": confidence,
                u"ambiguity_score": round(1.0 - confidence, 4),
                u"blocks_supporting_rows": [],
                u"existing_btz_values_detected": [],
                u"split_axis": u"ai_semantic",
                u"split_value": label,
                u"semantic_field_summary": {},
            }
        )
        idx += 1
        if not should_split:
            break

    missing = base_id_set - set(unicode(x) for r in refined for x in r[u"element_ids"])
    if missing:
        if log_lines is not None:
            log_lines.append(
                u"[IA grouping] {0}: {1} ids faltantes se mantienen en grupo base.".format(
                    base_key[:80], len(missing)
                )
            )
        refined.append(
            {
                u"base_group_key": base_key,
                u"refined_group_key": base_key,
                u"group_origin": u"base",
                u"element_ids": [int(x) for x in sorted(missing)],
                u"element_count": len(missing),
                u"macro_group": _norm_text(base_group.get(u"macro_group")),
                u"category_name": _norm_text(base_group.get(u"category_name")),
                u"family_name": _norm_text(base_group.get(u"family_name")),
                u"type_name": _norm_text(base_group.get(u"type_name")),
                u"group_summary": u"Fallback base para elementos no asignados por IA.",
                u"split_reason": u"elementos no asignados",
                u"should_split": False,
                u"needs_review": True,
                u"classification_hint": u"REVIEW",
                u"candidate_columns": [],
                u"candidate_btz": [],
                u"dominant_candidate": None,
                u"dominant_confidence": 0.0,
                u"ambiguity_score": 1.0,
                u"blocks_supporting_rows": [],
                u"existing_btz_values_detected": [],
                u"split_axis": u"",
                u"split_value": u"",
                u"semantic_field_summary": {},
            }
        )

    # Si no hubo refined valido, fallback final al grupo base.
    if not refined:
        refined.append(
            {
                u"base_group_key": base_key,
                u"refined_group_key": base_key,
                u"group_origin": u"base",
                u"element_ids": [int(x) for x in base_ids],
                u"element_count": len(base_ids),
                u"macro_group": _norm_text(base_group.get(u"macro_group")),
                u"category_name": _norm_text(base_group.get(u"category_name")),
                u"family_name": _norm_text(base_group.get(u"family_name")),
                u"type_name": _norm_text(base_group.get(u"type_name")),
                u"group_summary": u"Fallback conservador: sin split",
                u"split_reason": u"sin grupos IA validos",
                u"should_split": False,
                u"needs_review": True,
                u"classification_hint": u"REVIEW",
                u"candidate_columns": [],
                u"candidate_btz": [],
                u"dominant_candidate": None,
                u"dominant_confidence": 0.0,
                u"ambiguity_score": 1.0,
                u"blocks_supporting_rows": [],
                u"existing_btz_values_detected": [],
                u"split_axis": u"",
                u"split_value": u"",
                u"semantic_field_summary": {},
            }
        )

    return refined
