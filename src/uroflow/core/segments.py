"""Segment detection: identify contiguous valid data spans without imputation."""

import numpy as np
from typing import List, Tuple
from uroflow.core.types import Segment, Gap


def find_segments_and_gaps(timestamp: np.ndarray, 
                           mass: np.ndarray,
                           dt_factor: float = 5.0) -> Tuple[List[Segment], List[Gap]]:
    """Identify contiguous spans of valid data and gaps.
    
    Segments are contiguous spans where:
    - All mass values are finite (not NaN)
    - Timestamps are continuous (no large jumps)
    
    Gaps are identified by:
    - Invalid mass samples (NaN)
    - Timestamp jumps: dt > (median_dt * dt_factor)
    
    Args:
        timestamp: Time array in seconds since session start
        mass: Mass array in grams (can contain NaN)
        dt_factor: Multiplier for gap detection threshold
        
    Returns:
        Tuple of (segments, gaps):
        - segments: List of Segment objects (contiguous valid spans)
        - gaps: List of Gap objects (missing or invalid data)
        
    Notes:
        NO IMPUTATION: Missing data remains missing, gaps break segments.
        When no segments are found but most data is valid, treats entire
        dataset as one segment (fallback for data with scattered NaN).
    """
    n = len(timestamp)
    
    if n == 0:
        return [], []
    
    # Calculate timestamp deltas (use nanmedian in case of outliers)
    dt = np.diff(timestamp)
    median_dt = np.nanmedian(dt[np.isfinite(dt)])
    if median_dt <= 0 or not np.isfinite(median_dt):
        median_dt = np.median(np.abs(dt)) or 0.05  # Fallback
    dt_threshold = median_dt * dt_factor
    
    # Identify valid samples (finite mass)
    valid = np.isfinite(mass)
    n_valid = np.sum(valid)
    valid_frac = n_valid / n if n > 0 else 0
    
    # Identify timestamp gaps (prepend False since diff reduces length by 1)
    # Only flag as gap if dt is both > threshold AND positive (ignore negative/zero)
    time_gaps = np.concatenate([[False], (dt > dt_threshold) & np.isfinite(dt)])
    
    # Combined: a sample is "broken" if it's invalid OR follows a time gap
    broken = ~valid | time_gaps
    
    # Find transitions: segment_starts = broken->valid, segment_ends = valid->broken
    segment_starts = np.where(np.diff(np.concatenate([[True], broken])) < 0)[0]
    segment_ends = np.where(np.diff(np.concatenate([broken, [True]])) > 0)[0]
    
    # Build segment list
    segments = []
    for start, end in zip(segment_starts, segment_ends):
        if end > start:
            segments.append(Segment(start_idx=start, end_idx=end))
    
    # Fallback: if no segments found but we have valid data, treat entire range as one segment
    # This handles data with scattered NaN or dt_factor fragmenting everything into tiny pieces
    if not segments and n_valid > 100:
        # Find first and last valid index
        valid_idx = np.where(valid)[0]
        if len(valid_idx) > 0:
            start_idx = int(valid_idx[0])
            end_idx = int(valid_idx[-1]) + 1
            if end_idx > start_idx:
                segments = [Segment(start_idx=start_idx, end_idx=end_idx)]
    
    # Find gaps (inverse of segments)
    gaps = []
    
    if segments:
        # Gap before first segment
        if segments[0].start_idx > 0:
            gaps.append(Gap(start_idx=0, end_idx=segments[0].start_idx))
        
        # Gaps between segments
        for i in range(len(segments) - 1):
            gap_start = segments[i].end_idx
            gap_end = segments[i + 1].start_idx
            if gap_end > gap_start:
                gaps.append(Gap(start_idx=gap_start, end_idx=gap_end))
        
        # Gap after last segment
        if segments[-1].end_idx < n:
            gaps.append(Gap(start_idx=segments[-1].end_idx, end_idx=n))
    else:
        # No segments, entire thing is a gap
        gaps = [Gap(start_idx=0, end_idx=n)]
    
    return segments, gaps


def get_segment_containing_idx(segments: List[Segment], idx: int) -> int:
    """Find which segment contains a given index.
    
    Args:
        segments: List of Segment objects
        idx: Sample index to search for
        
    Returns:
        Index of segment containing idx, or -1 if not in any segment
    """
    for i, seg in enumerate(segments):
        if seg.contains(idx):
            return i
    return -1


def get_segment_containing_time(segments: List[Segment], 
                                timestamp: np.ndarray,
                                time_s: float) -> int:
    """Find which segment contains a given time.
    
    Args:
        segments: List of Segment objects
        timestamp: Time array in seconds
        time_s: Time point to search for
        
    Returns:
        Index of segment containing time_s, or -1 if not in any segment
    """
    for i, seg in enumerate(segments):
        seg_start_time = timestamp[seg.start_idx]
        seg_end_time = timestamp[seg.end_idx - 1] if seg.end_idx > seg.start_idx else seg_start_time
        
        if seg_start_time <= time_s <= seg_end_time:
            return i
    return -1


def compute_segment_stats(segment: Segment,
                          timestamp: np.ndarray,
                          mass: np.ndarray) -> dict:
    """Compute statistics for a segment.
    
    Args:
        segment: Segment object
        timestamp: Time array
        mass: Mass array
        
    Returns:
        Dictionary with segment statistics
    """
    seg_t = timestamp[segment.start_idx:segment.end_idx]
    seg_m = mass[segment.start_idx:segment.end_idx]
    
    stats = {
        'n_samples': len(segment),
        'duration_s': seg_t[-1] - seg_t[0] if len(seg_t) > 1 else 0.0,
        'mean_mass_g': np.nanmean(seg_m),
        'std_mass_g': np.nanstd(seg_m),
        'min_mass_g': np.nanmin(seg_m),
        'max_mass_g': np.nanmax(seg_m),
        'start_time_s': seg_t[0] if len(seg_t) > 0 else 0.0,
        'end_time_s': seg_t[-1] if len(seg_t) > 0 else 0.0,
    }
    
    return stats


def check_event_crosses_gap(event_start_idx: int,
                            event_end_idx: int,
                            segments: List[Segment]) -> bool:
    """Check if an event window crosses a gap.
    
    Args:
        event_start_idx: Event start index
        event_end_idx: Event end index (exclusive)
        segments: List of Segment objects
        
    Returns:
        True if event crosses a gap, False if entirely within one segment
    """
    # Find which segment contains start
    start_seg = get_segment_containing_idx(segments, event_start_idx)
    
    if start_seg == -1:
        return True  # Starts in a gap
    
    # Check if entire event is within this segment
    if event_end_idx <= segments[start_seg].end_idx:
        return False  # Entire event in one segment
    
    return True  # Event crosses into another segment or gap


def merge_close_gaps(segments: List[Segment],
                    timestamp: np.ndarray,
                    max_gap_s: float) -> List[Segment]:
    """Merge segments separated by small gaps.
    
    Used when you want to treat brief interruptions as part of same segment.
    
    Args:
        segments: List of Segment objects
        timestamp: Time array
        max_gap_s: Maximum gap duration to merge (seconds)
        
    Returns:
        New list of merged segments
        
    Note:
        This does NOT fill gaps - it only adjusts segment boundaries
    """
    if len(segments) <= 1:
        return segments.copy()
    
    merged = []
    current = segments[0]
    
    for next_seg in segments[1:]:
        gap_start_time = timestamp[current.end_idx - 1] if current.end_idx > 0 else 0
        gap_end_time = timestamp[next_seg.start_idx]
        gap_duration = gap_end_time - gap_start_time
        
        if gap_duration <= max_gap_s:
            # Merge: extend current to include next
            current = Segment(
                start_idx=current.start_idx,
                end_idx=next_seg.end_idx
            )
        else:
            # Gap too large, finalize current and start new
            merged.append(current)
            current = next_seg
    
    # Add final segment
    merged.append(current)
    
    return merged
