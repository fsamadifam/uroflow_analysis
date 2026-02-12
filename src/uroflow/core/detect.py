"""Auto-detection of events within segments using deterministic thresholds."""

import numpy as np
from typing import List
import uuid
from uroflow.core.types import Event, Segment, DetectionParams, EventSource
from uroflow.core.segments import check_event_crosses_gap


def detect_events_in_segments(timestamp: np.ndarray,
                              mass: np.ndarray,
                              segments: List[Segment],
                              params: DetectionParams) -> List[Event]:
    """Detect events within segments only (no cross-gap detection).
    
    For each segment:
    1. Compute rolling delta over diff_test_time window
    2. Apply threshold to find candidate regions (POSITIVE delta only - mass increase)
    3. Morphological cleanup (remove short runs, merge close events)
    4. Refine boundaries
    5. Filter by duration (min and max)
    6. Create Event objects
    
    Args:
        timestamp: Time array in seconds
        mass: Mass array in grams
        segments: List of Segment objects
        params: Detection parameters
        
    Returns:
        List of detected Event objects (source="auto")
        
    Notes:
        Events NEVER cross segment boundaries (gaps break detection)
        Only POSITIVE mass changes are detected (mass increase, not evaporation)
    """
    print(f"\n=== AUTO-DETECTION ===")
    print(f"Parameters: threshold={params.threshold_g}g, window={params.diff_test_time_s}s, "
          f"min_event={params.min_event_len_s}s, max_event={params.max_event_len_s}s, merge_gap={params.min_gap_merge_s}s")
    print(f"Processing {len(segments)} segments...")
    
    all_events = []
    
    for i, segment in enumerate(segments):
        segment_events = _detect_in_single_segment(
            timestamp, mass, segment, params
        )
        if segment_events:
            print(f"  Segment {i}: Found {len(segment_events)} events")
        all_events.extend(segment_events)
    
    print(f"Total auto-detected events: {len(all_events)}")
    print(f"======================\n")
    
    return all_events


def _detect_in_single_segment(timestamp: np.ndarray,
                              mass: np.ndarray,
                              segment: Segment,
                              params: DetectionParams) -> List[Event]:
    """Detect events within a single segment.
    
    Args:
        timestamp: Full time array
        mass: Full mass array
        segment: Segment to process
        params: Detection parameters
        
    Returns:
        List of Event objects found in this segment
    """
    # Extract segment data
    seg_t = timestamp[segment.start_idx:segment.end_idx]
    seg_m = mass[segment.start_idx:segment.end_idx]
    
    if len(seg_t) < 2:
        return []
    
    # Estimate sampling rate
    dt = np.diff(seg_t)
    median_dt = np.median(dt)
    fs = 1.0 / median_dt if median_dt > 0 else 10.0
    
    # Calculate window size in samples
    window_samples = max(2, int(params.diff_test_time_s * fs))
    
    if len(seg_m) < window_samples + 1:
        return []  # Segment too short for detection
    
    # Compute rolling delta
    delta = _compute_rolling_delta(seg_m, window_samples, params.min_valid_frac)
    
    # Debug: show delta statistics
    valid_delta = delta[np.isfinite(delta)]
    if len(valid_delta) > 0:
        max_delta = np.max(valid_delta)
        n_above_threshold = np.sum(valid_delta > params.threshold_g)
        if max_delta > params.threshold_g * 0.5:  # Only print if close to threshold
            print(f"    Segment [{segment.start_idx}:{segment.end_idx}]: "
                  f"max_delta={max_delta:.4f}g, {n_above_threshold} samples above threshold")
    
    # Apply threshold to get candidate mask
    candidate_mask = delta > params.threshold_g
    
    # Morphological cleanup
    cleaned_mask = _morphological_cleanup(
        candidate_mask, 
        seg_t,
        params.min_event_len_s,
        params.min_gap_merge_s
    )
    
    # Find runs of True values in cleaned mask
    event_windows = _find_mask_runs(cleaned_mask)
    
    if not event_windows:
        return []
    
    # Refine boundaries and create Event objects
    events = []
    for start_rel, end_rel in event_windows:
        # Refine boundaries
        refined_start, refined_end = _refine_boundaries(
            seg_m, seg_t, start_rel, end_rel, window_samples
        )
        
        # Convert to absolute indices
        abs_start_idx = segment.start_idx + refined_start
        abs_end_idx = segment.start_idx + refined_end
        
        # Get times
        start_time = timestamp[abs_start_idx]
        end_time = timestamp[abs_end_idx - 1] if abs_end_idx > abs_start_idx else start_time
        
        # Calculate duration and filter by max duration
        duration = end_time - start_time
        if duration > params.max_event_len_s:
            print(f"    Skipping event: duration {duration:.1f}s exceeds max {params.max_event_len_s}s")
            continue
        
        # Verify this is a mass INCREASE event (not evaporation/decrease)
        event_mass = mass[abs_start_idx:abs_end_idx]
        if len(event_mass) >= 2:
            # Compare start vs end mass using median for robustness
            start_mass = np.nanmedian(event_mass[:min(10, len(event_mass)//4+1)])
            end_mass = np.nanmedian(event_mass[-min(10, len(event_mass)//4+1):])
            if np.isfinite(start_mass) and np.isfinite(end_mass):
                if end_mass <= start_mass:
                    print(f"    Skipping event: mass decrease (start={start_mass:.3f}g, end={end_mass:.3f}g)")
                    continue
        
        # Create Event
        event = Event(
            event_id=str(uuid.uuid4()),
            start_idx=abs_start_idx,
            end_idx=abs_end_idx,
            start_time_s=start_time,
            end_time_s=end_time,
            source="auto",
            locked=False,
            label_user="",
            notes="",
            features=None,  # Will be computed later
            needs_manual=False
        )
        
        events.append(event)
    
    return events


def _compute_rolling_delta(mass: np.ndarray,
                           window: int,
                           min_valid_frac: float) -> np.ndarray:
    """Compute rolling delta: mass[i] - mass[i-window].
    
    Only computes delta if sufficient valid samples in window.
    
    Args:
        mass: Mass array for segment
        window: Window size in samples
        min_valid_frac: Minimum fraction of valid samples required
        
    Returns:
        Delta array (same length as mass, with NaN where invalid)
    """
    n = len(mass)
    delta = np.full(n, np.nan)
    
    for i in range(window, n):
        window_data = mass[i-window:i+1]
        valid_count = np.sum(np.isfinite(window_data))
        valid_frac = valid_count / len(window_data)
        
        if valid_frac >= min_valid_frac:
            # Use nanmean of endpoints to handle occasional NaN
            current = mass[i] if np.isfinite(mass[i]) else np.nan
            past = mass[i-window] if np.isfinite(mass[i-window]) else np.nan
            
            if np.isfinite(current) and np.isfinite(past):
                delta[i] = current - past
    
    return delta


def _morphological_cleanup(mask: np.ndarray,
                           timestamp: np.ndarray,
                           min_event_len_s: float,
                           min_gap_merge_s: float) -> np.ndarray:
    """Apply morphological operations to clean up candidate mask.
    
    1. Remove runs shorter than min_event_len_s
    2. Fill holes shorter than min_gap_merge_s
    
    Args:
        mask: Boolean mask of candidates
        timestamp: Time array
        min_event_len_s: Minimum event duration
        min_gap_merge_s: Maximum gap to fill
        
    Returns:
        Cleaned boolean mask
    """
    if len(mask) == 0:
        return mask.copy()
    
    # Remove short runs
    mask = _remove_short_runs(mask, timestamp, min_event_len_s, True)
    
    # Fill short gaps (holes)
    mask = _remove_short_runs(~mask, timestamp, min_gap_merge_s, False)
    
    return mask


def _remove_short_runs(mask: np.ndarray,
                      timestamp: np.ndarray,
                      min_duration_s: float,
                      remove_true: bool) -> np.ndarray:
    """Remove runs of True (or False) values that are too short.
    
    Args:
        mask: Boolean mask
        timestamp: Time array
        min_duration_s: Minimum run duration
        remove_true: If True, remove short True runs; if False, remove short False runs
        
    Returns:
        Cleaned mask
    """
    if remove_true:
        target_mask = mask.copy()
    else:
        target_mask = ~mask
    
    # Find runs
    runs = _find_mask_runs(target_mask)
    
    cleaned = mask.copy()
    
    for start, end in runs:
        duration = timestamp[end - 1] - timestamp[start] if end > start else 0.0
        
        if duration < min_duration_s:
            # Remove this run
            if remove_true:
                cleaned[start:end] = False
            else:
                cleaned[start:end] = True
    
    return cleaned


def _find_mask_runs(mask: np.ndarray) -> List[tuple]:
    """Find runs of True values in boolean mask.
    
    Args:
        mask: Boolean mask
        
    Returns:
        List of (start_idx, end_idx) tuples for each run (end_idx exclusive)
    """
    if len(mask) == 0 or not np.any(mask):
        return []
    
    # Add False padding to detect runs at boundaries
    padded = np.concatenate([[False], mask, [False]])
    
    # Find transitions
    diff = np.diff(padded.astype(int))
    starts = np.where(diff == 1)[0]  # False -> True
    ends = np.where(diff == -1)[0]   # True -> False
    
    return list(zip(starts, ends))


def _refine_boundaries(mass: np.ndarray,
                      timestamp: np.ndarray,
                      start: int,
                      end: int,
                      window: int) -> tuple:
    """Refine event boundaries by looking for onset/offset in slope.
    
    Expands slightly pre/post, then snaps to where slope changes sign.
    
    Args:
        mass: Mass array for segment
        timestamp: Time array for segment
        start: Initial start index (relative to segment)
        end: Initial end index (relative to segment, exclusive)
        window: Rolling window size used for detection
        
    Returns:
        Tuple of (refined_start, refined_end)
    """
    # Expand search region
    expansion = min(window, len(mass) // 10)
    search_start = max(0, start - expansion)
    search_end = min(len(mass), end + expansion)
    
    # Find onset: look backward from start for slope sign change
    refined_start = _find_onset(mass, search_start, start, window_size=5)
    
    # Find offset: look forward from end for slope sign change
    refined_end = _find_offset(mass, end, search_end, window_size=5)
    
    # Ensure boundaries are valid
    refined_start = max(0, refined_start)
    refined_end = min(len(mass), refined_end)
    
    if refined_end <= refined_start:
        refined_end = refined_start + 1
    
    return refined_start, refined_end


def _find_onset(mass: np.ndarray, search_start: int, event_start: int, window_size: int) -> int:
    """Find event onset by looking for positive slope.
    
    Args:
        mass: Mass array
        search_start: Start of search region
        event_start: Initial event start
        window_size: Window for slope estimation
        
    Returns:
        Refined start index
    """
    if event_start - search_start < window_size:
        return event_start
    
    # Compute slope in search region
    for i in range(event_start, search_start, -1):
        if i < window_size:
            break
        
        # Simple slope estimate
        window_m = mass[i-window_size:i]
        if np.sum(np.isfinite(window_m)) < window_size // 2:
            continue
        
        slope = np.nanmean(np.diff(window_m))
        
        # Look for transition to positive slope
        if slope > 0:
            return i
    
    return event_start


def _find_offset(mass: np.ndarray, event_end: int, search_end: int, window_size: int) -> int:
    """Find event offset by looking for slope returning to zero.
    
    Args:
        mass: Mass array
        event_end: Initial event end
        search_end: End of search region
        window_size: Window for slope estimation
        
    Returns:
        Refined end index
    """
    if search_end - event_end < window_size:
        return event_end
    
    # Compute slope in search region
    for i in range(event_end, search_end):
        if i + window_size >= len(mass):
            break
        
        # Simple slope estimate
        window_m = mass[i:i+window_size]
        if np.sum(np.isfinite(window_m)) < window_size // 2:
            continue
        
        slope = np.nanmean(np.diff(window_m))
        
        # Look for slope near zero (plateau)
        if abs(slope) < 0.001:  # Threshold for "flat"
            return i
    
    return event_end


def detect_from_acquisition_flags(timestamp: np.ndarray,
                                  mass: np.ndarray,
                                  acquisition_windows: List[tuple],
                                  segments: List[Segment]) -> List[Event]:
    """Convert acquisition event flags to Event objects.
    
    Args:
        timestamp: Time array
        mass: Mass array
        acquisition_windows: List of (start_idx, end_idx) from acquisition flags
        segments: List of Segment objects
        
    Returns:
        List of Event objects with source="acquisition"
    """
    events = []
    
    for start_idx, end_idx in acquisition_windows:
        # Check if this window crosses a gap
        crosses_gap = check_event_crosses_gap(start_idx, end_idx, segments)
        
        # Get times
        start_time = timestamp[start_idx]
        end_time = timestamp[end_idx - 1] if end_idx > start_idx else start_time
        
        event = Event(
            event_id=str(uuid.uuid4()),
            start_idx=start_idx,
            end_idx=end_idx,
            start_time_s=start_time,
            end_time_s=end_time,
            source="acquisition",
            locked=False,  # Can be edited
            label_user="",  # Unlabeled initially
            notes="From acquisition flags",
            features=None,
            needs_manual=crosses_gap  # Flag if crosses gap
        )
        
        events.append(event)
    
    return events
