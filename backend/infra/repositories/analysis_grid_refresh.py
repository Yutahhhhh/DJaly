"""Replace saved automatic grids when explicitly reanalyzing, never manual edits."""
import json
from datetime import datetime

from api.schemas.performance_metadata import BeatGrid
from domain.models.performance_metadata import TrackPerformanceMetadata


def refresh_saved_analysis_grid(session, track_id, new_grid):
    if not new_grid:
        return
    grid = BeatGrid.model_validate(new_grid)
    if grid.source != "analysis":
        raise ValueError("Expected an analysis grid")
    row = session.get(TrackPerformanceMetadata, track_id)
    if row is None or not row.beat_grid_json:
        return
    try:
        old = json.loads(row.beat_grid_json)
    except (ValueError, TypeError):
        return
    # All editor transformations explicitly set source=manual. Legacy data
    # without a source is also protected. Cues/loops keep their exact bytes.
    if not isinstance(old, dict) or old.get("source") != "analysis":
        return
    serialized = grid.model_dump_json()
    if old != json.loads(serialized):
        row.beat_grid_json = serialized
        row.revision += 1  # An open editor must reload, not overwrite this result.
        row.updated_at = datetime.now()
        session.add(row)
