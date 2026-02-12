"""Session configuration loading utilities."""

import json
from pathlib import Path
from typing import Optional


def load_session_config(config_path: str) -> dict:
    """Load session configuration JSON file.
    
    Args:
        config_path: Path to session_config.json file
        
    Returns:
        Dictionary containing session configuration
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If config file is not valid JSON
    """
    config_path = Path(config_path)
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    return config


def get_detection_params_from_config(config: dict) -> dict:
    """Extract detection parameters from session config.
    
    Args:
        config: Session configuration dictionary
        
    Returns:
        Dictionary with detection parameters (can be used to create DetectionParams)
    """
    config_snapshot = config.get('config_snapshot', {})
    
    params = {
        'diff_test_time_s': config_snapshot.get('diff_test_time', 5.0),
        'threshold_g': config_snapshot.get('threshold', 0.05),
    }
    
    return params


def validate_session_config(config_path: str) -> tuple[bool, str]:
    """Validate session configuration file.
    
    Args:
        config_path: Path to session_config.json file
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        config = load_session_config(config_path)
        
        # Check for expected fields (not all required, just common ones)
        expected_fields = ['cage_id', 'rat_id', 'start_date', 'start_time']
        missing_fields = [f for f in expected_fields if f not in config]
        
        if missing_fields:
            return True, f"Warning: Missing optional fields: {missing_fields}"
        
        return True, "OK"
        
    except FileNotFoundError as e:
        return False, str(e)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except Exception as e:
        return False, f"Error validating config: {e}"


def get_session_metadata(config: dict) -> dict:
    """Extract metadata from session config for display.
    
    Args:
        config: Session configuration dictionary
        
    Returns:
        Dictionary with formatted metadata
    """
    metadata = {}
    
    # Basic session info
    if 'cage_id' in config:
        metadata['cage_id'] = config['cage_id']
    if 'rat_id' in config:
        metadata['rat_id'] = config['rat_id']
    
    # Timestamps
    if 'start_date' in config and 'start_time' in config:
        metadata['session_start'] = f"{config['start_date']} {config['start_time']}"
    
    if 'end_date' in config and 'end_time' in config:
        metadata['session_end'] = f"{config['end_date']} {config['end_time']}"
    
    if 'duration_readable' in config:
        metadata['duration'] = config['duration_readable']
    
    # Acquisition parameters
    if 'config_snapshot' in config:
        snap = config['config_snapshot']
        if 'threshold' in snap:
            metadata['acq_threshold'] = f"{snap['threshold']} g"
        if 'diff_test_time' in snap:
            metadata['acq_diff_time'] = f"{snap['diff_test_time']} s"
        if 'use_camera' in snap:
            metadata['has_video'] = snap['use_camera']
    
    return metadata
