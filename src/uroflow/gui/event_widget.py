"""Integrated event management widget with table, filters, and navigation."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableView, QLabel, QCheckBox, QComboBox, QLineEdit, QApplication
)
from PySide6.QtCore import Signal, Qt

from uroflow.gui.table_model import EventTableModel, EventFilterProxyModel
from uroflow.gui.label_delegate import LabelDelegate


class EventWidget(QWidget):
    """Widget for event table with filtering and navigation."""
    
    event_selected = Signal(str)  # event_id
    next_event_requested = Signal()
    prev_event_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.table_model = EventTableModel()
        self.proxy_model = EventFilterProxyModel()
        self.proxy_model.setSourceModel(self.table_model)
        self.metadata = None
        
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
        
        layout.addWidget(self.table_view)
        
        # Navigation buttons
        nav_layout = QHBoxLayout()
        
        self.prev_button = QPushButton("← Previous")
        self.prev_button.clicked.connect(self.prev_event_requested.emit)
        nav_layout.addWidget(self.prev_button)
        
        self.next_button = QPushButton("Next →")
        self.next_button.clicked.connect(self.next_event_requested.emit)
        nav_layout.addWidget(self.next_button)
        
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
    
    
    def _on_filter_changed(self):
        """Handle filter control changes."""
        self.proxy_model.set_filter_unlabeled(self.unlabeled_checkbox.isChecked())
        self.proxy_model.set_filter_needs_manual(self.needs_manual_checkbox.isChecked())
        
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
