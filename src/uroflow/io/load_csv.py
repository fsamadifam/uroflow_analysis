"""CSV loading with event column conversion."""

import numpy as np
import pandas as pd
from typing import Tuple, List, Optional
from pathlib import Path


def load_uroflow_csv(csv_path: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Load uroflow CSV and return numpy arrays.
    
    Args:
        csv_path: Path to CSV file
        
    Returns:
        Tuple of:
        - timestamp (np.ndarray): Time in seconds since session start
        - mass (np.ndarray): Mass in grams (contains NaN for invalid samples)
        - acquisition_events (np.ndarray): Boolean array where True = event flagged during acquisition
        - metadata (dict): Additional columns (cage_id, rat_id, wall_clock_time, etc.)
        
    Raises:
        FileNotFoundError: If CSV file doesn't exist
        ValueError: If required columns are missing
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    # Load CSV with pandas (one-time operation)
    df = pd.read_csv(csv_path)
    
    # Validate required columns
    required_cols = ['timestamp', 'mass']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Extract timestamp and mass arrays
    timestamp = df['timestamp'].values.astype(float)
    mass = df['mass'].values.astype(float)
    
    # Handle 'event' column if present (acquisition flags)
    if 'event' in df.columns:
        # Convert 'y'/'n' to boolean (handle various formats)
        event_col = df['event'].astype(str).str.lower().str.strip()
        acquisition_events = (event_col == 'y') | (event_col == 'yes') | (event_col == 'true') | (event_col == '1')
    else:
        # No event column, all False
        acquisition_events = np.zeros(len(df), dtype=bool)
    
    # Extract metadata
    metadata = {}
    metadata_cols = ['cage_id', 'rat_id', 'wall_clock_time']
    for col in metadata_cols:
        if col in df.columns:
            metadata[col] = df[col].values
    
    # Store original shape info
    metadata['n_samples'] = len(timestamp)
    metadata['source_file'] = str(csv_path)
    
    return timestamp, mass, acquisition_events, metadata


def wall_clock_at_index(metadata: Optional[dict], idx: int) -> str:
    """Return wall_clock_time string from CSV metadata for a sample index."""
    if metadata is None or 'wall_clock_time' not in metadata:
        return ""
    wct = metadata['wall_clock_time']
    if idx < 0 or idx >= len(wct):
        return ""
    return str(wct[idx])


def find_acquisition_event_windows(timestamp: np.ndarray, 
                                   acquisition_events: np.ndarray,
                                   min_gap_s: float = 1.0) -> List[Tuple[int, int]]:
    """Convert acquisition event flags to event windows.
    
    Groups consecutive 'y' flags into windows, merging nearby events.
    
    Args:
        timestamp: Time array in seconds
        acquisition_events: Boolean array of acquisition flags
        min_gap_s: Minimum gap in seconds to separate events
        
    Returns:
        List of (start_idx, end_idx) tuples for each event window
    """
    if not np.any(acquisition_events):
        return []
    
    # Find runs of True values
    event_indices = np.where(acquisition_events)[0]
    
    if len(event_indices) == 0:
        return []
    
    windows = []
    start_idx = event_indices[0]
    prev_idx = event_indices[0]
    
    for idx in event_indices[1:]:
        # Check if this index is part of same event or new event
        time_gap = timestamp[idx] - timestamp[prev_idx]
        idx_gap = idx - prev_idx
        
        if time_gap > min_gap_s or idx_gap > 100:  # New event
            windows.append((start_idx, prev_idx + 1))  # end_idx is exclusive
            start_idx = idx
        
        prev_idx = idx
    
    # Add final window
    windows.append((start_idx, prev_idx + 1))
    
    # Expand windows slightly to ensure we capture full event
    expanded_windows = []
    for start_idx, end_idx in windows:
        # Expand by 5% on each side or min 10 samples
        expansion = max(10, int((end_idx - start_idx) * 0.05))
        expanded_start = max(0, start_idx - expansion)
        expanded_end = min(len(timestamp), end_idx + expansion)
        expanded_windows.append((expanded_start, expanded_end))
    
    return expanded_windows


def validate_csv_structure(csv_path: str) -> Tuple[bool, str]:
    """Quick validation of CSV structure without full load.
    
    Args:
        csv_path: Path to CSV file
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        csv_path = Path(csv_path)
        if not csv_path.exists():
            return False, f"File not found: {csv_path}"
        
        # Read just first few rows
        df_head = pd.read_csv(csv_path, nrows=5)
        
        # Check required columns
        required_cols = ['timestamp', 'mass']
        missing_cols = [col for col in required_cols if col not in df_head.columns]
        if missing_cols:
            return False, f"Missing required columns: {missing_cols}"
        
        # Check data types can be converted
        try:
            df_head['timestamp'].astype(float)
            df_head['mass'].astype(float)
        except (ValueError, TypeError) as e:
            return False, f"Invalid data types: {e}"
        
        return True, "OK"
        
    except Exception as e:
        return False, f"Error reading CSV: {e}"
