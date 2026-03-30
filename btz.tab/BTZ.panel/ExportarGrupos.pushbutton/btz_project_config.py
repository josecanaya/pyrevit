# -*- coding: utf-8 -*-
"""
Configuracion semantica de proyecto (editable rapido en public/project_config).

Objetivo:
- Centralizar logica del proyecto en JSON + prompts.
- Aplicar reglas blandas (penalizacion de confianza) antes de IA.
"""
from __future__ import print_function

import os
import json
import codecs
import csv
import re
import datetime

from btz_apply_webhook import PUBLIC_DIR

try:
    unicode
except NameError:
    unicode = str


PROJECT_CONFIG_DIR = os.path.join(PUBLIC_DIR, "project_config")
PROJECT_CONFIG_JSON = os.path.join(PROJECT_CONFIG_DIR, "project_config.json")
PROJECT_PROMPT_MD = os.path.join(PROJECT_CONFIG_DIR, "prompt_project.md")
TRANSFORM_PROMPT_MD = os.path.join(PROJECT_CONFIG_DIR, "prompt_transform_blocks.md")
BLOCKS_SEMANTIC_JSON = os.path.join(PROJECT_CONFIG_DIR, "blocks_semantic.json")
AUDIT_JSON = os.path.join(PROJECT_CONFIG_DIR, "project_config.audit.json")


def _u(x):
    return unicode(x or u"").strip()


def _now_utc_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _as_text(value):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    try:
        return unicode(value)
    except Exception:
        return u""


def _read_text_file(path):
    encodings = [u"utf-8-sig", u"utf-8", u"cp1252", u"latin1"]
    last = None
    for enc in encodings:
        try:
            with codecs.open(path, "r", enc) as fp:
                return _as_text(fp.read())
        except Exception as ex:
            last = ex
            continue
    raise ValueError(u"No se pudo leer archivo de texto: {0}".format(last))


def _default_project_config():
    return {
        u"version": u"1.0",
        u"project_name": u"",
        u"rule_mode": u"soft",
        u"updated_at_utc": _now_utc_iso(),
        u"paths": {
            u"blocks_source_csv": os.path.join(PUBLIC_DIR, "blocks_normalized.csv"),
            u"blocks_semantic_json": BLOCKS_SEMANTIC_JSON,
            u"prompt_project_md": PROJECT_PROMPT_MD,
            u"prompt_transform_blocks_md": TRANSFORM_PROMPT_MD,
            u"audit_json": AUDIT_JSON,
        },
        u"confidence": {
            u"zone_match_bonus": 0.08,
            u"zone_mismatch_penalty": 0.25,
            u"forbidden_token_penalty": 0.35,
            u"review_threshold": 0.55,
            u"auto_apply_threshold": 0.65,
            u"confidence_floor": 0.05,
            u"confidence_ceiling": 0.99,
        },
        u"matching": {
            u"normalize_case": True,
            u"strip_accents": True,
            u"token_boundary_strict": True,
            u"min_token_length": 2,
        },
        u"soft_constraints": {
            u"prefer_same_zone": True,
            u"penalize_cross_zone": True,
            u"penalize_forbidden_tokens": True,
            u"demote_to_review_on_conflict": True,
        },
        u"semantic_tokens": {
            u"N1": {
                u"type": u"zona",
                u"meaning": u"Nave 1",
                u"aliases": [u"NAVE 1", u"N-1", u"N1"],
                u"expected_tags": [u"NAVE 1"],
                u"forbidden_with": [u"VESTUARIOS", u"PA", u"PG", u"SR1", u"ST1"],
                u"weight": 1.0,
            },
            u"VESTUARIOS": {
                u"type": u"zona",
                u"meaning": u"Area de vestuarios",
                u"aliases": [u"VESTUARIO", u"VESTUARIOS"],
                u"expected_tags": [u"VESTUARIOS"],
                u"forbidden_with": [u"N1", u"PA", u"PG", u"SR1", u"ST1"],
                u"weight": 1.0,
            },
            u"SR1": {
                u"type": u"sector",
                u"meaning": u"Sala Recepcion 1",
                u"aliases": [u"SR1", u"SALA RECEPCION 1"],
                u"expected_tags": [u"SALA RECEPCION 1"],
                u"forbidden_with": [u"ST1"],
                u"weight": 0.9,
            },
            u"ST1": {
                u"type": u"sector",
                u"meaning": u"Sala Terminacion 1",
                u"aliases": [u"ST1", u"SALA TERMINACION 1"],
                u"expected_tags": [u"SALA TERMINACION 1"],
                u"forbidden_with": [u"SR1"],
                u"weight": 0.9,
            },
            u"PA": {
                u"type": u"planta",
                u"meaning": u"Planta Agua",
                u"aliases": [u"PA", u"PLANTA AGUA"],
                u"expected_tags": [u"PLANTA AGUA"],
                u"forbidden_with": [u"N1", u"VESTUARIOS", u"PG"],
                u"weight": 0.95,
            },
            u"PG": {
                u"type": u"planta",
                u"meaning": u"Planta Gas",
                u"aliases": [u"PG", u"PLANTA GAS"],
                u"expected_tags": [u"PLANTA GAS"],
                u"forbidden_with": [u"N1", u"VESTUARIOS", u"PA"],
                u"weight": 0.95,
            },
        },
    }


DEFAULT_PROJECT_PROMPT = u"""# Prompt de proyecto BTZ

Reglas semanticas del proyecto (ajustables):
- N1 refiere a Nave 1.
- VESTUARIOS refiere al area de vestuarios.
- SR1 y ST1 son sectores distintos; no mezclar salvo evidencia fuerte.
- PA y PG son plantas distintas.

Instruccion al modelo:
- Prioriza coherencia de zona/sector por encima de similitud textual superficial.
- Si hay conflicto entre tokens de zona, baja confianza o evita split agresivo.
"""


DEFAULT_TRANSFORM_PROMPT = u"""# Prompt para transformar CSV -> blocks_semantic.json

Objetivo:
- Tomar blocks_normalized.csv y generar una version semantica enriquecida.

Campos sugeridos por fila:
- code
- description
- description_prefix
- description_name
- active_tags
- inferred_tokens (N1, VESTUARIOS, SR1, ST1, PA, PG, etc.)
- project_zone_hint
- project_sector_hint
- forbidden_tokens_suggested
"""


def ensure_project_config_files(log_lines=None):
    if not os.path.isdir(PROJECT_CONFIG_DIR):
        os.makedirs(PROJECT_CONFIG_DIR)
        if log_lines is not None:
            log_lines.append(u"[PROJECT-CONFIG] creada carpeta: {0}".format(PROJECT_CONFIG_DIR))

    if not os.path.isfile(PROJECT_CONFIG_JSON):
        with codecs.open(PROJECT_CONFIG_JSON, "w", "utf-8") as fp:
            fp.write(json.dumps(_default_project_config(), ensure_ascii=False, indent=2))
        if log_lines is not None:
            log_lines.append(u"[PROJECT-CONFIG] creado: project_config.json")

    if not os.path.isfile(PROJECT_PROMPT_MD):
        with codecs.open(PROJECT_PROMPT_MD, "w", "utf-8") as fp:
            fp.write(DEFAULT_PROJECT_PROMPT)
        if log_lines is not None:
            log_lines.append(u"[PROJECT-CONFIG] creado: prompt_project.md")

    if not os.path.isfile(TRANSFORM_PROMPT_MD):
        with codecs.open(TRANSFORM_PROMPT_MD, "w", "utf-8") as fp:
            fp.write(DEFAULT_TRANSFORM_PROMPT)
        if log_lines is not None:
            log_lines.append(u"[PROJECT-CONFIG] creado: prompt_transform_blocks.md")

    if not os.path.isfile(BLOCKS_SEMANTIC_JSON):
        with codecs.open(BLOCKS_SEMANTIC_JSON, "w", "utf-8") as fp:
            fp.write(json.dumps({u"items": []}, ensure_ascii=False, indent=2))
        if log_lines is not None:
            log_lines.append(u"[PROJECT-CONFIG] creado: blocks_semantic.json")

    if not os.path.isfile(AUDIT_JSON):
        with codecs.open(AUDIT_JSON, "w", "utf-8") as fp:
            fp.write(json.dumps({u"events": []}, ensure_ascii=False, indent=2))
        if log_lines is not None:
            log_lines.append(u"[PROJECT-CONFIG] creado: project_config.audit.json")


def save_project_prompt_text(prompt_text):
    ensure_project_config_files()
    with codecs.open(PROJECT_PROMPT_MD, "w", "utf-8") as fp:
        # Guardar literal el texto recibido (sin strip ni normalizacion).
        fp.write(_as_text(prompt_text))


def _load_json(path, default_obj):
    if not os.path.isfile(path):
        return default_obj
    try:
        with codecs.open(path, "r", "utf-8-sig") as fp:
            data = json.loads(fp.read())
        return data if isinstance(data, dict) else default_obj
    except Exception:
        return default_obj


def append_project_audit(event_name, detail_dict=None):
    ensure_project_config_files()
    data = _load_json(AUDIT_JSON, {u"events": []})
    events = data.get(u"events") or []
    events.append(
        {
            u"timestamp_utc": _now_utc_iso(),
            u"event": _u(event_name),
            u"detail": detail_dict or {},
        }
    )
    data[u"events"] = events[-500:]
    with codecs.open(AUDIT_JSON, "w", "utf-8") as fp:
        fp.write(json.dumps(data, ensure_ascii=False, indent=2))


def load_project_prompt():
    if not os.path.isfile(PROJECT_PROMPT_MD):
        return u""
    try:
        with codecs.open(PROJECT_PROMPT_MD, "r", "utf-8-sig") as fp:
            return _u(fp.read())
    except Exception:
        return u""


def load_project_config(log_lines=None):
    ensure_project_config_files(log_lines)
    cfg = _default_project_config()
    try:
        with codecs.open(PROJECT_CONFIG_JSON, "r", "utf-8-sig") as fp:
            user_cfg = json.loads(fp.read())
        if isinstance(user_cfg, dict):
            cfg.update(user_cfg)
            # merge shallow para sub-dicts frecuentes
            for key in [u"paths", u"confidence", u"matching", u"soft_constraints"]:
                if isinstance(cfg.get(key), dict) and isinstance(user_cfg.get(key), dict):
                    tmp = dict(cfg.get(key))
                    tmp.update(user_cfg.get(key))
                    cfg[key] = tmp
    except Exception as ex:
        if log_lines is not None:
            log_lines.append(u"[PROJECT-CONFIG] no se pudo cargar JSON, usando default: {0}".format(ex))
    cfg[u"prompt_project_text"] = load_project_prompt()
    return cfg


def save_project_config(cfg):
    ensure_project_config_files()
    cfg = cfg or _default_project_config()
    cfg[u"updated_at_utc"] = _now_utc_iso()
    with codecs.open(PROJECT_CONFIG_JSON, "w", "utf-8") as fp:
        fp.write(json.dumps(cfg, ensure_ascii=False, indent=2))


def validate_project_config(cfg):
    issues = []
    if not isinstance(cfg, dict):
        return [u"config no es objeto JSON"]
    if _u(cfg.get(u"rule_mode")) not in (u"soft", u"hybrid", u"hard"):
        issues.append(u"rule_mode debe ser soft|hybrid|hard")
    sem = cfg.get(u"semantic_tokens")
    if not isinstance(sem, dict) or not sem:
        issues.append(u"semantic_tokens vacio o invalido")
    conf = cfg.get(u"confidence") or {}
    if not isinstance(conf, dict):
        issues.append(u"confidence debe ser objeto")
    else:
        for k in [u"zone_mismatch_penalty", u"forbidden_token_penalty", u"review_threshold"]:
            if k not in conf:
                issues.append(u"falta confidence.{0}".format(k))
    return issues


def _tokenize(text):
    return set(re.findall(u"[A-Za-z0-9_\\-]{2,}", _u(text).upper()))


def _extract_rules_from_prompt(prompt_text):
    """
    Heuristica liviana para texto natural en espanol.
    Soporta patrones como:
    - "N1 refiere a Nave 1"
    - "VESTUARIOS no puede estar con N1"
    """
    txt = _u(prompt_text)
    if not txt:
        return {}
    sem = {}
    relation_lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    for ln in relation_lines:
        lnu = ln.upper()

        m_mean = re.search(
            u"\\b([A-Z][A-Z0-9_\\-]{1,15})\\b\\s+(?:REFIERE A|HACE REFERENCIA A|SIGNIFICA|=|:)\\s+(.+)$",
            lnu,
        )
        if m_mean:
            token = _u(m_mean.group(1)).upper()
            meaning = _u(m_mean.group(2))
            sem.setdefault(token, {})
            sem[token][u"meaning"] = meaning
            sem[token].setdefault(u"aliases", [token])
            sem[token].setdefault(u"forbidden_with", [])

        m_forb = re.search(
            u"\\b([A-Z][A-Z0-9_\\-]{1,15})\\b\\s+(?:NO PUEDE ESTAR CON|NO MEZCLAR CON|INCOMPATIBLE CON)\\s+\\b([A-Z][A-Z0-9_\\-]{1,15})\\b",
            lnu,
        )
        if m_forb:
            a = _u(m_forb.group(1)).upper()
            b = _u(m_forb.group(2)).upper()
            sem.setdefault(a, {})
            sem[a].setdefault(u"aliases", [a])
            sem[a].setdefault(u"forbidden_with", [])
            if b not in sem[a][u"forbidden_with"]:
                sem[a][u"forbidden_with"].append(b)
            sem.setdefault(b, {})
            sem[b].setdefault(u"aliases", [b])
            sem[b].setdefault(u"forbidden_with", [])
            if a not in sem[b][u"forbidden_with"]:
                sem[b][u"forbidden_with"].append(a)
    return sem


def apply_prompt_to_project_config(
    prompt_text,
    project_name=u"",
    imported_file_path=u"",
    log_lines=None,
):
    """
    Toma texto (pegado o desde archivo), guarda prompt y ajusta semantic_tokens.
    """
    ensure_project_config_files(log_lines)
    cfg = load_project_config(log_lines)
    merged_prompt = _as_text(prompt_text)
    if imported_file_path:
        file_txt = _read_text_file(imported_file_path)
        if merged_prompt and (not merged_prompt.endswith(u"\n")):
            merged_prompt += u"\n"
        merged_prompt += file_txt
    # Siempre persistir prompt_project.md con el contenido combinado literal.
    save_project_prompt_text(merged_prompt)
    cfg[u"prompt_project_text"] = merged_prompt
    if _u(project_name):
        cfg[u"project_name"] = _u(project_name)

    semantic_tokens = cfg.get(u"semantic_tokens") or {}
    extracted = _extract_rules_from_prompt(merged_prompt)
    created = 0
    updated = 0
    for tk, raw in extracted.items():
        if tk not in semantic_tokens:
            semantic_tokens[tk] = {
                u"type": u"otro",
                u"meaning": _u(raw.get(u"meaning")) or tk,
                u"aliases": [tk],
                u"expected_tags": [tk],
                u"forbidden_with": [],
                u"weight": 0.9,
            }
            created += 1
        else:
            if _u(raw.get(u"meaning")):
                semantic_tokens[tk][u"meaning"] = _u(raw.get(u"meaning"))
            updated += 1
        forb = semantic_tokens[tk].get(u"forbidden_with") or []
        for f in (raw.get(u"forbidden_with") or []):
            fu = _u(f).upper()
            if fu and fu not in forb:
                forb.append(fu)
        semantic_tokens[tk][u"forbidden_with"] = sorted(list(set(forb)))
        aliases = semantic_tokens[tk].get(u"aliases") or []
        if tk not in aliases:
            aliases.append(tk)
        semantic_tokens[tk][u"aliases"] = sorted(list(set([_u(x).upper() for x in aliases if _u(x)])))

    cfg[u"semantic_tokens"] = semantic_tokens
    save_project_config(cfg)
    append_project_audit(
        u"apply_prompt_to_project_config",
        {
            u"project_name": _u(cfg.get(u"project_name")),
            u"imported_file_path": _u(imported_file_path),
            u"extracted_tokens": sorted(list(extracted.keys())),
            u"created_tokens": created,
            u"updated_tokens": updated,
        },
    )
    if log_lines is not None:
        log_lines.append(
            u"[PROJECT-CONFIG] prompt aplicado. tokens_extraidos={0} creados={1} actualizados={2}".format(
                len(extracted), created, updated
            )
        )
    return {
        u"tokens_extracted_count": len(extracted),
        u"tokens_created_count": created,
        u"tokens_updated_count": updated,
        u"project_name": _u(cfg.get(u"project_name")),
    }


def _extract_detected_tokens(full_text, semantic_tokens):
    found = set()
    tokens = _tokenize(full_text)
    for key, rule in (semantic_tokens or {}).items():
        k = _u(key).upper()
        aliases = [k] + [_u(x).upper() for x in (rule.get(u"aliases") or [])]
        for a in aliases:
            if a and a in tokens:
                found.add(k)
                break
    return sorted(found)


def _flatten_conflict_tokens(conflict_pairs):
    out = set()
    for a, b in (conflict_pairs or []):
        au = _u(a).upper()
        bu = _u(b).upper()
        if au:
            out.add(au)
        if bu:
            out.add(bu)
    return sorted(list(out))


def build_project_context_for_scenario(scenario, cfg):
    sem = cfg.get(u"semantic_tokens") or {}
    conf = cfg.get(u"confidence") or {}
    group_text_parts = [
        _u(scenario.get(u"base_group_key")),
        _u(scenario.get(u"group_summary")),
    ]
    for c in (scenario.get(u"candidate_blocks") or []):
        group_text_parts.append(_u(c.get(u"description_prefix")))
        group_text_parts.append(_u(c.get(u"description_name")))
        for t in (c.get(u"active_tags") or []):
            group_text_parts.append(_u(t))
    full_text = u" ".join(group_text_parts)
    detected = _extract_detected_tokens(full_text, sem)

    penalty = 0.0
    conflict_pairs = []
    for tk in detected:
        rule = sem.get(tk) or {}
        forbidden = [_u(x).upper() for x in (rule.get(u"forbidden_with") or [])]
        for fk in forbidden:
            if fk and fk in detected:
                conflict_pairs.append((tk, fk))
    if conflict_pairs:
        try:
            penalty = float(conf.get(u"forbidden_token_penalty", 0.35))
        except Exception:
            penalty = 0.35

    return {
        u"detected_tokens": detected,
        u"conflict_pairs": conflict_pairs,
        u"soft_penalty": round(max(0.0, penalty), 4),
        u"rule_mode": _u(cfg.get(u"rule_mode")) or u"soft",
        u"project_prompt": _u(cfg.get(u"prompt_project_text")),
    }


def apply_project_soft_logic_to_scenario(scenario, cfg, log_lines=None):
    """
    Inserta contexto de proyecto y penaliza score_hint de candidatos en conflicto.
    """
    if not isinstance(scenario, dict):
        return scenario
    ctx = build_project_context_for_scenario(scenario, cfg)
    scenario[u"project_context"] = ctx

    detected = set([_u(x).upper() for x in (ctx.get(u"detected_tokens") or [])])
    conflict_tokens = set()
    for a, b in (ctx.get(u"conflict_pairs") or []):
        conflict_tokens.add(_u(a).upper())
        conflict_tokens.add(_u(b).upper())

    penalty = float(ctx.get(u"soft_penalty") or 0.0)
    adjusted = 0
    for cb in (scenario.get(u"candidate_blocks") or []):
        base_score = float(cb.get(u"score_hint") or 0.0)
        txt = u" ".join(
            [
                _u(cb.get(u"description_prefix")),
                _u(cb.get(u"description_name")),
                u" ".join([_u(t) for t in (cb.get(u"active_tags") or [])]),
            ]
        ).upper()
        row_tokens = _tokenize(txt)
        has_conflict = bool(conflict_tokens.intersection(row_tokens))
        if has_conflict and penalty > 0:
            cb[u"score_hint_project"] = round(max(0.0, base_score - penalty), 4)
            cb[u"project_penalty_applied"] = round(penalty, 4)
            adjusted += 1
        else:
            cb[u"score_hint_project"] = round(base_score, 4)
            cb[u"project_penalty_applied"] = 0.0

    if log_lines is not None:
        log_lines.append(
            u"[PROJECT-CONFIG] {0}: tokens={1} conflicts={2} candidates_adjusted={3}".format(
                _u(scenario.get(u"base_group_key"))[:90],
                len(detected),
                len(ctx.get(u"conflict_pairs") or []),
                adjusted,
            )
        )
    return scenario


def build_project_rule_split_parts(
    base_key,
    base_group,
    group_rows,
    scenario,
    insight,
    project_cfg,
    log_lines=None,
):
    """
    Split deterministico por tokens de proyecto cuando hay conflicto semantico.
    Se usa para que la logica de proyecto tenga impacto real incluso si la IA no divide.
    """
    sc = scenario or {}
    ctx = sc.get(u"project_context") or {}
    sem = (project_cfg or {}).get(u"semantic_tokens") or {}
    conflict_pairs = ctx.get(u"conflict_pairs") or []
    target_tokens = _flatten_conflict_tokens(conflict_pairs)
    if len(target_tokens) < 2:
        if log_lines is not None:
            log_lines.append(
                u"[PROJECT-CONFIG] split por reglas omitido {0}: sin conflicto suficiente".format(
                    _u(base_key)[:90]
                )
            )
        return []

    # mapa token -> alias normalizados
    alias_map = {}
    for tk in target_tokens:
        rule = sem.get(tk) or {}
        aliases = [tk] + [_u(x).upper() for x in (rule.get(u"aliases") or [])]
        alias_map[tk] = sorted(list(set([a for a in aliases if a])))

    buckets = {}
    unassigned = []
    for row in (group_rows or []):
        try:
            eid = int(row.get(u"element_id"))
        except Exception:
            continue
        text = u" ".join(
            [
                _u(row.get(u"group_key")),
                _u(row.get(u"category_name")),
                _u(row.get(u"family_name")),
                _u(row.get(u"type_name")),
                _u(row.get(u"level_name")),
                _u(row.get(u"comments")),
                _u(row.get(u"type_comments")),
                _u(row.get(u"mark")),
            ]
        ).upper()
        tokens = _tokenize(text)
        matched = []
        for tk, aliases in alias_map.items():
            for al in aliases:
                if al in tokens:
                    matched.append(tk)
                    break
        matched = sorted(list(set(matched)))
        if len(matched) == 1:
            buckets.setdefault(matched[0], []).append(eid)
        else:
            unassigned.append(eid)

    non_empty = [(k, v) for k, v in buckets.items() if v]
    if len(non_empty) < 2:
        if log_lines is not None:
            log_lines.append(
                u"[PROJECT-CONFIG] split por reglas omitido {0}: buckets útiles={1}".format(
                    _u(base_key)[:90], len(non_empty)
                )
            )
        return []

    parts = []
    for tk, ids in sorted(non_empty, key=lambda kv: kv[0]):
        parts.append(
            {
                u"base_group_key": base_key,
                u"refined_group_key": u"{0}||ref|proj:{1}".format(base_key, _u(tk).lower()),
                u"group_origin": u"project_rule_split",
                u"element_ids": sorted(ids),
                u"element_count": len(ids),
                u"macro_group": base_group.get(u"macro_group") or u"",
                u"category_name": base_group.get(u"category_name") or u"",
                u"family_name": base_group.get(u"family_name") or u"",
                u"type_name": base_group.get(u"type_name") or u"",
                u"candidate_columns": insight.get(u"candidate_columns") or [],
                u"candidate_btz": insight.get(u"candidate_btz") or [],
                u"dominant_candidate": insight.get(u"dominant_candidate"),
                u"dominant_confidence": insight.get(u"dominant_confidence"),
                u"ambiguity_score": insight.get(u"ambiguity_score"),
                u"blocks_supporting_rows": insight.get(u"blocks_supporting_rows") or [],
                u"existing_btz_values_detected": insight.get(u"existing_btz_values_detected")
                or [],
                u"semantic_field_summary": {},
                u"should_split": True,
                u"split_reason": u"project_rule_split por conflicto de tokens",
                u"split_axis": u"project_token",
                u"split_value": _u(tk),
                u"classification_hint": u"REVIEW",
                u"needs_review": True,
                u"group_summary": u"project_rule_split token={0} elems={1}".format(
                    _u(tk), len(ids)
                ),
            }
        )

    if unassigned:
        parts.append(
            {
                u"base_group_key": base_key,
                u"refined_group_key": u"{0}||ref|proj:sin_token".format(base_key),
                u"group_origin": u"project_rule_split",
                u"element_ids": sorted(unassigned),
                u"element_count": len(unassigned),
                u"macro_group": base_group.get(u"macro_group") or u"",
                u"category_name": base_group.get(u"category_name") or u"",
                u"family_name": base_group.get(u"family_name") or u"",
                u"type_name": base_group.get(u"type_name") or u"",
                u"candidate_columns": insight.get(u"candidate_columns") or [],
                u"candidate_btz": insight.get(u"candidate_btz") or [],
                u"dominant_candidate": insight.get(u"dominant_candidate"),
                u"dominant_confidence": insight.get(u"dominant_confidence"),
                u"ambiguity_score": insight.get(u"ambiguity_score"),
                u"blocks_supporting_rows": insight.get(u"blocks_supporting_rows") or [],
                u"existing_btz_values_detected": insight.get(u"existing_btz_values_detected")
                or [],
                u"semantic_field_summary": {},
                u"should_split": True,
                u"split_reason": u"project_rule_split residual",
                u"split_axis": u"project_token",
                u"split_value": u"(sin_token)",
                u"classification_hint": u"REVIEW",
                u"needs_review": True,
                u"group_summary": u"project_rule_split residual elems={0}".format(
                    len(unassigned)
                ),
            }
        )

    if log_lines is not None:
        log_lines.append(
            u"[PROJECT-CONFIG] split por reglas aplicado {0}: {1} subgrupos (conflicts={2})".format(
                _u(base_key)[:90], len(parts), len(conflict_pairs)
            )
        )
    return parts


def refresh_blocks_semantic_from_csv(csv_path, log_lines=None):
    """
    Genera blocks_semantic.json base a partir de blocks_normalized.csv.
    Este paso deja estructura lista para refinamiento por prompt.
    """
    items = []
    if not csv_path or (not os.path.isfile(csv_path)):
        if log_lines is not None:
            log_lines.append(u"[PROJECT-CONFIG] CSV no encontrado para semantic: {0}".format(csv_path))
        return 0

    with codecs.open(csv_path, "r", "utf-8-sig") as fp:
        sample = fp.read(4096)
        fp.seek(0)
        delim = ","
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=";,").delimiter
        except Exception:
            if sample.count(";") > sample.count(","):
                delim = ";"
        rd = csv.DictReader(fp, delimiter=delim)
        for row in rd:
            code = _u(row.get("code"))
            if not code:
                continue
            tags = [x.strip() for x in _u(row.get("active_tags")).split("|") if x.strip()]
            text = u" ".join([_u(row.get("description_prefix")), _u(row.get("description_name")), _u(row.get("description")), u" ".join(tags)])
            inferred = sorted(list(_tokenize(text).intersection(set([u"N1", u"VESTUARIOS", u"SR1", u"ST1", u"PA", u"PG"]))))
            items.append({
                u"code": code,
                u"description": _u(row.get("description")),
                u"description_prefix": _u(row.get("description_prefix")),
                u"description_name": _u(row.get("description_name")),
                u"active_tags": tags,
                u"inferred_tokens": inferred,
                u"project_zone_hint": inferred[0] if inferred else u"",
                u"project_sector_hint": u"",
                u"forbidden_tokens_suggested": [],
            })

    with codecs.open(BLOCKS_SEMANTIC_JSON, "w", "utf-8") as fp:
        fp.write(json.dumps({u"items": items, u"generated_at_utc": _now_utc_iso()}, ensure_ascii=False, indent=2))
    if log_lines is not None:
        log_lines.append(u"[PROJECT-CONFIG] blocks_semantic.json actualizado ({0} items)".format(len(items)))
    return len(items)
