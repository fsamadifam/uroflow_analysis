"""Feature computation for events (for triage, not classification)."""

import numpy as np
from typing import List, Optional
from uroflow.core.types import Event, EventFeatures, Segment
from uroflow.core.segments import check_event_crosses_gap


def compute_event_features(event: Event,
                           timestamp: np.ndarray,
                           mass: np.ndarray,
                           segments: List[Segment]) -> EventFeatures:
    """Compute features for a single event.
    
    Features are used for triage/sorting, NOT for automated classification.
    
    Args:
        event: Event object
        timestamp: Full time array
        mass: Full mass array
        segments: List of Segment objects
        
    Returns:
        EventFeatures object
        
    Notes:
        If event crosses a gap, some features may be NaN or unreliable
    """
    # Extract event window
    event_t = timestamp[event.start_idx:event.end_idx]
    event_m = mass[event.start_idx:event.end_idx]
    
    # Check if crosses gap
    crosses_gap = check_event_crosses_gap(event.start_idx, event.end_idx, segments)
    
    # Compute duration
    duration_s = event_t[-1] - event_t[0] if len(event_t) > 1 else 0.0
    
    # Compute delta mass (pre vs post)
    delta_mass_g = _compute_delta_mass(
        timestamp, mass, event.start_idx, event.end_idx
    )
    
    # Compute peak slope (sharpness)
    peak_slope_g_per_s = _compute_peak_slope(event_t, event_m)
    
    # Compute mean slope (overall behavior)
    mean_slope_g_per_s = _compute_mean_slope(event_t, event_m, delta_mass_g, duration_s)
    
    # Compute oscillation score
    oscillation_score = _compute_oscillation_score(event_m)
    
    # Create features object
    try:
        features = EventFeatures(
            duration_s=duration_s,
            delta_mass_g=delta_mass_g,
            peak_slope_g_per_s=peak_slope_g_per_s,
            mean_slope_g_per_s=mean_slope_g_per_s,
            oscillation_score=oscillation_score,
            crosses_gap=crosses_gap
        )
    except ValueError:
        # If validation fails (non-finite values), create with crosses_gap=True
        features = EventFeatures(
            duration_s=duration_s if np.isfinite(duration_s) else 0.0,
            delta_mass_g=delta_mass_g if np.isfinite(delta_mass_g) else 0.0,
            peak_slope_g_per_s=peak_slope_g_per_s if np.isfinite(peak_slope_g_per_s) else 0.0,
            mean_slope_g_per_s=mean_slope_g_per_s if np.isfinite(mean_slope_g_per_s) else 0.0,
            oscillation_score=oscillation_score if np.isfinite(oscillation_score) else 0.0,
            crosses_gap=True
        )
    
    return features


def compute_features_for_events(events: List[Event],
                                timestamp: np.ndarray,
                                mass: np.ndarray,
                                segments: List[Segment],
                                metadata: Optional[dict] = None) -> List[Event]:
    """Compute features for all events in place.
    
    Args:
        events: List of Event objects (will be modified in place)
        timestamp: Full time array
        mass: Full mass array
        segments: List of Segment objects
        metadata: Optional metadata dict with wall_clock_time array
        
    Returns:
        Same list of events with features populated
    """
    for event in events:
        event.features = compute_event_features(event, timestamp, mass, segments)
        
        # Set needs_manual flag if crosses gap
        if event.features.crosses_gap:
            event.needs_manual = True
        
        # Populate wall_clock_time if not already set and metadata available
        if not event.wall_clock_time and metadata:
            wall_clock_time = _get_wall_clock_for_event(event, metadata)
            if wall_clock_time:
                event.wall_clock_time = wall_clock_time
    
    return events


def _get_wall_clock_for_event(event: Event, metadata: dict) -> str:
    """Get wall clock time string for an event from metadata.
    
    Args:
        event: Event object
        metadata: Metadata dict with wall_clock_time array
        
    Returns:
        Wall clock time string or empty string if not available
    """
    if 'wall_clock_time' not in metadata:
        return ""
    
    wall_clock_times = metadata['wall_clock_time']
    
    # Use start_idx to get the wall clock time
    idx = event.start_idx
    if 0 <= idx < len(wall_clock_times):
        wct = wall_clock_times[idx]
        return str(wct) if wct else ""
    
    return ""


def _compute_delta_mass(timestamp: np.ndarray,
                       mass: np.ndarray,
                       start_idx: int,
                       end_idx: int,
                       baseline_window_s: float = 10.0,
                       post_window_s: float = 5.0) -> float:
    """Compute net mass change: post - pre using robust statistics.
    
    Args:
        timestamp: Full time array
        mass: Full mass array
        start_idx: Event start index
        end_idx: Event end index
        baseline_window_s: Duration before event for baseline (seconds)
        post_window_s: Duration after event for post measurement (seconds)
        
    Returns:
        Delta mass in grams (post - pre)
    """
    # Find pre-event baseline window
    pre_start_time = timestamp[start_idx] - baseline_window_s
    pre_start_idx = np.searchsorted(timestamp, pre_start_time)
    pre_start_idx = max(0, pre_start_idx)
    
    pre_mass = mass[pre_start_idx:start_idx]
    pre_median = np.nanmedian(pre_mass) if len(pre_mass) > 0 else np.nan
    
    # Find post-event window
    post_end_time = timestamp[end_idx - 1] + post_window_s if end_idx > 0 else timestamp[-1]
    post_end_idx = np.searchsorted(timestamp, post_end_time)
    post_end_idx = min(len(timestamp), post_end_idx)
    
    post_mass = mass[end_idx:post_end_idx]
    post_median = np.nanmedian(post_mass) if len(post_mass) > 0 else np.nan
    
    # Compute delta
    if np.isfinite(pre_median) and np.isfinite(post_median):
        return post_median - pre_median
    else:
        return np.nan


def _compute_peak_slope(timestamp: np.ndarray, mass: np.ndarray, window: int = 5) -> float:
    """Compute maximum positive slope estimate.
    
    Args:
        timestamp: Time array for event
        mass: Mass array for event
        window: Window size for slope estimation
        
    Returns:
        Peak positive slope in g/s
    """
    if len(mass) < window + 1:
        return 0.0
    
    slopes = []
    
    for i in range(window, len(mass)):
        window_m = mass[i-window:i+1]
        window_t = timestamp[i-window:i+1]
        
        # Only compute if most samples valid
        if np.sum(np.isfinite(window_m)) >= window * 0.8:
            # Use finite differences
            valid_mask = np.isfinite(window_m)
            if np.sum(valid_mask) >= 2:
                dt = np.diff(window_t[valid_mask])
                dm = np.diff(window_m[valid_mask])
                
                if len(dt) > 0 and np.all(dt > 0):
                    slope = np.nanmean(dm / dt)
                    if np.isfinite(slope) and slope > 0:
                        slopes.append(slope)
    
    if slopes:
        return float(np.max(slopes))
    else:
        return 0.0


def _compute_mean_slope(timestamp: np.ndarray, mass: np.ndarray, 
                        delta_mass_g: float, duration_s: float) -> float:
    """Compute mean slope for overall behavior assessment.
    
    This complements peak_slope by providing a measure of the overall
    rate of mass change throughout the event.
    
    Args:
        timestamp: Time array for event
        mass: Mass array for event
        delta_mass_g: Net mass change (already computed)
        duration_s: Event duration (already computed)
        
    Returns:
        Mean slope in g/s
    """
    # Simple approach: use delta_mass / duration for overall slope
    if duration_s > 0 and np.isfinite(delta_mass_g):
        return delta_mass_g / duration_s
    
    # Fallback: compute from valid sample differences
    if len(mass) < 2 or len(timestamp) < 2:
        return 0.0
    
    # Get valid (finite) samples
    valid_mask = np.isfinite(mass)
    if np.sum(valid_mask) < 2:
        return 0.0
    
    valid_mass = mass[valid_mask]
    valid_time = timestamp[valid_mask]
    
    # Compute overall slope using linear regression or simple difference
    if len(valid_mass) >= 2:
        # Simple approach: (end - start) / (time_end - time_start)
        slope = (valid_mass[-1] - valid_mass[0]) / (valid_time[-1] - valid_time[0])
        return float(slope) if np.isfinite(slope) else 0.0
    
    return 0.0


def _compute_oscillation_score(mass: np.ndarray, window: int = 5) -> float:
    """Compute oscillation score based on sign changes in slope.
    
    More oscillations → higher score (may indicate artifact or animal movement)
    
    Args:
        mass: Mass array for event
        window: Window for slope estimation
        
    Returns:
        Oscillation score (normalized by event length)
    """
    if len(mass) < window + 1:
        return 0.0
    
    # Compute slopes
    slopes = []
    for i in range(window, len(mass)):
        window_m = mass[i-window:i+1]
        if np.sum(np.isfinite(window_m)) >= window * 0.5:
            slope = np.nanmean(np.diff(window_m))
            if np.isfinite(slope):
                slopes.append(slope)
    
    if len(slopes) < 2:
        return 0.0
    
    # Count sign changes
    slopes_arr = np.array(slopes)
    sign_changes = np.sum(np.diff(np.sign(slopes_arr)) != 0)
    
    # Normalize by number of windows
    oscillation_score = sign_changes / len(slopes)
    
    return float(oscillation_score)


def recompute_features_for_event(event: Event,
                                 timestamp: np.ndarray,
                                 mass: np.ndarray,
                                 segments: List[Segment]):
    """Recompute features for a single event (after boundary edit).
    
    Args:
        event: Event object to update (modified in place)
        timestamp: Full time array
        mass: Full mass array
        segments: List of Segment objects
    """
    event.features = compute_event_features(event, timestamp, mass, segments)
    
    # Update needs_manual flag
    if event.features.crosses_gap:
        event.needs_manual = True
    else:
        event.needs_manual = False
    
    # Update modified timestamp
    event.update_modified()


def get_feature_summary_stats(events: List[Event]) -> dict:
    """Compute summary statistics across all events.
    
    Useful for understanding dataset characteristics.
    
    Args:
        events: List of Event objects with computed features
        
    Returns:
        Dictionary with summary statistics
    """
    # Filter events with valid features
    valid_events = [e for e in events if e.features is not None and not e.features.crosses_gap]
    
    if not valid_events:
        return {}
    
    # Extract feature arrays
    durations = [e.features.duration_s for e in valid_events]
    deltas = [e.features.delta_mass_g for e in valid_events]
    slopes = [e.features.peak_slope_g_per_s for e in valid_events]
    
    stats = {
        'n_events': len(events),
        'n_valid': len(valid_events),
        'n_crosses_gap': sum(1 for e in events if e.features and e.features.crosses_gap),
        'duration_mean_s': np.mean(durations),
        'duration_std_s': np.std(durations),
        'duration_median_s': np.median(durations),
        'delta_mass_mean_g': np.mean(deltas),
        'delta_mass_std_g': np.std(deltas),
        'delta_mass_median_g': np.median(deltas),
        'slope_mean_g_per_s': np.mean(slopes),
        'slope_max_g_per_s': np.max(slopes),
    }
    
    return stats


def classify_event_heuristic(event: Event,
                             urine_min_mass_g: float = 0.1,
                             feces_min_mass_g: float = 0.05,
                             slope_ratio_threshold: float = 2.5,
                             oscillation_threshold: float = 0.5) -> str:
    """Apply heuristic classification to an event based on size, duration, and shape.
    
    This is a deterministic rule-based classifier using thresholds.
    NOT machine learning. Results should be reviewed manually.
    
    Key insight:
    - URINE: Usually a larger or more sustained mass increase. Some urine events
             contain a sharp local slope, so size/duration are checked before the
             slope-ratio fallback.
    - FECES: Usually a short, sharp step with smaller-to-moderate mass gain.
    
    The slope_ratio is computed as: peak_slope * duration / delta_mass
    - For urine (slow ramp): low peak slope, so ratio is lower
    - For feces (sudden jump): high peak slope concentrated in short time, ratio is higher
    
    Args:
        event: Event with computed features
        urine_min_mass_g: Minimum mass change for urine classification
        feces_min_mass_g: Minimum mass change for feces classification
        slope_ratio_threshold: Threshold for distinguishing ramp vs jump
                              Below = urine (ramp), Above = feces (jump)
        oscillation_threshold: Above this, event is likely artifact
        
    Returns:
        Label string: "urine", "feces", or "" (unlabeled/uncertain)
    """
    if event.features is None:
        print(f"  Event {event.event_id[:8]}: No features computed")
        return ""
    
    features = event.features
    delta_mass = features.delta_mass_g
    duration = features.duration_s
    peak_slope = features.peak_slope_g_per_s
    
    # Compute slope ratio: how "jumpy" is the mass change?
    # Higher ratio = more sudden change (feces), Lower ratio = gradual ramp (urine)
    if delta_mass > 0 and duration > 0:
        # Normalized slope: peak_slope relative to average slope
        avg_slope = delta_mass / duration
        slope_ratio = peak_slope / avg_slope if avg_slope > 0 else 0
    else:
        slope_ratio = 0
    
    print(f"  Event {event.event_id[:8]}: delta_mass={delta_mass:.3f}g, duration={duration:.1f}s, "
          f"peak_slope={peak_slope:.4f}g/s, slope_ratio={slope_ratio:.2f}, "
          f"oscillation={features.oscillation_score:.3f}")
    
    # Very high oscillation suggests artifact/noise - don't auto-classify
    if features.oscillation_score > oscillation_threshold:
        print(f"    -> Skipped: high oscillation ({features.oscillation_score:.3f})")
        return ""
    
    # Negative or zero mass change - don't classify
    if delta_mass <= 0:
        print(f"    -> Skipped: non-positive mass change")
        return ""

    # Strong urine cues. These are intentionally checked before slope_ratio:
    # longer/larger urine events can contain a brief high-slope burst that would
    # otherwise look feces-like if the ratio were used alone.
    large_urine_mass_g = max(0.75, urine_min_mass_g * 3.0)
    sustained_urine_duration_s = 2.25
    if delta_mass >= large_urine_mass_g:
        print(f"    -> Classified as URINE (large mass gain {delta_mass:.3f}g)")
        return "urine"

    if delta_mass >= urine_min_mass_g and duration >= sustained_urine_duration_s:
        print(f"    -> Classified as URINE (sustained event {duration:.2f}s)")
        return "urine"

    # Strong feces cue. Short, sharp moderate-mass steps can have a deceptively
    # low slope_ratio because the whole event window is brief.
    short_feces_duration_s = 1.50
    feces_max_mass_g = 0.65
    sharp_feces_peak_slope_g_s = 0.80
    if (
        delta_mass >= feces_min_mass_g
        and delta_mass <= feces_max_mass_g
        and duration <= short_feces_duration_s
        and peak_slope >= sharp_feces_peak_slope_g_s
    ):
        print(f"    -> Classified as FECES (short sharp step)")
        return "feces"
    
    # Classification based on slope pattern
    # FECES: Sudden jump - high slope ratio (peak slope much higher than average)
    if delta_mass >= feces_min_mass_g and slope_ratio >= slope_ratio_threshold:
        print(f"    -> Classified as FECES (sudden jump, slope_ratio={slope_ratio:.2f})")
        return "feces"
    
    # URINE: Gradual ramp - lower slope ratio (more uniform increase)
    if delta_mass >= urine_min_mass_g and slope_ratio < slope_ratio_threshold:
        print(f"    -> Classified as URINE (gradual ramp, slope_ratio={slope_ratio:.2f})")
        return "urine"
    
    # Very small mass changes - likely feces if it's a jump
    if delta_mass < urine_min_mass_g and delta_mass >= feces_min_mass_g:
        print(f"    -> Classified as FECES (small mass change)")
        return "feces"
    
    # Uncertain - leave unlabeled for manual review
    print(f"    -> Uncertain, leaving unlabeled")
    return ""


def auto_classify_events(events: List[Event],
                         urine_min_mass_g: float = 0.1,
                         feces_min_mass_g: float = 0.05,
                         slope_ratio_threshold: float = 2.5) -> List[Event]:
    """Apply heuristic classification to all events based on slope pattern.
    
    Only classifies events that don't already have a user label.
    Sets needs_manual=True for uncertain events.
    
    Classification logic:
    - URINE: Gradual ramp-like mass increase (low slope ratio)
    - FECES: Sudden jump in mass (high slope ratio)
    
    Args:
        events: List of events with computed features
        urine_min_mass_g: Minimum mass change for urine
        feces_min_mass_g: Minimum mass change for feces
        slope_ratio_threshold: Threshold for ramp vs jump classification
        
    Returns:
        Same list of events with label_user populated where confident
    """
    print(f"\n=== AUTO-CLASSIFICATION ===")
    print(f"Classifying {len(events)} events...")
    print(f"Logic: URINE=gradual ramp (slope_ratio<{slope_ratio_threshold}), "
          f"FECES=sudden jump (slope_ratio>={slope_ratio_threshold})")
    
    n_urine = 0
    n_feces = 0
    n_unlabeled = 0
    
    for event in events:
        # Skip if already labeled by user
        if event.label_user:
            print(f"  Event {event.event_id[:8]}: Already labeled as '{event.label_user}'")
            continue
        
        # Apply heuristic classification
        label = classify_event_heuristic(
            event,
            urine_min_mass_g=urine_min_mass_g,
            feces_min_mass_g=feces_min_mass_g,
            slope_ratio_threshold=slope_ratio_threshold
        )
        
        if label:
            event.label_user = label
            if label == "urine":
                n_urine += 1
            else:
                n_feces += 1
        else:
            # Couldn't classify confidently - flag for manual review
            event.needs_manual = True
            n_unlabeled += 1
    
    print(f"Classification complete: {n_urine} urine, {n_feces} feces, {n_unlabeled} unlabeled")
    print(f"===========================\n")
    
    return events
