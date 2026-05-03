"""Table model for displaying and managing events."""

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QColor
from typing import List, Optional

from uroflow.core.types import Event


class EventTableModel(QAbstractTableModel):
    """Table model for event list."""
    
    # Column indices
    COL_ID = 0
    COL_START_TIME = 1
    COL_WALL_CLOCK_TIME = 2
    COL_DURATION = 3
    COL_DELTA_MASS = 4
    COL_LABEL = 5
    COL_SOURCE = 6
    COL_LOCKED = 7
    
    HEADERS = [
        "ID", "Start (s)", "Wall Clock Time", "Duration (s)", "Δ Mass (g)",
        "Label", "Source", "Locked"
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.events: List[Event] = []
        self.metadata = None  # Metadata dict with wall_clock_time array
    
    def set_events(self, events: List[Event], metadata: dict = None):
        """Set event list and refresh model.
        
        Args:
            events: List of Event objects
            metadata: Optional metadata dict with wall_clock_time array
        """
        self.beginResetModel()
        self.events = events
        self.metadata = metadata
        self.endResetModel()
    
    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of rows."""
        if parent.isValid():
            return 0
        return len(self.events)
    
    def columnCount(self, parent=QModelIndex()) -> int:
        """Return number of columns."""
        return len(self.HEADERS)
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        """Return header data."""
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None
    
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        """Return data for cell."""
        if not index.isValid() or not (0 <= index.row() < len(self.events)):
            return None
        
        event = self.events[index.row()]
        col = index.column()
        
        if role == Qt.DisplayRole:
            return self._get_display_data(event, col)
        
        elif role == Qt.CheckStateRole:
            # Show checkbox for Locked column
            if col == self.COL_LOCKED:
                return Qt.Checked if event.locked else Qt.Unchecked
            return None
        
        elif role == Qt.BackgroundRole:
            return self._get_background_color(event, col)
        
        elif role == Qt.ForegroundRole:
            return self._get_foreground_color(event, col)
        
        elif role == Qt.TextAlignmentRole:
            if col in [self.COL_START_TIME, self.COL_DURATION, self.COL_DELTA_MASS]:
                return Qt.AlignRight | Qt.AlignVCenter
            elif col == self.COL_WALL_CLOCK_TIME:
                return Qt.AlignLeft | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        
        elif role == Qt.UserRole:
            # Store event object for easy access
            return event
        
        return None
    
    def _get_display_data(self, event: Event, col: int):
        """Get display string for cell."""
        if col == self.COL_ID:
            # Show sequential number based on position in sorted list
            return str(self.events.index(event) + 1)
        
        elif col == self.COL_START_TIME:
            return f"{event.start_time_s:.1f}"
        
        elif col == self.COL_WALL_CLOCK_TIME:
            # Get wall clock time from metadata if available
            # Use start_time_s to find the original timestamp in CSV
            if self.metadata and 'wall_clock_time' in self.metadata:
                wall_clock_times = self.metadata['wall_clock_time']
                # Find the index in original timestamp array that corresponds to this time
                # This stays constant even when event boundaries are edited
                if hasattr(self.metadata, 'get') and 'timestamp' in self.metadata:
                    timestamp = self.metadata['timestamp']
                    # Find closest timestamp to event.start_time_s
                    import numpy as np
                    idx = np.searchsorted(timestamp, event.start_time_s)
                    idx = min(idx, len(wall_clock_times) - 1)
                    if idx < len(wall_clock_times):
                        return str(wall_clock_times[idx])
                elif event.start_idx < len(wall_clock_times):
                    # Fallback: use start_idx if timestamp not available
                    return str(wall_clock_times[event.start_idx])
            return "-"
        
        elif col == self.COL_DURATION:
            return f"{event.duration_s():.2f}"
        
        elif col == self.COL_DELTA_MASS:
            if event.features and event.features.delta_mass_g is not None:
                return f"{event.features.delta_mass_g:.3f}"
            return "-"
        
        elif col == self.COL_LABEL:
            return event.label_user if event.label_user else "(unlabeled)"
        
        elif col == self.COL_SOURCE:
            return event.source
        
        elif col == self.COL_LOCKED:
            return "Yes" if event.locked else "No"
        
        return ""
    
    def _get_background_color(self, event: Event, col: int) -> Optional[QColor]:
        """Get background color for cell."""
        # Highlight by label - high-contrast colors
        if col == self.COL_LABEL:
            if event.label_user == "urine":
                return QColor(255, 220, 150, 120)  # Light amber/orange
            elif event.label_user == "feces":
                return QColor(160, 120, 80, 120)  # Light brown
            elif event.label_user == "bad":
                return QColor(255, 182, 193, 100)  # Light red
            else:
                return QColor(245, 245, 245)  # Light gray for unlabeled
        
        # Highlight needs_manual rows (kept for internal use)
        if event.needs_manual:
            return QColor(255, 255, 200, 50)  # Very light yellow
        
        return None
    
    def _get_foreground_color(self, event: Event, col: int) -> Optional[QColor]:
        """Get text color for cell."""
        if col == self.COL_LABEL and not event.label_user:
            return QColor(150, 150, 150)  # Gray for unlabeled
        
        return None
    
    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        """Return item flags."""
        if not index.isValid():
            return Qt.NoItemFlags
        
        # All cells are selectable and enabled
        # Label and Locked columns are editable
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        
        if index.column() == self.COL_LABEL:
            flags |= Qt.ItemIsEditable
        elif index.column() == self.COL_LOCKED:
            flags |= Qt.ItemIsEditable | Qt.ItemIsUserCheckable
        
        return flags
    
    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        """Set data for cell (for editable columns)."""
        if not index.isValid() or not (0 <= index.row() < len(self.events)):
            return False
        
        event = self.events[index.row()]
        col = index.column()
        
        if col == self.COL_LABEL:
            if role != Qt.EditRole:
                return False
            # Validate label
            valid_labels = ["", "urine", "feces", "bad"]
            if value.lower() in valid_labels:
                event.label_user = value.lower()
                event.update_modified()
                self.dataChanged.emit(index, index)
                return True
        
        elif col == self.COL_LOCKED:
            # Handle both checkbox toggle and direct value setting
            if role == Qt.CheckStateRole:
                event.locked = (value == Qt.Checked)
            elif role == Qt.EditRole:
                # Allow text input: "Yes"/"No" or boolean
                if isinstance(value, bool):
                    event.locked = value
                elif isinstance(value, str):
                    event.locked = value.lower() in ['yes', 'true', '1']
                else:
                    return False
            else:
                return False
            
            event.update_modified()
            self.dataChanged.emit(index, index)
            return True
        
        return False
    
    def get_event_at_row(self, row: int) -> Optional[Event]:
        """Get event at row index.
        
        Args:
            row: Row index
            
        Returns:
            Event object or None
        """
        if 0 <= row < len(self.events):
            return self.events[row]
        return None
    
    def find_event_row(self, event_id: str) -> int:
        """Find row index for event ID.
        
        Args:
            event_id: Event ID to find
            
        Returns:
            Row index or -1 if not found
        """
        for i, event in enumerate(self.events):
            if event.event_id == event_id:
                return i
        return -1
    
    def update_event(self, event_id: str):
        """Trigger update for a specific event.
        
        Args:
            event_id: Event ID to update
        """
        row = self.find_event_row(event_id)
        if row >= 0:
            left = self.index(row, 0)
            right = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(left, right)
    
    def remove_event(self, event_id: str) -> bool:
        """Remove event from model.
        
        Args:
            event_id: Event ID to remove
            
        Returns:
            True if removed, False if not found
        """
        row = self.find_event_row(event_id)
        if row >= 0:
            self.beginRemoveRows(QModelIndex(), row, row)
            del self.events[row]
            self.endRemoveRows()
            return True
        return False
    
    def add_event(self, event: Event):
        """Add new event to model.
        
        Args:
            event: Event object to add
        """
        row = len(self.events)
        self.beginInsertRows(QModelIndex(), row, row)
        self.events.append(event)
        self.endInsertRows()


class EventFilterProxyModel(QSortFilterProxyModel):
    """Proxy model for filtering and sorting events."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.filter_unlabeled = False
        self.filter_needs_manual = False
        self.filter_label = None  # None or "urine"/"feces"/"bad"
        
        self.setSortRole(Qt.DisplayRole)
        self.setFilterRole(Qt.UserRole)
    
    def set_filter_unlabeled(self, enabled: bool):
        """Filter to show only unlabeled events.
        
        Args:
            enabled: True to show only unlabeled
        """
        self.filter_unlabeled = enabled
        self.invalidateFilter()
    
    def set_filter_needs_manual(self, enabled: bool):
        """Filter to show only events needing manual review.
        
        Args:
            enabled: True to show only needs_manual
        """
        self.filter_needs_manual = enabled
        self.invalidateFilter()
    
    def set_filter_label(self, label: Optional[str]):
        """Filter by label.
        
        Args:
            label: Label to filter by ("urine"/"feces"/"bad") or None for all
        """
        self.filter_label = label
        self.invalidateFilter()
    
    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        """Check if row should be shown.
        
        Args:
            source_row: Row index in source model
            source_parent: Parent index
            
        Returns:
            True if row should be shown
        """
        source_model = self.sourceModel()
        if not source_model:
            return True
        
        # Get event
        event = source_model.get_event_at_row(source_row)
        if not event:
            return True
        
        # Apply filters
        if self.filter_unlabeled and event.is_labeled():
            return False
        
        if self.filter_needs_manual and not event.needs_manual:
            return False
        
        if self.filter_label and event.label_user != self.filter_label:
            return False
        
        return True
    
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """Compare two items for sorting.
        
        Args:
            left: Left index
            right: Right index
            
        Returns:
            True if left < right
        """
        left_data = self.sourceModel().data(left, Qt.DisplayRole)
        right_data = self.sourceModel().data(right, Qt.DisplayRole)
        
        # Handle numeric columns
        try:
            left_num = float(left_data)
            right_num = float(right_data)
            return left_num < right_num
        except (ValueError, TypeError):
            pass
        
        # String comparison
        return str(left_data) < str(right_data)
