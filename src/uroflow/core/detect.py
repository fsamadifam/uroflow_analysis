"""Auto-detection of uroflow events using deterministic thresholds."""

import numpy as np
import pandas as pd
from typing import List
import uuid
from uroflow.core.types import Event, Segment, DetectionParams
from uroflow.core.segments import check_event_crosses_gap


def detect_events_in_segments(timestamp: np.ndarray,
                              mass: np.ndarray,
                              segments: List[Segment],
                              params: DetectionParams) -> List[Event]:
    """Detect events within contiguous segments using the first-pass slope detector.

    Pipeline for each segment:
    1. Rolling median smooth the raw mass trace
    2. Compute slope as delta mass / delta time
    3. Threshold positive slopes
    4. Merge close candidate regions
    5. Expand candidate windows and merge overlaps
    6. Validate each window by cumulative smoothed mass step and duration
    
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
    print(
        "Parameters: "
        f"smooth={params.diff_test_time_s}s, "
        f"slope_threshold={params.slope_threshold_g_s}g/s, "
        f"merge_gap={params.min_gap_merge_s}s, "
        f"expand={params.expand_event_s}s, "
        f"baseline={params.baseline_window_s}s, "
        f"min_delta={params.min_delta_mass_g}g, "
        f"min_event={params.min_event_len_s}s, "
        f"max_event={params.max_event_len_s}s"
    )
    print(f"Processing {len(segments)} segments...")
    
    all_events = []
    totals = {
        "raw_regions": 0,
        "merged_regions": 0,
        "expanded_regions": 0,
    }
    
    for i, segment in enumerate(segments):
        segment_events, stats = _detect_in_single_segment(
            timestamp, mass, segment, params
        )
        totals["raw_regions"] += stats["raw_regions"]
        totals["merged_regions"] += stats["merged_regions"]
        totals["expanded_regions"] += stats["expanded_regions"]
        if segment_events:
            print(f"  Segment {i}: Found {len(segment_events)} events")
        all_events.extend(segment_events)
    
    print(f"Raw positive-slope regions: {totals['raw_regions']:,}")
    print(f"Merged positive-slope regions: {totals['merged_regions']:,}")
    print(f"Expanded + re-merged regions: {totals['expanded_regions']:,}")
    print(f"Total auto-detected events: {len(all_events)}")
    print(f"======================\n")
    
    return all_events


def _detect_in_single_segment(timestamp: np.ndarray,
                              mass: np.ndarray,
                              segment: Segment,
                              params: DetectionParams) -> tuple[List[Event], dict]:
    """Detect events within one contiguous segment."""
    empty_stats = {
        "raw_regions": 0,
        "merged_regions": 0,
        "expanded_regions": 0,
    }

    seg_t = timestamp[segment.start_idx:segment.end_idx]
    seg_m = mass[segment.start_idx:segment.end_idx]

    if len(seg_t) < 2 or len(seg_m) < 2:
        return [], empty_stats

    dt = np.diff(seg_t)
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if len(dt) == 0:
        return [], empty_stats

    dt_median = float(np.median(dt))
    if not np.isfinite(dt_median) or dt_median <= 0:
        return [], empty_stats

    mass_smooth = _rolling_median_smooth(
        seg_m,
        smooth_seconds=params.diff_test_time_s,
        dt_median=dt_median,
        min_valid_frac=params.min_valid_frac,
    )

    dm = np.diff(mass_smooth, prepend=mass_smooth[0])
    dt_full = np.diff(seg_t, prepend=seg_t[0])
    slope = np.zeros_like(mass_smooth, dtype=float)
    np.divide(dm, dt_full, out=slope, where=(dt_full > 0))
    slope = np.where(np.isfinite(slope), slope, 0.0)

    candidate_mask = slope > params.slope_threshold_g_s
    raw_regions = _extract_regions(candidate_mask)
    merged_regions = _merge_regions(raw_regions, seg_t, max_gap_s=params.min_gap_merge_s)

    expand_n = int(round(params.expand_event_s / dt_median))
    expanded_regions = [
        [
            max(0, start - expand_n),
            min(len(seg_t) - 1, end + expand_n),
        ]
        for start, end in merged_regions
    ]
    expanded_merged_regions = _merge_regions(expanded_regions, seg_t, max_gap_s=0.0)

    stats = {
        "raw_regions": len(raw_regions),
        "merged_regions": len(merged_regions),
        "expanded_regions": len(expanded_merged_regions),
    }

    baseline_n = int(round(params.baseline_window_s / dt_median))
    events = []

    for start_rel, end_rel in expanded_merged_regions:
        pre_start = max(0, start_rel - baseline_n)
        pre_end = start_rel
        post_start = end_rel
        post_end = min(len(seg_t) - 1, end_rel + baseline_n)

        mass_before = np.nanmedian(mass_smooth[pre_start:pre_end + 1])
        mass_after = np.nanmedian(mass_smooth[post_start:post_end + 1])

        if not np.isfinite(mass_before) or not np.isfinite(mass_after):
            continue

        delta_mass_g = float(mass_after - mass_before)
        duration_s = float(seg_t[end_rel] - seg_t[start_rel])
        is_valid_event = (
            delta_mass_g >= params.min_delta_mass_g
            and params.min_event_len_s <= duration_s <= params.max_event_len_s
        )
        if not is_valid_event:
            continue

        abs_start_idx = segment.start_idx + start_rel
        abs_end_idx = segment.start_idx + end_rel + 1

        event = Event(
            event_id=str(uuid.uuid4()),
            start_idx=abs_start_idx,
            end_idx=abs_end_idx,
            start_time_s=float(timestamp[abs_start_idx]),
            end_time_s=float(timestamp[abs_end_idx - 1]),
            source="auto",
            locked=False,
            label_user="",
            notes="First-pass slope detector",
            features=None,
            needs_manual=False
        )
        events.append(event)
    
    return events, stats


def _rolling_median_smooth(mass: np.ndarray,
                           smooth_seconds: float,
                           dt_median: float,
                           min_valid_frac: float) -> np.ndarray:
    """Apply centered rolling median smoothing using a time-derived sample window."""
    smooth_window = int(round(smooth_seconds / dt_median))
    if smooth_window % 2 == 0:
        smooth_window += 1
    smooth_window = max(smooth_window, 5)

    min_periods = max(3, int(smooth_window * min_valid_frac))
    min_periods = min(min_periods, smooth_window)

    return (
        pd.Series(mass)
        .rolling(window=smooth_window, center=True, min_periods=min_periods)
        .median()
        .bfill()
        .ffill()
        .to_numpy()
    )


def _extract_regions(mask: np.ndarray) -> List[list[int]]:
    """Convert a boolean mask into contiguous inclusive True regions."""
    mask = np.asarray(mask, dtype=bool)
    if len(mask) == 0:
        return []

    starts = np.flatnonzero(mask & ~np.r_[False, mask[:-1]])
    ends = np.flatnonzero(mask & ~np.r_[mask[1:], False])
    return [[int(start), int(end)] for start, end in zip(starts, ends)]


def _merge_regions(regions: List[list[int]],
                   time_s: np.ndarray,
                   max_gap_s: float = 0.0) -> List[list[int]]:
    """Merge neighboring inclusive regions if the time gap is small."""
    if len(regions) == 0:
        return []

    regions = sorted(regions, key=lambda x: x[0])
    merged = [regions[0].copy()]

    for start, end in regions[1:]:
        previous_end = merged[-1][1]
        gap_s = time_s[start] - time_s[previous_end]

        if gap_s <= max_gap_s:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    return merged


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
