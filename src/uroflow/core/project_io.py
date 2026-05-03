"""Project persistence: save/load project.json with JSON serialization."""

import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime
from dataclasses import asdict
import numpy as np

from uroflow.core.types import Project, Event, DetectionParams, EventFeatures


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
    params_dict = project_dict['detection_params']
    detection_params = DetectionParams(**params_dict)
    
    # Parse events
    events = [_dict_to_event(e) for e in project_dict['events']]
    
    project = Project(
        input_csv_path=project_dict['input_csv_path'],
        session_config_path=project_dict['session_config_path'],
        session_config_snapshot=project_dict['session_config_snapshot'],
        detection_params=detection_params,
        events=events,
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
        created_at=event_dict['created_at'],
        modified_at=event_dict['modified_at'],
    )
    
    return event


def export_events_csv(events: list[Event], output_path: str):
    """Export events to CSV format.
    
    Args:
        events: List of Event objects
        output_path: Path to output CSV file
    """
    import csv
    
    output_path = Path(output_path)
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        
        # Header
        writer.writerow([
            'event_id', 'start_idx', 'end_idx', 
            'start_time_s', 'end_time_s', 'duration_s',
            'source', 'locked', 'label_user', 'notes',
            'delta_mass_g', 'peak_slope_g_per_s', 'oscillation_score',
            'plateau_stability', 'coverage_frac', 'crosses_gap', 'needs_manual'
        ])
        
        # Data rows
        for event in sorted(events, key=lambda e: e.start_time_s):
            row = [
                event.event_id,
                event.start_idx,
                event.end_idx,
                event.start_time_s,
                event.end_time_s,
                event.duration_s(),
                event.source,
                event.locked,
                event.label_user,
                event.notes,
            ]
            
            # Add features if present
            if event.features:
                row.extend([
                    event.features.delta_mass_g,
                    event.features.peak_slope_g_per_s,
                    event.features.oscillation_score,
                    event.features.plateau_stability,
                    event.features.coverage_frac,
                    event.features.crosses_gap,
                ])
            else:
                row.extend(['', '', '', '', '', ''])
            
            row.append(event.needs_manual)
            
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
