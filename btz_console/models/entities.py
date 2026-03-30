from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class ArtifactReference:
    name: str
    path: str
    exists: bool
    size_bytes: int = 0
    updated_at: Optional[datetime] = None
    required: bool = False
    notes: str = ""


@dataclass
class DependencyStatus:
    key: str
    state: str  # OK | Warning | Error | Pending
    detail: str


@dataclass
class SuggestionRecord:
    matched_code: str
    display_value: str
    suggested_value: str
    confidence: float
    source: str
    reason: str


@dataclass
class GroupRecord:
    group_key: str
    refined_group_key: str
    macro_group: str
    category_name: str
    family_name: str
    type_name: str
    count: int
    confidence: float
    source_origin: str
    needs_review: bool
    candidate_btz_principal: str
    sample_ids: List[int] = field(default_factory=list)
    candidate_btz: List[SuggestionRecord] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class ApplyPreview:
    groups_to_apply: int = 0
    elements_affected: int = 0
    warnings: List[str] = field(default_factory=list)
    preview_rows: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class ReportSummary:
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: List[str] = field(default_factory=list)
    log_excerpt: List[str] = field(default_factory=list)


@dataclass
class ProjectContext:
    project_name: str
    public_dir: str
    elements_count: int
    groups_count: int
    refined_groups_count: int
    load_status: str
    warnings: List[str] = field(default_factory=list)
    dependencies: List[DependencyStatus] = field(default_factory=list)
    artifacts: List[ArtifactReference] = field(default_factory=list)
    recent_logs: List[str] = field(default_factory=list)
