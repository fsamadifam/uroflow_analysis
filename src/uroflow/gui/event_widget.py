"""Integrated event management widget with table, filters, and navigation."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableView, QLabel, QCheckBox, QComboBox, QLineEdit, QApplication,
    QMessageBox, QMenu
)
from PySide6.QtCore import Signal, Qt
from typing import Optional

from uroflow.gui.table_model import EventTableModel, EventFilterProxyModel
from uroflow.gui.label_delegate import LabelDelegate
from uroflow.core.video import (
    get_video_files, find_matching_videos, open_video_file
)


class EventWidget(QWidget):
    """Widget for event table with filtering and navigation."""
    
    event_selected = Signal(str)  # event_id
    event_double_clicked = Signal(str)  # event_id - for centering view
    next_event_requested = Signal()
    prev_event_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.table_model = EventTableModel()
        self.proxy_model = EventFilterProxyModel()
        self.proxy_model.setSourceModel(self.table_model)
        self.metadata = None
        
        # Video folder and config for video matching
        self.video_folder_path: Optional[str] = None
        self.session_config: Optional[dict] = None
        self._video_files = []  # Cached list of (path, datetime) tuples
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI layout."""
        layout = QVBoxLayout(self)
        
        # Filter controls
        filter_layout = QHBoxLayout()
        
        self.unlabeled_checkbox = QCheckBox("Unlabeled only")
        self.unlabeled_checkbox.stateChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.unlabeled_checkbox)
        
        self.needs_manual_checkbox = QCheckBox("Needs manual")
        self.needs_manual_checkbox.stateChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.needs_manual_checkbox)
        
        self.needs_location_checkbox = QCheckBox("Needs location")
        self.needs_location_checkbox.stateChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.needs_location_checkbox)
        
        filter_layout.addWidget(QLabel("Label:"))
        self.label_combo = QComboBox()
        self.label_combo.addItems(["All", "Urine", "Feces", "Bad", "Unlabeled"])
        self.label_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.label_combo)
        
        filter_layout.addStretch()
        
        # Search box
        filter_layout.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Event ID or notes...")
        self.search_box.textChanged.connect(self._on_search_changed)
        filter_layout.addWidget(self.search_box)
        
        layout.addLayout(filter_layout)
        
        # Table view
        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setSelectionMode(QTableView.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        
        # Sort by start time (column 1) by default
        self.table_view.sortByColumn(EventTableModel.COL_START_TIME, Qt.AscendingOrder)
        
        # Install label delegate on label column
        self.label_delegate = LabelDelegate(self.table_view)
        label_col = EventTableModel.COL_LABEL
        self.table_view.setItemDelegateForColumn(label_col, self.label_delegate)
        
        # Allow editing with various triggers
        self.table_view.setEditTriggers(
            QTableView.DoubleClicked | QTableView.EditKeyPressed | QTableView.AnyKeyPressed
        )
        
        # Connect single click - will open editor on label column
        self.table_view.clicked.connect(self._on_cell_clicked)
        
        # Connect double click - centers plot view on event
        self.table_view.doubleClicked.connect(self._on_cell_double_clicked)
        
        layout.addWidget(self.table_view)
        
        # Navigation buttons
        nav_layout = QHBoxLayout()
        
        self.prev_button = QPushButton("← Previous")
        self.prev_button.clicked.connect(self.prev_event_requested.emit)
        nav_layout.addWidget(self.prev_button)
        
        self.next_button = QPushButton("Next →")
        self.next_button.clicked.connect(self.next_event_requested.emit)
        nav_layout.addWidget(self.next_button)
        
        nav_layout.addSpacing(20)
        
        # Open Event Video button
        self.video_button = QPushButton("Open Event Video")
        self.video_button.setToolTip("Open video file for the selected event")
        self.video_button.clicked.connect(self._on_open_video_clicked)
        self.video_button.setEnabled(False)  # Disabled until video folder is set
        nav_layout.addWidget(self.video_button)
        
        nav_layout.addStretch()
        
        self.event_count_label = QLabel("0 events")
        nav_layout.addWidget(self.event_count_label)
        
        layout.addLayout(nav_layout)
        
        # Resize columns to contents
        self.table_view.resizeColumnsToContents()
    
    def set_events(self, events: list, metadata: dict = None):
        """Set events in table.
        
        Args:
            events: List of Event objects
            metadata: Optional metadata dict with wall_clock_time array
        """
        self.metadata = metadata
        self.table_model.set_events(events, metadata)
        self.table_view.resizeColumnsToContents()
        self._update_count_label()
    
    def select_event(self, event_id: str):
        """Select event in table by ID.
        
        Args:
            event_id: Event ID to select
        """
        selection_model = None
        try:
            if not event_id:
                return
            
            if not hasattr(self, 'table_view') or self.table_view is None:
                print("  WARNING: table_view not available")
                return
            
            selection_model = self.table_view.selectionModel()
            if not selection_model:
                print("  WARNING: No selection model available")
                return
            
            # Block signals to prevent recursive event selection
            was_blocked = selection_model.signalsBlocked()
            selection_model.blockSignals(True)
            
            try:
                # Find in source model
                row = self.table_model.find_event_row(event_id)
                if row < 0:
                    print(f"  WARNING: Event {event_id[:8]} not found in table model")
                    return
                
                # Map to proxy model
                source_index = self.table_model.index(row, 0)
                if not source_index.isValid():
                    print(f"  WARNING: Invalid source index for row {row}")
                    return
                
                proxy_index = self.proxy_model.mapFromSource(source_index)
                if not proxy_index.isValid():
                    print(f"  WARNING: Event {event_id[:8]} not visible (filtered out)")
                    return
                
                # Select row - wrap in try/except to catch Qt errors
                proxy_row = proxy_index.row()
                proxy_count = self.proxy_model.rowCount()
                
                if 0 <= proxy_row < proxy_count:
                    # Use clearSelection first to avoid Qt state issues
                    self.table_view.clearSelection()
                    QApplication.processEvents()
                    
                    # Then select the row
                    self.table_view.selectRow(proxy_row)
                    QApplication.processEvents()
                    
                    # Finally scroll
                    self.table_view.scrollTo(proxy_index)
                else:
                    print(f"  WARNING: Invalid proxy row {proxy_row} (count={proxy_count})")
                    
            finally:
                # Always restore signal blocking state
                if selection_model:
                    try:
                        selection_model.blockSignals(was_blocked)
                    except:
                        pass
                
        except Exception as e:
            print(f"ERROR in select_event: {e}")
            import traceback
            traceback.print_exc()
            # Make sure signals are unblocked even on error
            if selection_model:
                try:
                    selection_model.blockSignals(False)
                except:
                    pass
    
    def get_selected_event_id(self) -> str:
        """Get currently selected event ID.
        
        Returns:
            Event ID or empty string if none selected
        """
        selection = self.table_view.selectionModel().currentIndex()
        if selection.isValid():
            # Map to source model
            source_index = self.proxy_model.mapToSource(selection)
            event = self.table_model.get_event_at_row(source_index.row())
            if event:
                return event.event_id
        return ""
    
    def _on_cell_clicked(self, index):
        """Handle single click on cell - select event and open editor for label column."""
        try:
            if not index.isValid():
                return
            
            # Map to source model
            source_index = self.proxy_model.mapToSource(index)
            if not source_index.isValid():
                return
            
            event = self.table_model.get_event_at_row(source_index.row())
            if event:
                print(f"Table row clicked: {event.event_id[:8]}")
                self.event_selected.emit(event.event_id)
            
            # Handle checkbox toggle for Locked column
            if source_index.column() == EventTableModel.COL_LOCKED:
                # Toggle the locked state
                # Get current state from source model
                current_state = self.table_model.data(source_index, Qt.CheckStateRole)
                new_state = Qt.Unchecked if current_state == Qt.Checked else Qt.Checked
                # Set data on source model (proxy will automatically update)
                self.table_model.setData(source_index, new_state, Qt.CheckStateRole)
                return
            
            # If clicked on label column, open editor immediately
            if source_index.column() == EventTableModel.COL_LABEL:
                self.table_view.edit(index)
                
        except Exception as e:
            print(f"ERROR in _on_cell_clicked: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_cell_double_clicked(self, index):
        """Handle double click on cell - select event and center plot view."""
        try:
            if not index.isValid():
                return
            
            # Map to source model
            source_index = self.proxy_model.mapToSource(index)
            if not source_index.isValid():
                return
            
            event = self.table_model.get_event_at_row(source_index.row())
            if event:
                print(f"Table row double-clicked: {event.event_id[:8]} - centering view")
                self.event_double_clicked.emit(event.event_id)
            
            # Don't open editor on double-click (except for label column, handled above)
            # The doubleClicked signal is processed after clicked, so label editing
            # will be handled by the edit trigger we set up
                
        except Exception as e:
            print(f"ERROR in _on_cell_double_clicked: {e}")
            import traceback
            traceback.print_exc()
    
    
    def _on_filter_changed(self):
        """Handle filter control changes."""
        self.proxy_model.set_filter_unlabeled(self.unlabeled_checkbox.isChecked())
        self.proxy_model.set_filter_needs_manual(self.needs_manual_checkbox.isChecked())
        self.proxy_model.set_filter_needs_location(self.needs_location_checkbox.isChecked())
        
        # Label filter
        label_text = self.label_combo.currentText().lower()
        if label_text == "all":
            self.proxy_model.set_filter_label(None)
        elif label_text == "unlabeled":
            self.proxy_model.set_filter_label("")
        else:
            self.proxy_model.set_filter_label(label_text)
        
        self._update_count_label()
    
    def _on_search_changed(self, text: str):
        """Handle search text change."""
        self.proxy_model.setFilterFixedString(text)
        self._update_count_label()
    
    def _update_count_label(self):
        """Update event count label."""
        visible_count = self.proxy_model.rowCount()
        total_count = self.table_model.rowCount()
        
        if visible_count == total_count:
            self.event_count_label.setText(f"{total_count} events")
        else:
            self.event_count_label.setText(f"{visible_count} / {total_count} events")
    
    def update_event(self, event_id: str):
        """Trigger refresh for specific event.
        
        Args:
            event_id: Event ID to update
        """
        self.table_model.update_event(event_id)
    
    def remove_event(self, event_id: str):
        """Remove event from table.
        
        Args:
            event_id: Event ID to remove
        """
        self.table_model.remove_event(event_id)
        self._update_count_label()
    
    def add_event(self, event):
        """Add event to table.
        
        Args:
            event: Event object to add
        """
        self.table_model.add_event(event)
        self._update_count_label()
    
    def refresh_table(self):
        """Refresh table to show updated event data."""
        # Force table to refresh all data
        self.table_model.layoutChanged.emit()
    
    def set_video_folder(self, folder_path: Optional[str], session_config: Optional[dict] = None):
        """Set the video folder for event video matching.
        
        Args:
            folder_path: Path to video folder, or None to clear
            session_config: Session config dict with start_date and start_time
        """
        self.video_folder_path = folder_path
        self.session_config = session_config
        
        # Cache video files list
        if folder_path:
            self._video_files = get_video_files(folder_path)
            self.video_button.setEnabled(True)
            self.video_button.setToolTip(f"Open video ({len(self._video_files)} files available)")
        else:
            self._video_files = []
            self.video_button.setEnabled(False)
            self.video_button.setToolTip("No video folder set")
    
    def _on_open_video_clicked(self):
        """Handle Open Event Video button click."""
        # Get selected event
        event_id = self.get_selected_event_id()
        if not event_id:
            QMessageBox.information(self, "No Selection", "Please select an event first.")
            return
        
        # Find the event object
        row = self.table_model.find_event_row(event_id)
        if row < 0:
            return
        
        event = self.table_model.get_event_at_row(row)
        if not event:
            return
        
        self._open_video_for_event(event)
    
    def _open_video_for_event(self, event):
        """Find and open video for the given event.
        
        Args:
            event: Event object to find video for
        """
        if not self.video_folder_path or not self._video_files:
            QMessageBox.information(
                self, "No Videos",
                "No video folder is set.\n\nUse File → Set Video Folder to configure."
            )
            return
        
        if not self.session_config:
            QMessageBox.warning(
                self, "Missing Config",
                "Session config not available for video matching."
            )
            return
        
        # Get session start date/time
        start_date = self.session_config.get('start_date', '')
        start_time = self.session_config.get('start_time', '')
        
        if not start_date or not start_time:
            QMessageBox.warning(
                self, "Missing Config",
                "Session start date/time not found in config."
            )
            return
        
        if not event.wall_clock_time:
            QMessageBox.information(
                self, "No Wall Clock Time",
                "This event has no wall clock time recorded.\n\n"
                "Cannot match to video without timestamp."
            )
            return
        
        # Find matching videos
        # Videos are saved ~5-30 seconds AFTER the event occurs
        matches = find_matching_videos(
            event,
            self._video_files,
            start_date,
            start_time,
            max_delay_after_event_s=60.0,  # Video saved up to 60s after event
            max_time_before_event_s=5.0     # Edge case: video saved slightly before
        )
        
        if not matches:
            QMessageBox.information(
                self, "No Video Found",
                f"No video found near event time: {event.wall_clock_time}\n\n"
                f"Event occurred at {event.wall_clock_time}, but no video\n"
                f"was recorded within the matching window."
            )
            return
        
        if len(matches) == 1:
            # Single match - open immediately
            video_path, video_dt, offset = matches[0]
            success, message = open_video_file(str(video_path))
            if not success:
                QMessageBox.warning(self, "Failed to Open Video", message)
        
        elif len(matches) <= 3:
            # 2-3 matches - show small popup menu
            menu = QMenu(self)
            menu.setTitle("Select Video")
            
            for video_path, video_dt, offset in matches:
                offset_str = f"+{offset:.0f}s" if offset >= 0 else f"{offset:.0f}s"
                action_text = f"{video_path.name} ({offset_str})"
                action = menu.addAction(action_text)
                action.setData(str(video_path))
            
            # Show menu below button
            action = menu.exec_(self.video_button.mapToGlobal(
                self.video_button.rect().bottomLeft()
            ))
            
            if action:
                video_path = action.data()
                success, message = open_video_file(video_path)
                if not success:
                    QMessageBox.warning(self, "Failed to Open Video", message)
        
        else:
            # More than 3 matches - show warning and open first one
            video_path, video_dt, offset = matches[0]
            reply = QMessageBox.question(
                self, "Multiple Videos",
                f"Found {len(matches)} potential videos.\n\n"
                f"Open the closest match?\n{video_path.name}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.Yes:
                success, message = open_video_file(str(video_path))
                if not success:
                    QMessageBox.warning(self, "Failed to Open Video", message)
