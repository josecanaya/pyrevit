from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from btz_console.config import ARTIFACT_SPECS
from btz_console.models import (
    DependencyStatus,
    GroupRecord,
    ProjectContext,
    SuggestionRecord,
)
from btz_console.services.file_discovery import discover_artifacts
from btz_console.services.loaders import load_csv_rows, load_json
from btz_console.services.log_parser import collect_recent_logs, extract_warnings


def _to_int(v, default=0) -> int:
    try:
        return int(v or default)
    except Exception:
        return default


def _to_float(v, default=0.0) -> float:
    try:
        return float(v or default)
    except Exception:
        return default


def _as_str(v) -> str:
    return str(v or "").strip()


def _candidate_to_suggestion(candidate, source: str) -> SuggestionRecord:
    if not isinstance(candidate, dict):
        return SuggestionRecord("", "", "", 0.0, source, "")
    display = _as_str(candidate.get("display_value"))
    matched_code = _as_str(candidate.get("matched_code"))
    suggested = _as_str(candidate.get("suggested_value"))
    if not display:
        display = "{} - {}".format(matched_code, suggested).strip(" -")
    return SuggestionRecord(
        matched_code=matched_code,
        display_value=display,
        suggested_value=suggested,
        confidence=_to_float(candidate.get("confidence")),
        source=source,
        reason=_as_str(candidate.get("reason")),
    )


def _load_revit_groups(public_dir: Path) -> List[Dict[str, str]]:
    p = public_dir / "revit_groups.csv"
    if not p.exists():
        return []
    return load_csv_rows(p)


def _load_revit_elements_count(public_dir: Path) -> int:
    p = public_dir / "revit_elements.csv"
    if not p.exists():
        return 0
    return len(load_csv_rows(p))


def _load_payload_enriched(public_dir: Path) -> List[Dict]:
    p = public_dir / "payload_groups.json"
    if not p.exists():
        return []
    data = load_json(p)
    if not isinstance(data, dict):
        return []
    groups = data.get("enriched_revit_groups")
    if isinstance(groups, list):
        return groups
    revit_groups = data.get("revit_groups")
    if isinstance(revit_groups, list):
        return revit_groups
    return []


def _load_manifest(public_dir: Path) -> Dict[str, Dict]:
    p = public_dir / "refined_groups_manifest.json"
    if not p.exists():
        return {}
    data = load_json(p)
    return data if isinstance(data, dict) else {}


def _load_webhook_mapping(public_dir: Path) -> Dict[str, Dict]:
    p = public_dir / "webhook_response.json"
    if not p.exists():
        return {}
    data = load_json(p)
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
    if not isinstance(data, dict):
        return {}
    gms = data.get("group_mappings")
    if not isinstance(gms, list):
        return {}
    out = {}
    for item in gms:
        if not isinstance(item, dict):
            continue
        gk = _as_str(item.get("group_key"))
        if gk:
            out[gk] = item
    return out


def _build_groups(public_dir: Path) -> Tuple[List[GroupRecord], int]:
    base_groups = _load_revit_groups(public_dir)
    enriched = _load_payload_enriched(public_dir)
    manifest = _load_manifest(public_dir)
    webhook = _load_webhook_mapping(public_dir)
    base_by_key = {(_as_str(r.get("group_key"))): r for r in base_groups}

    groups: List[GroupRecord] = []
    if enriched:
        for row in enriched:
            if not isinstance(row, dict):
                continue
            refined_key = _as_str(row.get("refined_group_key"))
            group_key = _as_str(row.get("base_group_key") or row.get("group_key"))
            key_lookup = refined_key or group_key
            base = base_by_key.get(group_key, {})
            candidates = row.get("candidate_btz") if isinstance(row.get("candidate_btz"), list) else []
            if not candidates and key_lookup in webhook:
                candidates = webhook[key_lookup].get("candidate_btz") or []
            suggestions = [_candidate_to_suggestion(c, "IA/Heurística") for c in candidates[:8]]
            principal = suggestions[0].display_value if suggestions else ""
            conf = _to_float(row.get("dominant_confidence"))
            if conf <= 0 and suggestions:
                conf = suggestions[0].confidence
            mf = manifest.get(key_lookup) or {}
            src = _as_str(row.get("group_origin") or mf.get("group_origin") or "base")
            needs_review = bool(row.get("needs_review") or mf.get("needs_review"))
            rec = GroupRecord(
                group_key=group_key,
                refined_group_key=refined_key,
                macro_group=_as_str(row.get("macro_group") or base.get("macro_group")),
                category_name=_as_str(row.get("category_name") or base.get("category_name")),
                family_name=_as_str(row.get("family_name") or base.get("family_name")),
                type_name=_as_str(row.get("type_name") or base.get("type_name")),
                count=_to_int(row.get("element_count") or row.get("count") or base.get("count")),
                confidence=conf,
                source_origin=src,
                needs_review=needs_review,
                candidate_btz_principal=principal,
                sample_ids=[_to_int(x) for x in (row.get("sample_element_ids") or []) if _to_int(x) > 0],
                candidate_btz=suggestions,
                metadata={
                    "split_reason": _as_str(row.get("split_reason")),
                    "classification_hint": _as_str(row.get("classification_hint") or mf.get("classification_hint")),
                },
            )
            groups.append(rec)
    else:
        for base in base_groups:
            gk = _as_str(base.get("group_key"))
            wm = webhook.get(gk, {})
            candidates = wm.get("candidate_btz") if isinstance(wm.get("candidate_btz"), list) else []
            suggestions = [_candidate_to_suggestion(c, "Webhook") for c in candidates[:8]]
            principal = suggestions[0].display_value if suggestions else ""
            groups.append(
                GroupRecord(
                    group_key=gk,
                    refined_group_key="",
                    macro_group=_as_str(base.get("macro_group")),
                    category_name=_as_str(base.get("category_name")),
                    family_name=_as_str(base.get("family_name")),
                    type_name=_as_str(base.get("type_name")),
                    count=_to_int(base.get("count")),
                    confidence=suggestions[0].confidence if suggestions else 0.0,
                    source_origin="base",
                    needs_review=False,
                    candidate_btz_principal=principal,
                    sample_ids=[],
                    candidate_btz=suggestions,
                    metadata={},
                )
            )

    return groups, len(base_groups)


def load_project_context(public_dir: Path) -> Tuple[ProjectContext, List[GroupRecord]]:
    artifacts = discover_artifacts(public_dir, ARTIFACT_SPECS)
    elements_count = _load_revit_elements_count(public_dir)
    groups, base_groups_count = _build_groups(public_dir)
    refined_count = len(groups)
    logs = collect_recent_logs(public_dir)
    warnings = extract_warnings(logs)

    missing_required = [a for a in artifacts if a.required and not a.exists]
    deps = [
        DependencyStatus(
            key="public_dir",
            state="OK" if public_dir.exists() else "Error",
            detail=str(public_dir),
        ),
        DependencyStatus(
            key="required_artifacts",
            state="OK" if not missing_required else "Warning",
            detail="Faltan {} artefactos requeridos".format(len(missing_required)),
        ),
    ]
    status = "OK"
    if missing_required:
        status = "Warning"
    if not public_dir.exists():
        status = "Error"

    project_name = public_dir.parent.name if public_dir.parent else "BTZ Project"
    ctx = ProjectContext(
        project_name=project_name,
        public_dir=str(public_dir),
        elements_count=elements_count,
        groups_count=base_groups_count,
        refined_groups_count=refined_count,
        load_status=status,
        warnings=warnings,
        dependencies=deps,
        artifacts=artifacts,
        recent_logs=logs[-120:],
    )
    return ctx, groups

