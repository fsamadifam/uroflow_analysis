"""Action handlers and undo/redo command pattern."""

from abc import ABC, abstractmethod
from typing import Optional, List
from uroflow.core.types import Event, Project, DetectionParams
from uroflow.core.features import recompute_features_for_event


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


class LabelEventCommand(Command):
    """Command to label an event."""
    
    def __init__(self, project: Project, event_id: str, new_label: str):
        self.project = project
        self.event_id = event_id
        self.new_label = new_label
        self.old_label = None
    
    def execute(self):
        """Set event label."""
        event = self.project.get_event_by_id(self.event_id)
        if event:
            self.old_label = event.label_user
            event.label_user = self.new_label
            event.update_modified()
    
    def undo(self):
        """Restore old label."""
        event = self.project.get_event_by_id(self.event_id)
        if event and self.old_label is not None:
            event.label_user = self.old_label
            event.update_modified()
    
    def description(self) -> str:
        return f"Label event as '{self.new_label}'"


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
                break
    
    def undo(self):
        """Restore deleted event."""
        if self.deleted_event and self.event_index is not None:
            self.project.events.insert(self.event_index, self.deleted_event)
    
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
    
    def undo(self):
        """Remove created event."""
        self.project.events.remove(self.event)
    
    def description(self) -> str:
        return f"Create {self.event.source} event"


class EditBoundaryCommand(Command):
    """Command to edit event boundaries."""
    
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
        self.old_start_idx = None
        self.old_end_idx = None
        self.old_start_time = None
        self.old_end_time = None
        self.old_features = None
    
    def execute(self):
        """Update event boundaries and recompute features."""
        event = self.project.get_event_by_id(self.event_id)
        if event:
            # Save old values
            self.old_start_idx = event.start_idx
            self.old_end_idx = event.end_idx
            self.old_start_time = event.start_time_s
            self.old_end_time = event.end_time_s
            self.old_features = event.features
            
            # Set new values
            event.start_idx = self.new_start_idx
            event.end_idx = self.new_end_idx
            event.start_time_s = self.new_start_time
            event.end_time_s = self.new_end_time
            
            # Recompute features
            recompute_features_for_event(event, self.timestamp, self.mass, self.segments)
    
    def undo(self):
        """Restore old boundaries."""
        event = self.project.get_event_by_id(self.event_id)
        if event:
            event.start_idx = self.old_start_idx
            event.end_idx = self.old_end_idx
            event.start_time_s = self.old_start_time
            event.end_time_s = self.old_end_time
            event.features = self.old_features
            event.update_modified()
    
    def description(self) -> str:
        return "Edit event boundaries"


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
