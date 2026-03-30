from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from btz_console.models import ArtifactReference


def discover_artifacts(public_dir: Path, artifact_specs) -> List[ArtifactReference]:
    refs = []
    for name, required in artifact_specs:
        p = public_dir / name
        exists = p.exists() and p.is_file()
        size = p.stat().st_size if exists else 0
        mtime = datetime.fromtimestamp(p.stat().st_mtime) if exists else None
        refs.append(
            ArtifactReference(
                name=name,
                path=str(p),
                exists=exists,
                size_bytes=size,
                updated_at=mtime,
                required=bool(required),
            )
        )
    return refs

