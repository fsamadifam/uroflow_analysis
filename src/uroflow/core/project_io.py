"""Project persistence: save/load project.json with JSON serialization."""

import json
import os
import re
from pathlib import Path
from typing import Optional
from datetime import datetime
from dataclasses import asdict
import numpy as np

from uroflow.core.types import (
    Project,
    Event,
    DetectionParams,
    EventFeatures,
    SpatialCoordinates,
    get_human_friendly_id,
)


def standard_session_name(input_csv_path: str, session_config: Optional[dict] = None) -> str:
    """Return the standard filename stem for a recording session.

    The preferred source is the recording CSV name, for example
    ``uroflow_2026_06_25_10_08_08_cage227397_rat1.csv``.  If that name does
    not contain the standard suffix, session metadata is used instead.
    """
    stem = Path(input_csv_path).stem
    match = re.search(
        r"(?P<session>\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_cage[^_]+_rat[^_]+)$",
        stem,
        re.IGNORECASE,
    )
    if match:
        return match.group("session")

    config = session_config or {}
    date = str(config.get("start_date", "")).replace("-", "_")
    start_time = str(config.get("start_time", "")).replace(":", "_")
    if date and start_time and config.get("cage_id") is not None and config.get("rat_id") is not None:
        return f"{date}_{start_time}_cage{_safe_filename_component(config['cage_id'])}_rat{_safe_filename_component(config['rat_id'])}"

    # No session identifiers available: callers should use their plain
    # artifact name (for example, ``events_table.csv``).
    return ""


def _safe_filename_component(value) -> str:
    """Make a metadata value safe to use in a filename."""
    return re.sub(r"[^A-Za-z0-9.-]+", "", str(value))


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy types."""
    
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


def save_project(project: Project, output_path: str):
    """Save project to JSON file with atomic writes.
    
    Args:
        project: Project object to save
        output_path: Path to output JSON file
        
    Notes:
        - Uses atomic write (temp file + rename) to prevent corruption
        - Updates project.last_modified timestamp
    """
    output_path = Path(output_path)
    
    # Update modification time
    project.update_modified()
    
    # Convert to dictionary
    project_dict = _project_to_dict(project)
    
    # Write to temporary file first (atomic write)
    temp_path = output_path.with_suffix('.json.tmp')
    
    try:
        with open(temp_path, 'w') as f:
            json.dump(project_dict, f, indent=2, cls=NumpyEncoder)
        
        # Atomic rename
        temp_path.replace(output_path)
        
    except Exception as e:
        # Clean up temp file if it exists
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"Failed to save project: {e}")


def load_project(project_path: str) -> Project:
    """Load project from JSON file.
    
    Args:
        project_path: Path to project JSON file
        
    Returns:
        Project object
        
    Raises:
        FileNotFoundError: If project file doesn't exist
        json.JSONDecodeError: If JSON is invalid
        ValueError: If project structure is invalid
    """
    project_path = Path(project_path)
    
    if not project_path.exists():
        raise FileNotFoundError(f"Project file not found: {project_path}")
    
    try:
        with open(project_path, 'r') as f:
            project_dict = json.load(f)
        
        project = _dict_to_project(project_dict)
        return project
        
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"Invalid JSON in project file: {e}", e.doc, e.pos)
    except Exception as e:
        raise ValueError(f"Failed to load project: {e}")


def _project_to_dict(project: Project) -> dict:
    """Convert Project object to dictionary for JSON serialization.
    
    Args:
        project: Project object
        
    Returns:
        Dictionary representation
    """
    project_dict = {
        'input_csv_path': project.input_csv_path,
        'session_config_path': project.session_config_path,
        'session_config_snapshot': project.session_config_snapshot,
        'detection_params': asdict(project.detection_params),
        'events': [_event_to_dict(e) for e in project.events],
        'video_folder_path': project.video_folder_path,
        'spatial_calibration': project.spatial_calibration,
        'created_at': project.created_at,
        'last_modified': project.last_modified,
    }
    
    return project_dict


def _dict_to_project(project_dict: dict) -> Project:
    """Convert dictionary to Project object.
    
    Args:
        project_dict: Dictionary from JSON
        
    Returns:
        Project object
    """
    # Parse detection params
    params_dict = project_dict.get('detection_params', {})
    detection_params = DetectionParams.from_dict(params_dict)
    
    # Parse events
    events = [_dict_to_event(e) for e in project_dict['events']]
    
    project = Project(
        input_csv_path=project_dict['input_csv_path'],
        session_config_path=project_dict['session_config_path'],
        session_config_snapshot=project_dict['session_config_snapshot'],
        detection_params=detection_params,
        events=events,
        video_folder_path=project_dict.get('video_folder_path'),
        spatial_calibration=project_dict.get('spatial_calibration'),
        created_at=project_dict['created_at'],
        last_modified=project_dict['last_modified'],
    )
    
    return project


def _event_to_dict(event: Event) -> dict:
    """Convert Event object to dictionary.
    
    Args:
        event: Event object
        
    Returns:
        Dictionary representation
    """
    event_dict = {
        'event_id': event.event_id,
        'start_idx': event.start_idx,
        'end_idx': event.end_idx,
        'start_time_s': event.start_time_s,
        'end_time_s': event.end_time_s,
        'source': event.source,
        'locked': event.locked,
        'label_user': event.label_user,
        'notes': event.notes,
        'features': asdict(event.features) if event.features else None,
        'needs_manual': event.needs_manual,
        'wall_clock_time': event.wall_clock_time,
        'spatial_coords': event.spatial_coords.to_dict() if event.spatial_coords else None,
        'created_at': event.created_at,
        'modified_at': event.modified_at,
    }
    
    return event_dict


def _dict_to_event(event_dict: dict) -> Event:
    """Convert dictionary to Event object.
    
    Args:
        event_dict: Dictionary from JSON
        
    Returns:
        Event object
    """
    # Parse features if present
    features = None
    if event_dict['features'] is not None:
        features = EventFeatures(**event_dict['features'])
    
    # Parse spatial_coords if present
    spatial_coords = None
    sc_dict = event_dict.get('spatial_coords')
    if sc_dict is not None:
        spatial_coords = SpatialCoordinates.from_dict(sc_dict)

    event = Event(
        event_id=event_dict['event_id'],
        start_idx=event_dict['start_idx'],
        end_idx=event_dict['end_idx'],
        start_time_s=event_dict['start_time_s'],
        end_time_s=event_dict['end_time_s'],
        source=event_dict['source'],
        locked=event_dict['locked'],
        label_user=event_dict['label_user'],
        notes=event_dict['notes'],
        features=features,
        needs_manual=event_dict['needs_manual'],
        wall_clock_time=event_dict.get('wall_clock_time', ''),
        spatial_coords=spatial_coords,
        created_at=event_dict['created_at'],
        modified_at=event_dict['modified_at'],
    )
    
    return event


def _clean_export_notes(notes: str) -> str:
    """Remove obsolete detector debug metrics from notes before CSV export."""
    if not notes:
        return ""

    if notes.startswith("First-pass slope detector:"):
        suffix = ""
        if " [merged]" in notes:
            suffix += " [merged]"
        if " [trimmed]" in notes:
            suffix += " [trimmed]"
        return "First-pass slope detector" + suffix

    return notes


CALIBRATION_EXPORT_COLUMNS = [
    'calibration_cage_radius_cm',
    'calibration_center_x_px',
    'calibration_center_y_px',
    'calibration_semi_major_px',
    'calibration_semi_minor_px',
    'calibration_angle_rad',
]


def get_calibration_export_values(spatial_calibration: Optional[dict]) -> list:
    """Return stable per-row CSV values describing the project calibration."""
    values = {column: '' for column in CALIBRATION_EXPORT_COLUMNS}

    if not spatial_calibration:
        return [values[column] for column in CALIBRATION_EXPORT_COLUMNS]

    ellipse = spatial_calibration.get('ellipse') or {}
    homography = spatial_calibration.get('homography') or {}

    if ellipse:
        values['calibration_cage_radius_cm'] = ellipse.get('cage_radius_cm', '')
        values['calibration_center_x_px'] = ellipse.get('center_x', '')
        values['calibration_center_y_px'] = ellipse.get('center_y', '')
        values['calibration_semi_major_px'] = ellipse.get('semi_major', '')
        values['calibration_semi_minor_px'] = ellipse.get('semi_minor', '')
        values['calibration_angle_rad'] = ellipse.get('angle_rad', '')
    elif homography:
        values['calibration_cage_radius_cm'] = homography.get('cage_radius_cm', '')

    return [values[column] for column in CALIBRATION_EXPORT_COLUMNS]


def export_events_csv(events: list[Event], output_path: str,
                      spatial_calibration: Optional[dict] = None):
    """Export events to CSV format.
    
    Args:
        events: List of Event objects
        output_path: Path to output CSV file
        spatial_calibration: Optional project calibration metadata to repeat per row
    """
    import csv
    
    output_path = Path(output_path)
    calibration_values = get_calibration_export_values(spatial_calibration)
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        
        # Header
        writer.writerow([
            'human_event_id', 'event_id', 'start_idx', 'end_idx',
            'start_time_s', 'wall_clock_time', 'end_time_s', 'duration_s',
            'delta_mass_g', 'label_user', 'location', 'source', 'locked',
            'needs_manual', 'notes',
            'peak_slope_g_per_s', 'mean_slope_g_per_s', 'oscillation_score',
            'crosses_gap',
            'image_x', 'image_y', 'real_x_cm', 'real_y_cm', 'radius_cm', 'theta_deg',
            *CALIBRATION_EXPORT_COLUMNS,
        ])
        
        # Data rows
        sorted_events = sorted(events, key=lambda e: e.start_time_s)
        for event in sorted_events:
            location = ""
            if event.spatial_coords:
                location = f"({event.spatial_coords.real_x_cm:.1f}, {event.spatial_coords.real_y_cm:.1f})"

            row = [
                get_human_friendly_id(event, sorted_events),
                event.event_id,
                event.start_idx,
                event.end_idx,
                event.start_time_s,
                event.wall_clock_time,
                event.end_time_s,
                event.duration_s(),
            ]
            
            # Add features if present
            if event.features:
                row.extend([
                    event.features.delta_mass_g,
                ])
            else:
                row.extend([''])

            row.extend([
                event.label_user,
                location,
                event.source,
                event.locked,
                event.needs_manual,
                _clean_export_notes(event.notes),
            ])

            if event.features:
                row.extend([
                    event.features.peak_slope_g_per_s,
                    event.features.mean_slope_g_per_s,
                    event.features.oscillation_score,
                    event.features.crosses_gap,
                ])
            else:
                row.extend(['', '', '', ''])
            
            # Add spatial coordinates
            if event.spatial_coords:
                row.extend([
                    event.spatial_coords.image_x,
                    event.spatial_coords.image_y,
                    event.spatial_coords.real_x_cm,
                    event.spatial_coords.real_y_cm,
                    event.spatial_coords.radius_cm,
                    event.spatial_coords.theta_deg,
                ])
            else:
                row.extend(['', '', '', '', '', ''])

            row.extend(calibration_values)
            
            writer.writerow(row)


def autosave_project(project: Project, 
                    project_path: str,
                    autosave_interval_s: float = 300.0,
                    last_save_time: Optional[float] = None) -> Optional[float]:
    """Conditionally save project if enough time has passed.
    
    Args:
        project: Project object
        project_path: Path to project file
        autosave_interval_s: Minimum interval between autosaves (seconds)
        last_save_time: Timestamp of last save (from time.time()), or None
        
    Returns:
        New last_save_time if saved, otherwise None
    """
    import time
    
    current_time = time.time()
    
    if last_save_time is None or (current_time - last_save_time) >= autosave_interval_s:
        save_project(project, project_path)
        return current_time
    
    return None


def validate_project_paths(project: Project) -> tuple[bool, str]:
    """Validate that project file paths exist.
    
    Args:
        project: Project object
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    csv_path = Path(project.input_csv_path)
    if not csv_path.exists():
        return False, f"CSV file not found: {csv_path}"
    
    config_path = Path(project.session_config_path)
    if not config_path.exists():
        return False, f"Config file not found: {config_path}"
    
    return True, "OK"
