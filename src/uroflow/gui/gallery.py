"""Event gallery with thumbnail views."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QGridLayout,
    QLabel, QPushButton, QFrame
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor

from uroflow.core.types import Event


class EventThumbWidget(QFrame):
    """Thumbnail widget for a single event."""
    
    clicked = Signal(str)  # event_id
    
    def __init__(self, event: Event, timestamp: np.ndarray, mass: np.ndarray, 
                 padding_s: float = 5.0, parent=None):
        super().__init__(parent)
        
        self.event = event
        self.padding_s = padding_s
        
        self.setFrameStyle(QFrame.Box | QFrame.Plain)
        self.setLineWidth(1)
        self.setFixedSize(200, 150)
        
        self._setup_ui(timestamp, mass)
    
    def _setup_ui(self, timestamp: np.ndarray, mass: np.ndarray):
        """Setup thumbnail plot."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        # Info label
        label_text = f"#{self.event.event_id[:6]}"
        if self.event.label_user:
            label_text += f" | {self.event.label_user}"
        if self.event.features:
            label_text += f" | {self.event.features.delta_mass_g:.2f}g {self.event.duration_s():.1f}s"
        
        info_label = QLabel(label_text)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("font-size: 9px;")
        layout.addWidget(info_label)
        
        # Plot widget (simplified)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.hideAxis('left')
        self.plot_widget.hideAxis('bottom')
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)
        
        # Extract event window
        t_start = max(0, self.event.start_time_s - self.padding_s)
        t_end = self.event.end_time_s + self.padding_s
        
        start_idx = np.searchsorted(timestamp, t_start)
        end_idx = np.searchsorted(timestamp, t_end)
        
        window_t = timestamp[start_idx:end_idx]
        window_m = mass[start_idx:end_idx]
        
        # Plot data
        self.plot_widget.plot(window_t, window_m, pen=pg.mkPen('k', width=1))
        
        # Add start/end markers
        self.plot_widget.addItem(pg.InfiniteLine(
            pos=self.event.start_time_s,
            angle=90,
            pen=pg.mkPen('g', width=2)
        ))
        self.plot_widget.addItem(pg.InfiniteLine(
            pos=self.event.end_time_s,
            angle=90,
            pen=pg.mkPen('r', width=2)
        ))
        
        layout.addWidget(self.plot_widget)
        
        # Set background color by label
        self._update_style()
    
    def _update_style(self):
        """Update widget style based on event state."""
        # Background by label
        if self.event.label_user == "urine":
            color = "lightblue"
        elif self.event.label_user == "feces":
            color = "tan"
        elif self.event.label_user == "bad":
            color = "lightcoral"
        else:
            color = "lightgray"
        
        self.setStyleSheet(f"EventThumbWidget {{ background-color: {color}; }}")
    
    def set_selected(self, selected: bool):
        """Highlight widget as selected.
        
        Args:
            selected: True to highlight
        """
        if selected:
            self.setLineWidth(3)
            self.setStyleSheet(self.styleSheet() + " border: 3px solid blue;")
        else:
            self.setLineWidth(1)
            self._update_style()
    
    def mousePressEvent(self, event):
        """Handle mouse click."""
        self.clicked.emit(self.event.event_id)


class EventGallery(QWidget):
    """Gallery view of all events as thumbnails."""
    
    event_selected = Signal(str)  # event_id
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.timestamp = None
        self.mass = None
        self.events = []
        self.thumb_widgets = []
        self.selected_event_id = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # Container widget for grid
        self.container = QWidget()
        self.grid_layout = QGridLayout(self.container)
        self.grid_layout.setSpacing(5)
        self.grid_layout.setContentsMargins(5, 5, 5, 5)
        
        scroll.setWidget(self.container)
        layout.addWidget(scroll)
    
    def set_data(self, timestamp: np.ndarray, mass: np.ndarray, events: list):
        """Set data and create thumbnails.
        
        Args:
            timestamp: Time array
            mass: Mass array
            events: List of Event objects
        """
        self.timestamp = timestamp
        self.mass = mass
        self.events = events
        
        self._rebuild_gallery()
    
    def _rebuild_gallery(self):
        """Rebuild gallery thumbnails."""
        print(f"  EventGallery._rebuild_gallery: {len(self.events) if self.events else 0} events")
        print(f"    NOTE: Gallery thumbnails temporarily disabled due to performance issues")
        print(f"    Using simple list view instead")
        
        # Clear existing
        for thumb in self.thumb_widgets:
            thumb.deleteLater()
        self.thumb_widgets.clear()
        
        if not self.events or self.timestamp is None:
            print("    No events or timestamp, skipping gallery")
            return
        
        # TEMPORARY: Use simple text labels instead of thumbnails with plots
        # Creating 50+ pyqtgraph PlotWidgets causes crashes
        n_cols = 2
        n_to_show = min(100, len(self.events))
        print(f"    Creating {n_to_show} event labels...")
        
        try:
            for i, event in enumerate(self.events[:n_to_show]):
                # Create simple label widget instead of thumbnail
                label = QLabel()
                label.setFrameStyle(QFrame.Box | QFrame.Plain)
                label.setLineWidth(1)
                label.setFixedHeight(60)
                label.setWordWrap(True)
                label.setStyleSheet("padding: 5px; background-color: white;")
                
                # Event info text
                info_text = f"Event #{i+1}: {event.event_id[:8]}...\n"
                info_text += f"Label: {event.label_user or 'Unlabeled'}\n"
                if event.features:
                    info_text += f"Δmass: {event.features.delta_mass_g:.2f}g, "
                    info_text += f"Duration: {event.duration_s():.1f}s"
                
                label.setText(info_text)
                label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                
                # Make clickable
                label.mousePressEvent = lambda evt, eid=event.event_id: self.event_selected.emit(eid)
                
                row = i // n_cols
                col = i % n_cols
                self.grid_layout.addWidget(label, row, col)
                self.thumb_widgets.append(label)
            
            # Add spacer at end
            self.grid_layout.setRowStretch(len(self.events) // n_cols + 1, 1)
            print(f"    Gallery complete: {len(self.thumb_widgets)} event labels created")
            
        except Exception as e:
            print(f"    ERROR creating event labels: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def highlight_event(self, event_id: str):
        """Highlight a specific event thumbnail.
        
        Args:
            event_id: Event ID to highlight
        """
        self.selected_event_id = event_id
        
        for i, thumb in enumerate(self.thumb_widgets):
            if i >= len(self.events):
                break
            
            is_selected = (self.events[i].event_id == event_id)
            
            # Since we're using simple QLabels now, highlight with background color
            if isinstance(thumb, QLabel):
                if is_selected:
                    thumb.setStyleSheet("padding: 5px; background-color: lightblue; border: 2px solid blue;")
                else:
                    thumb.setStyleSheet("padding: 5px; background-color: white;")
            else:
                # For future when we have proper thumbnail widgets
                if hasattr(thumb, 'set_selected'):
                    thumb.set_selected(is_selected)
    
    def clear(self):
        """Clear gallery."""
        for thumb in self.thumb_widgets:
            thumb.deleteLater()
        self.thumb_widgets.clear()
        self.events = []
