"""Core data types and structures for uroflow analysis."""

from dataclasses import dataclass, field
from typing import Optional, Literal, Tuple
from datetime import datetime
import numpy as np


EventSource = Literal["auto", "acquisition", "manual"]
EventLabel = Literal["urine", "feces", "bad", ""]


@dataclass
class Segment:
    """Represents a contiguous span of valid data samples.
    
    Segments are identified by having:
    - All samples with finite mass values
    - Continuous timestamps (no large gaps)
    """
    start_idx: int  # Inclusive
    end_idx: int    # Exclusive
    
    def __len__(self) -> int:
        return self.end_idx - self.start_idx
    
    def contains(self, idx: int) -> bool:
        """Check if an index is within this segment."""
        return self.start_idx <= idx < self.end_idx


@dataclass
class Gap:
    """Represents a gap in the data (missing or invalid samples)."""
    start_idx: int  # Inclusive
    end_idx: int    # Exclusive
    
    def __len__(self) -> int:
        return self.end_idx - self.start_idx


@dataclass
class DetectionParams:
    """Parameters for auto-detection algorithm.
    
    These control how events are detected within segments.
    """
    diff_test_time_s: float     # Rolling window duration for delta computation (seconds)
    threshold_g: float           # Minimum mass change to trigger detection (grams)
    min_event_len_s: float       # Minimum event duration (seconds)
    max_event_len_s: float       # Maximum event duration (seconds) - filters out long artifacts
    min_gap_merge_s: float       # Maximum gap to merge between events (seconds)
    min_valid_frac: float        # Minimum fraction of valid samples in rolling window
    
    @classmethod
    def from_session_config(cls, config: dict) -> 'DetectionParams':
        """Create detection parameters from session_config.json as reference.
        
        Args:
            config: Session configuration dictionary
            
        Returns:
            DetectionParams with values from config or defaults
        """
        snap = config.get('config_snapshot', {})
        return cls(
            diff_test_time_s=snap.get('diff_test_time', 5.0),
            threshold_g=snap.get('threshold', 0.05),
            min_event_len_s=2.0,  # defaults
            max_event_len_s=30.0,  # default max duration 30 seconds
            min_gap_merge_s=1.0,
            min_valid_frac=0.8
        )
    
    @classmethod
    def default(cls) -> 'DetectionParams':
        """Create default detection parameters."""
        return cls(
            diff_test_time_s=5.0,
            threshold_g=0.05,
            min_event_len_s=2.0,
            max_event_len_s=30.0,  # default max duration 30 seconds
            min_gap_merge_s=1.0,
            min_valid_frac=0.8
        )


@dataclass
class SpatialCoordinates:
    """Spatial location of an event in both image and real-world coordinates."""
    image_x: float  # Pixel x in video frame
    image_y: float  # Pixel y in video frame
    real_x_cm: float  # x in circular cage coordinate system (origin = center)
    real_y_cm: float  # y in circular cage coordinate system

    @property
    def radius_cm(self) -> float:
        """Distance from cage center in cm."""
        return float(np.sqrt(self.real_x_cm**2 + self.real_y_cm**2))

    @property
    def theta_deg(self) -> float:
        """Angle in degrees from positive x-axis, counterclockwise [0, 360)."""
        return float(np.degrees(np.arctan2(self.real_y_cm, self.real_x_cm)) % 360.0)

    def to_dict(self) -> dict:
        return {
            "image_x": self.image_x,
            "image_y": self.image_y,
            "real_x_cm": self.real_x_cm,
            "real_y_cm": self.real_y_cm,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpatialCoordinates":
        return cls(
            image_x=d["image_x"],
            image_y=d["image_y"],
            real_x_cm=d["real_x_cm"],
            real_y_cm=d["real_y_cm"],
        )


@dataclass
class EventFeatures:
    """Computed features for an event (for triage, not classification)."""
    duration_s: float              # Event duration in seconds
    delta_mass_g: float            # Net mass change (post - pre)
    peak_slope_g_per_s: float      # Maximum positive slope (sharpness)
    mean_slope_g_per_s: float      # Mean slope (overall behavior)
    oscillation_score: float       # Sign changes in slope (normalized)
    crosses_gap: bool              # True if event spans a data gap
    
    def __post_init__(self):
        """Validate that all values are finite (except when crosses_gap=True)."""
        import numpy as np
        if self.crosses_gap:
            return
        # Check for NaN values when not crossing gap
        for attr in ['duration_s', 'delta_mass_g', 'peak_slope_g_per_s', 'mean_slope_g_per_s',
                     'oscillation_score']:
            val = getattr(self, attr)
            if not np.isfinite(val):
                raise ValueError(f"Feature {attr} is not finite: {val}")


@dataclass
class Event:
    """Represents a detected or manually created event.
    
    Events are the fundamental unit of analysis - representing a potential
    urine, feces, or artifact event in the time series.
    """
    # Core identification
    event_id: str                          # Unique identifier
    start_idx: int                         # Start sample index (inclusive)
    end_idx: int                           # End sample index (exclusive)
    start_time_s: float                    # Start time in seconds since session start
    end_time_s: float                      # End time in seconds since session start
    
    # Source and provenance
    source: EventSource = "auto"           # How event was created
    locked: bool = False                   # If True, protected from overlap resolution
    
    # User labels
    label_user: EventLabel = ""            # User-assigned label (empty = unlabeled)
    notes: str = ""                        # Optional user notes
    
    # Computed features
    features: Optional[EventFeatures] = None
    needs_manual: bool = False             # True if crosses gap or other quality issues
    
    # Wall clock string from CSV row at event creation (not updated when boundaries move)
    wall_clock_time: str = ""
    
    # Spatial location annotation
    spatial_coords: Optional[SpatialCoordinates] = None
    
    # Timestamps for tracking edits
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    modified_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def duration_s(self) -> float:
        """Get event duration in seconds."""
        return self.end_time_s - self.start_time_s
    
    def overlaps_with(self, other: 'Event') -> bool:
        """Check if this event overlaps with another event."""
        return not (self.end_idx <= other.start_idx or other.end_idx <= self.start_idx)
    
    def contains_time(self, time_s: float) -> bool:
        """Check if a time point is within this event."""
        return self.start_time_s <= time_s < self.end_time_s
    
    def contains_idx(self, idx: int) -> bool:
        """Check if a sample index is within this event."""
        return self.start_idx <= idx < self.end_idx
    
    def is_labeled(self) -> bool:
        """Check if event has a user label."""
        return self.label_user != ""
    
    def update_modified(self):
        """Update the modified timestamp."""
        self.modified_at = datetime.now().isoformat()


@dataclass
class Project:
    """Complete project state for saving/loading analysis sessions.
    
    This contains everything needed to resume analysis without recomputing.
    """
    # Input data paths
    input_csv_path: str
    session_config_path: str
    session_config_snapshot: dict  # Read-only copy for reference
    
    # Detection parameters (used for this analysis)
    detection_params: DetectionParams
    
    # Events (auto-detected + manual + edited)
    events: list[Event] = field(default_factory=list)
    
    # Video folder path (optional)
    video_folder_path: Optional[str] = None
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def update_modified(self):
        """Update the last modified timestamp."""
        self.last_modified = datetime.now().isoformat()
    
    def get_event_by_id(self, event_id: str) -> Optional[Event]:
        """Find an event by its ID."""
        for event in self.events:
            if event.event_id == event_id:
                return event
        return None
    
    def get_unlabeled_events(self) -> list[Event]:
        """Get all events without user labels."""
        return [e for e in self.events if not e.is_labeled()]
    
    def get_events_by_label(self, label: EventLabel) -> list[Event]:
        """Get all events with a specific label."""
        return [e for e in self.events if e.label_user == label]
    
    def sort_events_by_time(self):
        """Sort events by start time in place."""
        self.events.sort(key=lambda e: e.start_time_s)
    
    def get_human_friendly_id(self, event: Event) -> str:
        """Get human-friendly ID for an event based on its position in the sorted list.
        
        Args:
            event: Event object
            
        Returns:
            Human-friendly ID like 'E001', 'E002', etc.
        """
        try:
            event_number = self.events.index(event) + 1
            return f"E{event_number:03d}"
        except ValueError:
            return "E???"


def get_human_friendly_id(event: Event, sorted_events: list[Event]) -> str:
    """Get human-friendly ID for an event based on its position in a sorted events list.
    
    Args:
        event: Event object
        sorted_events: List of events sorted by start time
        
    Returns:
        Human-friendly ID like 'E001', 'E002', etc.
    """
    try:
        event_number = sorted_events.index(event) + 1
        return f"E{event_number:03d}"
    except ValueError:
        return "E???"
