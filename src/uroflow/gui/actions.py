"""Action handlers and undo/redo command pattern."""

from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Optional, List
from uroflow.core.types import Event, Project, DetectionParams
from uroflow.core.features import recompute_features_for_event, auto_classify_events


class Command(ABC):
    """Base class for undoable commands."""
    
    @abstractmethod
    def execute(self):
        """Execute the command."""
        pass
    
    @abstractmethod
    def undo(self):
        """Undo the command."""
        pass
    
    @abstractmethod
    def description(self) -> str:
        """Return command description for UI."""
        pass


class EditEventFieldCommand(Command):
    """Change one review field while retaining its original value for redo."""

    FIELD_DESCRIPTIONS = {
        "label_user": "Label event",
        "locked": "Change event lock",
        "needs_manual": "Change manual review flag",
        "spatial_coords": "Mark event location",
    }

    def __init__(self, project: Project, event_id: str, field: str, value):
        if field not in self.FIELD_DESCRIPTIONS:
            raise ValueError(f"Unsupported review field: {field}")
        self.project = project
        self.event_id = event_id
        self.field = field
        self.value = deepcopy(value)
        self.old_value = None
        self.old_modified_at = None
        self.new_modified_at = None
        self._captured = False
    
    def execute(self):
        """Apply the edit; capture the old value only on the first execution."""
        event = self.project.get_event_by_id(self.event_id)
        if event:
            if not self._captured:
                self.old_value = deepcopy(getattr(event, self.field))
                self.old_modified_at = event.modified_at
                self._captured = True
            setattr(event, self.field, deepcopy(self.value))
            if self.new_modified_at is None:
                event.update_modified()
                self.new_modified_at = event.modified_at
            else:
                event.modified_at = self.new_modified_at
            self.project.update_modified()
    
    def undo(self):
        """Restore the field, including an originally empty or missing value."""
        event = self.project.get_event_by_id(self.event_id)
        if event and self._captured:
            setattr(event, self.field, deepcopy(self.old_value))
            event.modified_at = self.old_modified_at
            self.project.update_modified()
    
    def description(self) -> str:
        return self.FIELD_DESCRIPTIONS[self.field]


class LabelEventCommand(EditEventFieldCommand):
    """Command to label an event."""

    def __init__(self, project: Project, event_id: str, new_label: str):
        super().__init__(project, event_id, "label_user", new_label)

    def description(self) -> str:
        return f"Label event as '{self.value}'"


class DeleteEventCommand(Command):
    """Command to delete an event."""
    
    def __init__(self, project: Project, event_id: str):
        self.project = project
        self.event_id = event_id
        self.deleted_event = None
        self.event_index = None
    
    def execute(self):
        """Remove event from project."""
        for i, event in enumerate(self.project.events):
            if event.event_id == self.event_id:
                self.event_index = i
                self.deleted_event = event
                self.project.events.pop(i)
                self.project.update_modified()
                break
    
    def undo(self):
        """Restore deleted event."""
        if self.deleted_event and self.event_index is not None:
            self.project.events.insert(self.event_index, self.deleted_event)
            self.project.update_modified()
    
    def description(self) -> str:
        return "Delete event"


class CreateEventCommand(Command):
    """Command to create a new manual event."""
    
    def __init__(self, project: Project, event: Event):
        self.project = project
        self.event = event
    
    def execute(self):
        """Add event to project."""
        self.project.events.append(self.event)
        self.project.sort_events_by_time()
        self.project.update_modified()
    
    def undo(self):
        """Remove created event."""
        self.project.events.remove(self.event)
        self.project.update_modified()
    
    def description(self) -> str:
        return f"Create {self.event.source} event"


class EditBoundaryCommand(Command):
    """Command to edit event boundaries."""

    STATE_FIELDS = (
        "start_idx", "end_idx", "start_time_s", "end_time_s",
        "features", "needs_manual", "modified_at",
    )
    
    def __init__(self, project: Project, timestamp, mass, segments,
                 event_id: str, new_start_idx: int, new_end_idx: int,
                 new_start_time: float, new_end_time: float):
        self.project = project
        self.timestamp = timestamp
        self.mass = mass
        self.segments = segments
        self.event_id = event_id
        self.new_start_idx = new_start_idx
        self.new_end_idx = new_end_idx
        self.new_start_time = new_start_time
        self.new_end_time = new_end_time
        self.old_state = None
        self.new_state = None

    def _state(self, event):
        return {field: deepcopy(getattr(event, field)) for field in self.STATE_FIELDS}

    def _restore(self, event, state):
        for field, value in state.items():
            setattr(event, field, deepcopy(value))
        self.project.sort_events_by_time()
        self.project.update_modified()
    
    def execute(self):
        """Update event boundaries and recompute features."""
        event = self.project.get_event_by_id(self.event_id)
        if event:
            if self.new_state is not None:
                self._restore(event, self.new_state)
                return
            self.old_state = self._state(event)
            # Set new values
            event.start_idx = self.new_start_idx
            event.end_idx = self.new_end_idx
            event.start_time_s = self.new_start_time
            event.end_time_s = self.new_end_time
            
            # Recompute features
            recompute_features_for_event(
                event,
                self.timestamp,
                self.mass,
                self.segments,
                baseline_window_s=self.project.detection_params.baseline_window_s,
            )
            # A reviewer may have set this flag explicitly. A new feature
            # calculation must not silently clear that review decision.
            event.needs_manual |= self.old_state["needs_manual"]
            self.new_state = self._state(event)
            self.project.sort_events_by_time()
            self.project.update_modified()
    
    def undo(self):
        """Restore old boundaries."""
        event = self.project.get_event_by_id(self.event_id)
        if event and self.old_state is not None:
            self._restore(event, self.old_state)
    
    def description(self) -> str:
        return "Edit event boundaries"


class ClassifyEventsCommand(Command):
    """Classify the current events as one reversible review action."""

    def __init__(self, project: Project, params: dict):
        self.project = project
        self.params = params.copy()
        self.before = None
        self.after = None

    def _state(self):
        return {
            event.event_id: (event.label_user, event.needs_manual, event.modified_at)
            for event in self.project.events
        }

    def _restore(self, state):
        for event in self.project.events:
            if event.event_id in state:
                event.label_user, event.needs_manual, event.modified_at = state[event.event_id]
        self.project.update_modified()

    def execute(self):
        if self.after is not None:
            self._restore(self.after)
            return
        self.before = self._state()
        auto_classify_events(self.project.events, **self.params)
        for event in self.project.events:
            before = self.before[event.event_id]
            if (event.label_user, event.needs_manual) != before[:2]:
                event.update_modified()
        self.after = self._state()
        self.project.update_modified()

    def undo(self):
        if self.before is not None:
            self._restore(self.before)

    def description(self) -> str:
        return "Classify events"


class DetectEventsCommand(Command):
    """Command to replace project events with detection results.
    
    This command supports undo by storing the previous event list state.
    """
    
    def __init__(self, project: Project, new_events: List[Event],
                 removed_event_ids: List[str] = None,
                 old_params: DetectionParams = None,
                 new_params: DetectionParams = None):
        """Initialize detect events command.
        
        Args:
            project: Project to modify
            new_events: Resolved full event list after detection
            removed_event_ids: List of event IDs that were removed (auto events cleared)
            old_params: Previous detection params (for undo)
            new_params: New detection params used
        """
        self.project = project
        self.new_events = new_events
        self.removed_event_ids = removed_event_ids or []
        self.old_params = old_params
        self.new_params = new_params
        
        # Store previous events for undo
        self.previous_events: List[Event] = []
    
    def execute(self):
        """Apply detected/resolved events to project."""
        self.previous_events = self.project.events.copy()

        # Detection produces a fully resolved event list, including preserved
        # manual/locked events and newly detected events.
        self.project.events = self.new_events.copy()

        # Sort by time
        self.project.sort_events_by_time()
        
        # Update detection params
        if self.new_params:
            self.project.detection_params = self.new_params
        
        self.project.update_modified()
    
    def undo(self):
        """Restore previous event state."""
        self.project.events = self.previous_events.copy()

        # Sort by time
        self.project.sort_events_by_time()
        
        # Restore old params
        if self.old_params:
            self.project.detection_params = self.old_params
        
        self.project.update_modified()
    
    def description(self) -> str:
        return f"Detect events ({len(self.new_events)} total)"


class UndoStack:
    """Undo/redo stack manager."""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.undo_stack = []
        self.redo_stack = []
    
    def push(self, command: Command):
        """Push command onto undo stack and execute it.
        
        Args:
            command: Command to execute
        """
        command.execute()
        self.undo_stack.append(command)
        
        # Clear redo stack when new command is pushed
        self.redo_stack.clear()
        
        # Limit stack size
        if len(self.undo_stack) > self.max_size:
            self.undo_stack.pop(0)
    
    def undo(self) -> Optional[Command]:
        """Undo last command.
        
        Returns:
            Undone command or None if stack empty
        """
        if not self.undo_stack:
            return None
        
        command = self.undo_stack.pop()
        command.undo()
        self.redo_stack.append(command)
        return command
    
    def redo(self) -> Optional[Command]:
        """Redo last undone command.
        
        Returns:
            Redone command or None if stack empty
        """
        if not self.redo_stack:
            return None
        
        command = self.redo_stack.pop()
        command.execute()
        self.undo_stack.append(command)
        return command
    
    def can_undo(self) -> bool:
        """Check if undo is possible."""
        return len(self.undo_stack) > 0
    
    def can_redo(self) -> bool:
        """Check if redo is possible."""
        return len(self.redo_stack) > 0
    
    def clear(self):
        """Clear both stacks."""
        self.undo_stack.clear()
        self.redo_stack.clear()
    
    def get_undo_text(self) -> str:
        """Get description of last undo command."""
        if self.undo_stack:
            return self.undo_stack[-1].description()
        return "Nothing to undo"
    
    def get_redo_text(self) -> str:
        """Get description of last redo command."""
        if self.redo_stack:
            return self.redo_stack[-1].description()
        return "Nothing to redo"
