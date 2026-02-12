"""Deterministic overlap resolution with priority rules."""

import numpy as np
from typing import List
from uroflow.core.types import Event, EventSource


def resolve_overlaps(events: List[Event]) -> List[Event]:
    """Resolve all overlaps in event list deterministically.
    
    Priority rules:
    1. Manual events (source="manual" or locked=True) always win
    2. Acquisition-flagged events (source="acquisition") have medium priority
    3. Auto-detected events (source="auto") have lowest priority
    
    Resolution strategies:
    - Same-label overlaps → merge boundaries
    - Different-label overlaps → snap boundaries (earlier keeps end, later starts at end)
    
    Args:
        events: List of Event objects (may contain overlaps)
        
    Returns:
        New list of Event objects with all overlaps resolved
        
    Notes:
        - Input list is not modified
        - Output list is sorted by start time
        - No overlaps in output list
    """
    if len(events) <= 1:
        return events.copy()
    
    # Sort by start time
    sorted_events = sorted(events, key=lambda e: e.start_time_s)
    
    resolved = []
    i = 0
    
    while i < len(sorted_events):
        current = sorted_events[i]
        
        # Find all events that overlap with current
        overlapping = []
        j = i + 1
        while j < len(sorted_events):
            if sorted_events[j].start_idx < current.end_idx:
                overlapping.append(sorted_events[j])
                j += 1
            else:
                break  # No more overlaps (sorted by start time)
        
        if not overlapping:
            # No overlaps, keep current event
            resolved.append(current)
            i += 1
        else:
            # Resolve overlap group
            overlap_group = [current] + overlapping
            resolved_group = _resolve_overlap_group(overlap_group)
            resolved.extend(resolved_group)
            i = j  # Skip past all resolved events
    
    return resolved


def _resolve_overlap_group(events: List[Event]) -> List[Event]:
    """Resolve a group of overlapping events.
    
    Args:
        events: List of overlapping Event objects
        
    Returns:
        List of resolved Event objects (no overlaps)
    """
    if len(events) == 1:
        return events
    
    # Sort by priority (highest first)
    sorted_by_priority = sorted(events, key=_event_priority, reverse=True)
    
    resolved = []
    
    for event in sorted_by_priority:
        if not resolved:
            # First (highest priority) event always kept
            resolved.append(event)
        else:
            # Check for overlaps with already resolved events
            has_overlap = False
            
            for prev_event in resolved:
                if event.overlaps_with(prev_event):
                    has_overlap = True
                    
                    # Decide how to handle overlap
                    if event.label_user == prev_event.label_user and event.label_user != "":
                        # Same label: merge (extend prev_event to include this one)
                        merged = _merge_events(prev_event, event)
                        resolved.remove(prev_event)
                        resolved.append(merged)
                        break
                    else:
                        # Different labels or unlabeled: snap boundaries
                        snapped = _snap_boundaries(event, prev_event)
                        if snapped is not None and snapped.end_idx > snapped.start_idx:
                            resolved.append(snapped)
                        break
            
            if not has_overlap:
                # No overlap with resolved events, keep it
                resolved.append(event)
    
    # Sort by start time before returning
    return sorted(resolved, key=lambda e: e.start_time_s)


def _event_priority(event: Event) -> int:
    """Calculate priority score for event (higher = higher priority).
    
    Args:
        event: Event object
        
    Returns:
        Priority score (integer)
    """
    if event.locked:
        return 1000  # Locked events always win
    
    if event.source == "manual":
        return 100  # Manual events high priority
    elif event.source == "acquisition":
        return 50   # Acquisition medium priority
    else:  # "auto"
        return 10   # Auto-detected lowest priority


def _merge_events(event1: Event, event2: Event) -> Event:
    """Merge two events with same label into one.
    
    Takes earliest start and latest end.
    Keeps highest priority source and locked status.
    
    Args:
        event1: First event
        event2: Second event
        
    Returns:
        Merged Event object
    """
    # Find extent
    start_idx = min(event1.start_idx, event2.start_idx)
    end_idx = max(event1.end_idx, event2.end_idx)
    start_time_s = min(event1.start_time_s, event2.start_time_s)
    end_time_s = max(event1.end_time_s, event2.end_time_s)
    
    # Determine source (keep higher priority)
    if _event_priority(event1) >= _event_priority(event2):
        source = event1.source
        locked = event1.locked
        label_user = event1.label_user
        notes = event1.notes
        event_id = event1.event_id
    else:
        source = event2.source
        locked = event2.locked
        label_user = event2.label_user
        notes = event2.notes
        event_id = event2.event_id
    
    # Create merged event
    merged = Event(
        event_id=event_id,
        start_idx=start_idx,
        end_idx=end_idx,
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        source=source,
        locked=locked,
        label_user=label_user,
        notes=notes + f" [merged]",
        features=None,  # Will need recomputation
        needs_manual=True  # Flag for user review
    )
    
    return merged


def _snap_boundaries(lower_priority_event: Event, higher_priority_event: Event) -> Event:
    """Snap boundaries of lower priority event to avoid overlap.
    
    Args:
        lower_priority_event: Event with lower priority (will be trimmed)
        higher_priority_event: Event with higher priority (keeps boundaries)
        
    Returns:
        Trimmed event, or None if completely eliminated
    """
    # Find non-overlapping portion
    if lower_priority_event.start_idx >= higher_priority_event.end_idx:
        # No overlap (shouldn't happen, but handle it)
        return lower_priority_event
    
    if lower_priority_event.end_idx <= higher_priority_event.start_idx:
        # No overlap (shouldn't happen, but handle it)
        return lower_priority_event
    
    # Determine which portion to keep
    # If lower event starts before higher, trim its end
    if lower_priority_event.start_idx < higher_priority_event.start_idx:
        new_end_idx = higher_priority_event.start_idx
        new_end_time_s = higher_priority_event.start_time_s
        
        if new_end_idx > lower_priority_event.start_idx:
            # Create trimmed event
            trimmed = Event(
                event_id=lower_priority_event.event_id,
                start_idx=lower_priority_event.start_idx,
                end_idx=new_end_idx,
                start_time_s=lower_priority_event.start_time_s,
                end_time_s=new_end_time_s,
                source=lower_priority_event.source,
                locked=lower_priority_event.locked,
                label_user=lower_priority_event.label_user,
                notes=lower_priority_event.notes + " [trimmed]",
                features=None,  # Will need recomputation
                needs_manual=True
            )
            return trimmed
        else:
            return None  # Completely eliminated
    else:
        # Lower event starts after higher, trim its start
        new_start_idx = higher_priority_event.end_idx
        new_start_time_s = higher_priority_event.end_time_s
        
        if new_start_idx < lower_priority_event.end_idx:
            # Create trimmed event
            trimmed = Event(
                event_id=lower_priority_event.event_id,
                start_idx=new_start_idx,
                end_idx=lower_priority_event.end_idx,
                start_time_s=new_start_time_s,
                end_time_s=lower_priority_event.end_time_s,
                source=lower_priority_event.source,
                locked=lower_priority_event.locked,
                label_user=lower_priority_event.label_user,
                notes=lower_priority_event.notes + " [trimmed]",
                features=None,  # Will need recomputation
                needs_manual=True
            )
            return trimmed
        else:
            return None  # Completely eliminated


def check_for_overlaps(events: List[Event]) -> List[tuple]:
    """Check for overlaps in event list.
    
    Args:
        events: List of Event objects
        
    Returns:
        List of (event1_index, event2_index) tuples for overlapping pairs
    """
    overlaps = []
    
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            if events[i].overlaps_with(events[j]):
                overlaps.append((i, j))
    
    return overlaps


def remove_duplicates(events: List[Event]) -> List[Event]:
    """Remove duplicate events (same start/end indices).
    
    Keeps highest priority event among duplicates.
    
    Args:
        events: List of Event objects
        
    Returns:
        List with duplicates removed
    """
    if len(events) <= 1:
        return events.copy()
    
    # Group by (start_idx, end_idx)
    groups = {}
    for event in events:
        key = (event.start_idx, event.end_idx)
        if key not in groups:
            groups[key] = []
        groups[key].append(event)
    
    # Keep highest priority from each group
    deduplicated = []
    for group in groups.values():
        if len(group) == 1:
            deduplicated.append(group[0])
        else:
            # Keep highest priority
            best = max(group, key=_event_priority)
            deduplicated.append(best)
    
    return sorted(deduplicated, key=lambda e: e.start_time_s)


def validate_no_overlaps(events: List[Event]) -> bool:
    """Validate that no events overlap.
    
    Args:
        events: List of Event objects
        
    Returns:
        True if no overlaps, False otherwise
    """
    overlaps = check_for_overlaps(events)
    return len(overlaps) == 0
