from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from btz_console.models import GroupRecord, ProjectContext
from btz_console.services import load_project_context


@dataclass
class AppState:
    public_dir: Path
    context: Optional[ProjectContext] = None
    groups: List[GroupRecord] = field(default_factory=list)
    selected_group: Optional[GroupRecord] = None

    def refresh(self):
        self.context, self.groups = load_project_context(self.public_dir)
        if self.selected_group:
            current_key = (self.selected_group.refined_group_key or self.selected_group.group_key)
            self.selected_group = next(
                (
                    g
                    for g in self.groups
                    if (g.refined_group_key or g.group_key) == current_key
                ),
                None,
            )

