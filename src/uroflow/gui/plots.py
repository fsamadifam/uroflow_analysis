"""Plot widgets for overview and detail views using pyqtgraph."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QScrollBar, QComboBox
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor

from uroflow.core.types import Event, Segment, Gap


class OverviewPlot(QWidget):
    """Overview plot showing full 24h trace with events and gaps."""
    
    event_clicked = Signal(str)  # event_id
    region_selected = Signal(float, float)  # start_time, end_time
    manual_event_requested = Signal(float, float)  # start_time, end_time
    create_event_confirmed = Signal(float, float)  # start_time, end_time - when user confirms creation
    detect_events_requested = Signal()  # When detect events button is clicked
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.timestamp = None
        self.mass = None
        self.segments = []
        self.gaps = []
        self.events = []
        
        # For manual event creation
        self.drag_start_pos = None
        self.drag_line = None
        
        # Creation mode
        self._create_mode = False
        self._create_region = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup plot widget."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar for create mode
        toolbar = QHBoxLayout()
        
        self.create_mode_btn = QPushButton("+ Create New Event")
        self.create_mode_btn.setCheckable(True)
        self.create_mode_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 5px 15px;
                border: 1px solid #45a049;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:checked {
                background-color: #388E3C;
                border: 2px solid #2E7D32;
            }
        """)
        self.create_mode_btn.toggled.connect(self._on_create_mode_toggled)
        toolbar.addWidget(self.create_mode_btn)
        
        self.confirm_create_btn = QPushButton("✓ Add Event")
        self.confirm_create_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 5px 15px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.confirm_create_btn.clicked.connect(self._on_confirm_create)
        self.confirm_create_btn.setEnabled(False)
        self.confirm_create_btn.hide()
        toolbar.addWidget(self.confirm_create_btn)
        
        self.cancel_create_btn = QPushButton("✕ Cancel")
        self.cancel_create_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                padding: 5px 15px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        self.cancel_create_btn.clicked.connect(self._on_cancel_create)
        self.cancel_create_btn.hide()
        toolbar.addWidget(self.cancel_create_btn)
        
        self.create_info_label = QPushButton("")
        self.create_info_label.setFlat(True)
        self.create_info_label.setEnabled(False)
        self.create_info_label.setStyleSheet("color: #666; border: none;")
        self.create_info_label.hide()
        toolbar.addWidget(self.create_info_label)
        
        # Detect Events button (close to Create New Event button)
        self.detect_events_btn = QPushButton("Detect Events")
        self.detect_events_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 5px 15px;
                border: 1px solid #1976D2;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.detect_events_btn.clicked.connect(self.detect_events_requested.emit)
        toolbar.addWidget(self.detect_events_btn)
        
        toolbar.addStretch()
        
        layout.addLayout(toolbar)
        
        # Create plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'Mass', units='g', color='k')
        self.plot_widget.setLabel('bottom', 'Time', color='k')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Set axis label and tick colors to black
        self.plot_widget.getAxis('left').setPen('k')
        self.plot_widget.getAxis('left').setTextPen('k')
        self.plot_widget.getAxis('bottom').setPen('k')
        self.plot_widget.getAxis('bottom').setTextPen('k')
        
        # Custom time axis formatter
        from pyqtgraph import AxisItem
        class TimeAxisItem(AxisItem):
            def tickStrings(self, values, scale, spacing):
                strings = []
                for v in values:
                    hours = int(v // 3600)
                    minutes = int((v % 3600) // 60)
                    seconds = int(v % 60)
                    if hours > 0:
                        strings.append(f"{hours}:{minutes:02d}:{seconds:02d}")
                    elif minutes > 0:
                        strings.append(f"{minutes}:{seconds:02d}")
                    else:
                        strings.append(f"{seconds}s")
                return strings
        
        # Replace bottom axis
        self.plot_widget.setAxisItems({'bottom': TimeAxisItem(orientation='bottom')})
        
        # Ensure bottom axis is also black
        bottom_axis = self.plot_widget.getAxis('bottom')
        bottom_axis.setPen('k')
        bottom_axis.setTextPen('k')
        
        # Enable box zoom: right-click drag to zoom to a box, middle-click to reset
        self.plot_widget.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        
        # Main plot area with vertical scrollbar
        plot_area_layout = QHBoxLayout()
        plot_area_layout.setContentsMargins(0, 0, 0, 0)
        plot_area_layout.setSpacing(2)
        
        plot_area_layout.addWidget(self.plot_widget, stretch=1)
        
        # Vertical scrollbar for Y-axis navigation (visible only when zoomed)
        self.nav_scrollbar_v = QScrollBar(Qt.Vertical)
        self.nav_scrollbar_v.setMinimum(0)
        self.nav_scrollbar_v.setMaximum(10000)
        self.nav_scrollbar_v.setValue(0)
        self.nav_scrollbar_v.setPageStep(1000)
        self.nav_scrollbar_v.setSingleStep(100)
        self.nav_scrollbar_v.valueChanged.connect(self._on_scrollbar_v_changed)
        self.nav_scrollbar_v.setToolTip("Drag to pan Y-axis (visible when zoomed)")
        self.nav_scrollbar_v.hide()
        
        plot_area_layout.addWidget(self.nav_scrollbar_v)
        
        layout.addLayout(plot_area_layout)
        
        # Horizontal scrollbar for navigation (visible only when zoomed)
        scrollbar_layout = QHBoxLayout()
        scrollbar_layout.setContentsMargins(0, 0, 0, 0)
        
        self.nav_scrollbar = QScrollBar(Qt.Horizontal)
        self.nav_scrollbar.setMinimum(0)
        self.nav_scrollbar.setMaximum(10000)  # High resolution for smooth scrolling
        self.nav_scrollbar.setValue(0)
        self.nav_scrollbar.setPageStep(1000)  # 10% of range
        self.nav_scrollbar.setSingleStep(100)  # 1% of range
        self.nav_scrollbar.valueChanged.connect(self._on_scrollbar_changed)
        self.nav_scrollbar.setToolTip("Drag to pan view (visible when zoomed in)")
        self.nav_scrollbar.hide()  # Hidden until zoomed
        
        # Zoom info label
        self.zoom_label = QLabel("")
        self.zoom_label.setStyleSheet("color: #666; font-size: 10px;")
        self.zoom_label.hide()
        
        # Reset zoom button
        self.reset_zoom_btn = QPushButton("Reset Zoom")
        self.reset_zoom_btn.setStyleSheet("""
            QPushButton {
                background-color: #9E9E9E;
                color: white;
                padding: 2px 8px;
                border-radius: 2px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #757575;
            }
        """)
        self.reset_zoom_btn.clicked.connect(self._on_reset_zoom)
        self.reset_zoom_btn.hide()
        
        scrollbar_layout.addWidget(self.nav_scrollbar, stretch=1)
        scrollbar_layout.addWidget(self.zoom_label)
        scrollbar_layout.addWidget(self.reset_zoom_btn)
        
        layout.addLayout(scrollbar_layout)
        
        # Plot items
        self.data_curve = self.plot_widget.plot(pen=pg.mkPen('k', width=1))
        
        # Gap regions (shaded)
        self.gap_items = []
        
        # Event markers
        self.event_items = []
        
        # Selection indicator (arrow pointing to selected event)
        self.selection_arrow = None
        
        # Track data range for scrollbars
        self._data_start = 0.0
        self._data_end = 1.0
        self._data_y_min = 0.0
        self._data_y_max = 1.0
        self._updating_scrollbar = False  # Flag to prevent signal loops
        
        # Enable mouse interaction
        self.plot_widget.scene().sigMouseClicked.connect(self._on_mouse_click)
        
        # Enable drag for manual event creation (Ctrl+Click+Drag)
        self.plot_widget.setMouseEnabled(x=True, y=False)
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_move)
        
        # Connect range changes to update scrollbars
        self.plot_widget.sigXRangeChanged.connect(self._on_x_range_changed)
        self.plot_widget.sigYRangeChanged.connect(self._on_y_range_changed)
    
    def set_data(self, timestamp: np.ndarray, mass: np.ndarray,
                 segments: list, gaps: list, events: list):
        """Set data and redraw plot.
        
        Args:
            timestamp: Time array
            mass: Mass array
            segments: List of Segment objects
            gaps: List of Gap objects
            events: List of Event objects
        """
        self.timestamp = timestamp
        self.mass = mass
        self.segments = segments
        self.gaps = gaps
        self.events = events
        
        # Track data range for scrollbars
        if timestamp is not None and len(timestamp) > 0:
            self._data_start = timestamp[0]
            self._data_end = timestamp[-1]
        if mass is not None and len(mass) > 0:
            self._data_y_min = float(np.nanmin(mass))
            self._data_y_max = float(np.nanmax(mass))
            # Add small padding to Y range
            y_padding = (self._data_y_max - self._data_y_min) * 0.02
            self._data_y_min -= y_padding
            self._data_y_max += y_padding
        
        self._redraw()
    
    def _redraw(self):
        """Redraw entire plot."""
        if self.timestamp is None:
            print("OverviewPlot._redraw: No data (timestamp is None)")
            return
        
        print(f"OverviewPlot._redraw: Drawing {len(self.timestamp)} points, {len(self.events)} events")
        
        # Update data curve with all points (no downsampling)
        try:
            self.data_curve.setData(self.timestamp, self.mass)
            print(f"  Data curve updated")
        except Exception as e:
            print(f"  ERROR setting data curve: {e}")
            import traceback
            traceback.print_exc()
        
        # Draw gaps
        try:
            self._draw_gaps()
            print(f"  Gaps drawn")
        except Exception as e:
            print(f"  ERROR drawing gaps: {e}")
            import traceback
            traceback.print_exc()
        
        # Draw events
        try:
            self._draw_events()
            print(f"  Events drawn")
        except Exception as e:
            print(f"  ERROR drawing events: {e}")
            import traceback
            traceback.print_exc()
        
        # Auto-range
        try:
            self.plot_widget.autoRange()
            print(f"  Auto-range complete")
        except Exception as e:
            print(f"  ERROR auto-ranging: {e}")
            import traceback
            traceback.print_exc()
        
        # Force repaint
        self.plot_widget.update()
        self.update()
    
    def _draw_gaps(self):
        """Draw gap regions."""
        # Clear existing
        for item in self.gap_items:
            self.plot_widget.removeItem(item)
        self.gap_items.clear()
        
        if not self.gaps or self.timestamp is None:
            return
        
        for gap in self.gaps:
            if gap.end_idx > gap.start_idx:
                t_start = self.timestamp[gap.start_idx]
                t_end = self.timestamp[gap.end_idx - 1] if gap.end_idx < len(self.timestamp) else self.timestamp[-1]
                
                # Create shaded region
                region = pg.LinearRegionItem(
                    values=[t_start, t_end],
                    orientation='vertical',
                    brush=pg.mkBrush(200, 200, 200, 100),
                    movable=False
                )
                self.plot_widget.addItem(region)
                self.gap_items.append(region)
    
    def _draw_events(self):
        """Draw event markers."""
        # Clear existing items safely
        for item in self.event_items:
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass  # Item may already be removed
        self.event_items.clear()
        
        if not self.events:
            return
        
        for event in self.events:
            # Color by label and source
            color = self._get_event_color(event)
            
            # Create region item with matching border color
            region = pg.LinearRegionItem(
                values=[event.start_time_s, event.end_time_s],
                orientation='vertical',
                brush=pg.mkBrush(*color, 80),  # Semi-transparent fill
                pen=pg.mkPen(color, width=2),  # Border matches fill color
                movable=False
            )
            
            # Store event_id for click detection (used by _on_mouse_click)
            region.event_id = event.event_id
            
            self.plot_widget.addItem(region)
            self.event_items.append(region)
    
    def _get_event_color(self, event: Event) -> tuple:
        """Get color for event based on label and source.
        
        Returns:
            RGB tuple (0-255)
        """
        # By label - high-contrast colors
        if event.label_user == "urine":
            return (255, 176, 0)  # Vivid orange/amber (#FFB000)
        elif event.label_user == "feces":
            return (92, 46, 0)  # Dark brown (#5C2E00)
        elif event.label_user == "bad":
            return (255, 0, 0)  # Red
        
        # By source (unlabeled) - neutral gray
        if event.source == "manual":
            return (0, 200, 0)  # Green
        elif event.source == "acquisition":
            return (255, 200, 0)  # Yellow
        else:  # "auto"
            return (128, 128, 128)  # Neutral gray (#808080)
    
    def _on_mouse_click(self, event):
        """Handle mouse click to select event or start drag."""
        from PySide6.QtCore import Qt
        
        if event.button() != 1:  # Left click only
            return
        
        if self.timestamp is None:
            return
        
        pos = event.scenePos()
        
        # First check if we clicked on an event region
        items_at_pos = self.plot_widget.scene().items(pos)
        for item in items_at_pos:
            if hasattr(item, 'event_id'):
                # Clicked on an event region
                print(f"Clicked on event region: {item.event_id[:8]}")
                self.event_clicked.emit(item.event_id)
                return
        
        # If not on a region, check by time coordinate
        mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
        time_clicked = mouse_point.x()
        
        # Check if Ctrl is pressed for manual event creation
        modifiers = event.modifiers()
        if modifiers == Qt.ControlModifier:
            # Start drag for manual event
            self.drag_start_pos = time_clicked
            print(f"Manual event drag started at {time_clicked:.2f}s (Ctrl+Click)")
            return
        
        # Otherwise, select existing event by time
        for event_obj in self.events:
            if event_obj.contains_time(time_clicked):
                print(f"Clicked on event by time: {event_obj.event_id[:8]}")
                self.event_clicked.emit(event_obj.event_id)
                break
    
    def _on_mouse_move(self, pos):
        """Handle mouse move for drag selection."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        
        if self.drag_start_pos is None:
            return
        
        # Check if still dragging (Ctrl held)
        modifiers = QApplication.keyboardModifiers()
        if not (modifiers & Qt.ControlModifier):
            # Ctrl released, finish drag
            self._finish_drag()
            return
        
        # Get current position in data coordinates
        if self.plot_widget.sceneBoundingRect().contains(pos):
            mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
            current_time = mouse_point.x()
            
            # Draw selection line/region
            if self.drag_line is None:
                self.drag_line = pg.LinearRegionItem(
                    values=[self.drag_start_pos, current_time],
                    brush=pg.mkBrush(100, 100, 255, 100),
                    movable=False
                )
                self.plot_widget.addItem(self.drag_line)
            else:
                self.drag_line.setRegion([self.drag_start_pos, current_time])
    
    def _finish_drag(self):
        """Finish drag and create manual event."""
        if self.drag_start_pos is None:
            return
        
        if self.drag_line is not None:
            # Get final region
            region = self.drag_line.getRegion()
            start_time = min(region)
            end_time = max(region)
            
            # Remove visual
            self.plot_widget.removeItem(self.drag_line)
            self.drag_line = None
            
            # Only create if region is significant (> 0.5 seconds)
            if end_time - start_time > 0.5:
                print(f"Manual event created: {start_time:.2f}s -> {end_time:.2f}s")
                self.manual_event_requested.emit(start_time, end_time)
        
        self.drag_start_pos = None
    
    def _on_create_mode_toggled(self, checked: bool):
        """Handle create mode toggle."""
        self._create_mode = checked
        
        if checked:
            # Show creation UI
            self.confirm_create_btn.show()
            self.confirm_create_btn.setEnabled(False)
            self.cancel_create_btn.show()
            self.create_info_label.show()
            self.create_info_label.setText("Drag the green region to select event boundaries")
            
            # Create the selection region in the center of current view
            view_range = self.plot_widget.viewRange()
            center = (view_range[0][0] + view_range[0][1]) / 2
            half_width = 5.0  # 10 second default width
            
            self._create_region = pg.LinearRegionItem(
                values=[center - half_width, center + half_width],
                brush=pg.mkBrush(100, 255, 100, 100),
                pen=pg.mkPen('g', width=2),
                movable=True
            )
            self._create_region.sigRegionChanged.connect(self._on_create_region_changed)
            self.plot_widget.addItem(self._create_region)
            self._create_region.setZValue(100)  # Above events
            
            self.confirm_create_btn.setEnabled(True)
            self._on_create_region_changed()  # Update info label
        else:
            # Hide creation UI
            self.confirm_create_btn.hide()
            self.cancel_create_btn.hide()
            self.create_info_label.hide()
            
            # Remove region
            if self._create_region is not None:
                try:
                    self.plot_widget.removeItem(self._create_region)
                except:
                    pass
                self._create_region = None
    
    def _on_create_region_changed(self):
        """Update info label when create region changes."""
        if self._create_region is None:
            return
        
        region = self._create_region.getRegion()
        start = min(region)
        end = max(region)
        duration = end - start
        
        self.create_info_label.setText(f"Start: {start:.1f}s | End: {end:.1f}s | Duration: {duration:.2f}s")
        
        # Validate
        if duration < 0.5:
            self.confirm_create_btn.setEnabled(False)
        else:
            self.confirm_create_btn.setEnabled(True)
    
    def _on_confirm_create(self):
        """Confirm event creation."""
        if self._create_region is None:
            return
        
        region = self._create_region.getRegion()
        start = min(region)
        end = max(region)
        
        if end - start >= 0.5:
            print(f"Create event confirmed: {start:.2f}s -> {end:.2f}s")
            self.create_event_confirmed.emit(start, end)
        
        # Exit create mode
        self.create_mode_btn.setChecked(False)
    
    def _on_cancel_create(self):
        """Cancel event creation."""
        self.create_mode_btn.setChecked(False)
    
    def highlight_event(self, event_id: str, center_view: bool = False):
        """Highlight a specific event with arrow and distinct styling.
        
        Args:
            event_id: Event ID to highlight
            center_view: If True, center the x-range on the selected event
        """
        try:
            # Remove old arrow if exists
            if self.selection_arrow is not None:
                try:
                    self.plot_widget.removeItem(self.selection_arrow)
                except:
                    pass
                self.selection_arrow = None
            
            # Build a map of event_id to event for safe lookup
            event_map = {e.event_id: e for e in self.events} if self.events else {}
            
            selected_event = None
            
            # Find and highlight the event region
            for region in self.event_items:
                if not hasattr(region, 'event_id'):
                    continue
                    
                region_event_id = region.event_id
                event = event_map.get(region_event_id)
                if not event:
                    continue
                
                if region_event_id == event_id:
                    # SELECTED: Keep original color but make it very bright
                    color = self._get_event_color(event)
                    region.setBrush(pg.mkBrush(*color, 200))
                    if hasattr(region, 'setPen'):
                        region.setPen(pg.mkPen((0, 0, 0), width=4))
                    region.setZValue(50)  # Bring to front
                    selected_event = event
                else:
                    # Normal: use event's natural color with lower opacity
                    color = self._get_event_color(event)
                    region.setBrush(pg.mkBrush(*color, 60))
                    if hasattr(region, 'setPen'):
                        region.setPen(pg.mkPen(color, width=1))
                    region.setZValue(10)
            
            # Add arrow indicator above selected event
            if selected_event is not None:
                center_time = (selected_event.start_time_s + selected_event.end_time_s) / 2
                
                # Create arrow using text annotation
                arrow = pg.TextItem(
                    text="▼",
                    color=(0, 0, 0),
                    anchor=(0.5, 1.0),
                    border={'color': (255, 255, 0), 'width': 2},
                    fill=(255, 255, 0, 200)
                )
                arrow.setFont(pg.QtGui.QFont("Arial", 20, pg.QtGui.QFont.Bold))
                
                # Position at top of plot
                view_range = self.plot_widget.viewRange()
                y_pos = view_range[1][1] * 0.95  # 95% up the Y axis
                
                arrow.setPos(center_time, y_pos)
                arrow.setZValue(100)  # Above everything
                
                self.plot_widget.addItem(arrow)
                self.selection_arrow = arrow
                
                # Center view on selected event if requested
                if center_view:
                    self.center_on_event(selected_event)
                
        except Exception as e:
            print(f"ERROR in highlight_event: {e}")
    
    def center_on_event(self, event, padding_factor: float = 3.0):
        """Center both X and Y range on a specific event.
        
        Args:
            event: Event object to center on
            padding_factor: Multiplier for event duration to set window width
        """
        if event is None or self.timestamp is None or self.mass is None:
            return
        
        try:
            # === X-axis centering ===
            event_duration = event.end_time_s - event.start_time_s
            center_time = (event.start_time_s + event.end_time_s) / 2
            
            # Window width is event duration * padding_factor (min 30s for short events)
            window_width = max(event_duration * padding_factor, 30.0)
            half_width = window_width / 2
            
            # Calculate new X range, clamped to data bounds
            new_x_start = max(center_time - half_width, self._data_start)
            new_x_end = min(center_time + half_width, self._data_end)
            
            # === Y-axis centering ===
            # Get mass values within the event time window
            start_idx = max(0, event.start_idx)
            end_idx = min(len(self.mass), event.end_idx)
            
            if start_idx < end_idx:
                event_mass = self.mass[start_idx:end_idx]
                event_y_min = float(np.nanmin(event_mass))
                event_y_max = float(np.nanmax(event_mass))
                
                # Add padding around the event's Y range (50% on each side)
                y_range = event_y_max - event_y_min
                y_padding = max(y_range * 0.5, 0.5)  # At least 0.5g padding
                
                new_y_min = max(event_y_min - y_padding, self._data_y_min)
                new_y_max = min(event_y_max + y_padding, self._data_y_max)
            else:
                # Fallback to full Y range
                new_y_min = self._data_y_min
                new_y_max = self._data_y_max
            
            # Set both ranges
            self.plot_widget.setXRange(new_x_start, new_x_end, padding=0)
            self.plot_widget.setYRange(new_y_min, new_y_max, padding=0)
            
        except Exception as e:
            print(f"ERROR in center_on_event: {e}")
    
    def _on_x_range_changed(self, view_box, x_range):
        """Handle x-range change - update scrollbar visibility and position.
        
        Args:
            view_box: The ViewBox that changed
            x_range: New (min, max) x range
        """
        if self._updating_scrollbar or self.timestamp is None:
            return
        
        try:
            view_start, view_end = x_range
            data_range = self._data_end - self._data_start
            view_width = view_end - view_start
            
            if data_range <= 0:
                return
            
            # Calculate zoom level (1.0 = full view, higher = zoomed in)
            zoom_level = data_range / view_width if view_width > 0 else 1.0
            
            # Check if Y is also zoomed
            y_range = self.plot_widget.viewRange()[1]
            y_view_height = y_range[1] - y_range[0]
            y_data_range = self._data_y_max - self._data_y_min
            y_zoom = y_data_range / y_view_height if y_view_height > 0 else 1.0
            
            # Show each scrollbar only when its axis is zoomed (so it's functional)
            # Show zoom controls when either axis is zoomed
            is_x_zoomed = zoom_level > 1.1
            is_y_zoomed = y_zoom > 1.1
            is_any_zoomed = is_x_zoomed or is_y_zoomed
            
            self.nav_scrollbar.setVisible(is_x_zoomed)
            self.nav_scrollbar_v.setVisible(is_y_zoomed)
            self.zoom_label.setVisible(is_any_zoomed)
            self.reset_zoom_btn.setVisible(is_any_zoomed)
            
            if is_any_zoomed:
                # Update zoom label showing both axes if zoomed
                if is_x_zoomed and is_y_zoomed:
                    self.zoom_label.setText(f"Zoom: X {zoom_level:.1f}x, Y {y_zoom:.1f}x")
                elif is_x_zoomed:
                    self.zoom_label.setText(f"Zoom: X {zoom_level:.1f}x")
                else:
                    self.zoom_label.setText(f"Zoom: Y {y_zoom:.1f}x")
                
                self._updating_scrollbar = True
                
                # Update horizontal scrollbar position and page size
                page_fraction = view_width / data_range
                page_step = int(10000 * page_fraction)
                self.nav_scrollbar.setPageStep(max(page_step, 100))
                
                # Single step = 2% of visible window for extra-fine X scrolling
                single_step = int(page_step * 0.02)
                self.nav_scrollbar.setSingleStep(max(single_step, 10))
                
                scrollable_range = data_range - view_width
                if scrollable_range > 0:
                    position_fraction = (view_start - self._data_start) / scrollable_range
                    scrollbar_value = int(position_fraction * (10000 - page_step))
                    self.nav_scrollbar.setValue(max(0, min(scrollbar_value, 10000 - page_step)))
                
                # Also update vertical scrollbar position (needed when showing due to X zoom)
                if y_data_range > 0:
                    y_page_fraction = y_view_height / y_data_range
                    y_page_step = int(10000 * y_page_fraction)
                    self.nav_scrollbar_v.setPageStep(max(y_page_step, 100))
                    
                    # Single step = 5% of visible window for fine scrolling
                    y_single_step = int(y_page_step * 0.05)
                    self.nav_scrollbar_v.setSingleStep(max(y_single_step, 20))
                    
                    y_scrollable_range = y_data_range - y_view_height
                    if y_scrollable_range > 0:
                        # Inverted: high scrollbar value = low Y view
                        y_position_fraction = (self._data_y_max - y_range[1]) / y_scrollable_range
                        y_scrollbar_value = int(y_position_fraction * (10000 - y_page_step))
                        self.nav_scrollbar_v.setValue(max(0, min(y_scrollbar_value, 10000 - y_page_step)))
                    else:
                        # Y not scrollable (full range visible), set to 0
                        self.nav_scrollbar_v.setValue(0)
                
                self._updating_scrollbar = False
                
        except Exception as e:
            self._updating_scrollbar = False
            print(f"ERROR in _on_x_range_changed: {e}")
    
    def _on_scrollbar_changed(self, value: int):
        """Handle scrollbar value change - pan the plot.
        
        Args:
            value: New scrollbar value (0-10000)
        """
        if self._updating_scrollbar or self.timestamp is None:
            return
        
        try:
            self._updating_scrollbar = True
            
            # Get current view width
            view_range = self.plot_widget.viewRange()
            view_width = view_range[0][1] - view_range[0][0]
            
            data_range = self._data_end - self._data_start
            scrollable_range = data_range - view_width
            
            if scrollable_range <= 0:
                self._updating_scrollbar = False
                return
            
            # Calculate page step for correct position mapping
            page_fraction = view_width / data_range
            page_step = int(10000 * page_fraction)
            
            # Map scrollbar value to view position
            max_scrollbar = 10000 - page_step
            if max_scrollbar > 0:
                position_fraction = value / max_scrollbar
            else:
                position_fraction = 0
            
            new_start = self._data_start + (position_fraction * scrollable_range)
            new_end = new_start + view_width
            
            # Clamp to data bounds
            if new_end > self._data_end:
                new_end = self._data_end
                new_start = new_end - view_width
            if new_start < self._data_start:
                new_start = self._data_start
                new_end = new_start + view_width
            
            # Update plot range
            self.plot_widget.setXRange(new_start, new_end, padding=0)
            
            self._updating_scrollbar = False
            
        except Exception as e:
            self._updating_scrollbar = False
            print(f"ERROR in _on_scrollbar_changed: {e}")
    
    def _on_reset_zoom(self):
        """Reset to full data view."""
        if self.timestamp is None:
            return
        
        try:
            self.plot_widget.autoRange()
        except Exception as e:
            print(f"ERROR in _on_reset_zoom: {e}")
    
    def _on_y_range_changed(self, view_box, y_range):
        """Handle y-range change - update vertical scrollbar visibility and position.
        
        Args:
            view_box: The ViewBox that changed
            y_range: New (min, max) y range
        """
        if self._updating_scrollbar or self.mass is None:
            return
        
        try:
            view_min, view_max = y_range
            data_range = self._data_y_max - self._data_y_min
            view_height = view_max - view_min
            
            if data_range <= 0:
                return
            
            # Calculate Y zoom level
            y_zoom_level = data_range / view_height if view_height > 0 else 1.0
            
            # Check if X is also zoomed
            x_range = self.plot_widget.viewRange()[0]
            x_view_width = x_range[1] - x_range[0]
            x_data_range = self._data_end - self._data_start
            x_zoom = x_data_range / x_view_width if x_view_width > 0 else 1.0
            
            # Show each scrollbar only when its axis is zoomed (so it's functional)
            # Show zoom controls when either axis is zoomed
            is_y_zoomed = y_zoom_level > 1.1
            is_x_zoomed = x_zoom > 1.1
            is_any_zoomed = is_x_zoomed or is_y_zoomed
            
            self.nav_scrollbar.setVisible(is_x_zoomed)
            self.nav_scrollbar_v.setVisible(is_y_zoomed)
            self.zoom_label.setVisible(is_any_zoomed)
            self.reset_zoom_btn.setVisible(is_any_zoomed)
            
            if is_any_zoomed:
                self._updating_scrollbar = True
                
                # Update vertical scrollbar position and page size
                page_fraction = view_height / data_range
                page_step = int(10000 * page_fraction)
                self.nav_scrollbar_v.setPageStep(max(page_step, 100))
                
                # Single step = 5% of visible window for fine scrolling
                single_step = int(page_step * 0.05)
                self.nav_scrollbar_v.setSingleStep(max(single_step, 20))
                
                # Position (inverted - top of scrollbar = high Y values)
                scrollable_range = data_range - view_height
                if scrollable_range > 0:
                    position_fraction = (self._data_y_max - view_max) / scrollable_range
                    scrollbar_value = int(position_fraction * (10000 - page_step))
                    self.nav_scrollbar_v.setValue(max(0, min(scrollbar_value, 10000 - page_step)))
                else:
                    self.nav_scrollbar_v.setValue(0)
                
                # Also update horizontal scrollbar position (needed when showing due to Y zoom)
                if x_data_range > 0:
                    x_page_fraction = x_view_width / x_data_range
                    x_page_step = int(10000 * x_page_fraction)
                    self.nav_scrollbar.setPageStep(max(x_page_step, 100))
                    
                    # Single step = 2% of visible window for extra-fine X scrolling
                    x_single_step = int(x_page_step * 0.02)
                    self.nav_scrollbar.setSingleStep(max(x_single_step, 10))
                    
                    x_scrollable_range = x_data_range - x_view_width
                    if x_scrollable_range > 0:
                        x_position_fraction = (x_range[0] - self._data_start) / x_scrollable_range
                        x_scrollbar_value = int(x_position_fraction * (10000 - x_page_step))
                        self.nav_scrollbar.setValue(max(0, min(x_scrollbar_value, 10000 - x_page_step)))
                    else:
                        self.nav_scrollbar.setValue(0)
                
                self._updating_scrollbar = False
            
            # Update zoom label if any zoom is active
            if is_any_zoomed:
                if is_x_zoomed and is_y_zoomed:
                    self.zoom_label.setText(f"Zoom: X {x_zoom:.1f}x, Y {y_zoom_level:.1f}x")
                elif is_x_zoomed:
                    self.zoom_label.setText(f"Zoom: X {x_zoom:.1f}x")
                else:
                    self.zoom_label.setText(f"Zoom: Y {y_zoom_level:.1f}x")
                
        except Exception as e:
            self._updating_scrollbar = False
            print(f"ERROR in _on_y_range_changed: {e}")
    
    def _on_scrollbar_v_changed(self, value: int):
        """Handle vertical scrollbar value change - pan the Y-axis.
        
        Args:
            value: New scrollbar value (0-10000)
        """
        if self._updating_scrollbar or self.mass is None:
            return
        
        try:
            self._updating_scrollbar = True
            
            # Get current view height
            view_range = self.plot_widget.viewRange()
            view_height = view_range[1][1] - view_range[1][0]
            
            data_range = self._data_y_max - self._data_y_min
            scrollable_range = data_range - view_height
            
            if scrollable_range <= 0:
                self._updating_scrollbar = False
                return
            
            # Calculate page step for correct position mapping
            page_fraction = view_height / data_range
            page_step = int(10000 * page_fraction)
            
            # Map scrollbar value to view position (inverted)
            max_scrollbar = 10000 - page_step
            if max_scrollbar > 0:
                position_fraction = value / max_scrollbar
            else:
                position_fraction = 0
            
            # Inverted: high scrollbar value = low Y view
            new_max = self._data_y_max - (position_fraction * scrollable_range)
            new_min = new_max - view_height
            
            # Clamp to data bounds
            if new_min < self._data_y_min:
                new_min = self._data_y_min
                new_max = new_min + view_height
            if new_max > self._data_y_max:
                new_max = self._data_y_max
                new_min = new_max - view_height
            
            # Update plot range
            self.plot_widget.setYRange(new_min, new_max, padding=0)
            
            self._updating_scrollbar = False
            
        except Exception as e:
            self._updating_scrollbar = False
            print(f"ERROR in _on_scrollbar_v_changed: {e}")
    
    def update_event_bounds(self, event_id: str, start_time: float, end_time: float):
        """Update the bounds of a single event without full redraw.
        
        Args:
            event_id: Event ID to update
            start_time: New start time
            end_time: New end time
        """
        for region in self.event_items:
            if hasattr(region, 'event_id') and region.event_id == event_id:
                region.setRegion([start_time, end_time])
                return True
        return False
    
    def clear(self):
        """Clear all plot data."""
        self.data_curve.setData([], [])
        for item in self.gap_items + self.event_items:
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self.gap_items.clear()
        self.event_items.clear()


class DetailPlot(QWidget):
    """Detail plot showing zoomed view around selected event."""
    
    boundary_changed = Signal(str, float, float)  # event_id, new_start_time, new_end_time
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.timestamp = None
        self.mass = None
        self.current_event = None
        self.window_padding_s = 30.0  # Show ±30s around event
        self._setting_event = False  # Flag to block signals during event setup
        self.plot_style = "line"
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup plot widget."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addWidget(QLabel("Detail plot:"))

        self.plot_style_combo = QComboBox()
        self.plot_style_combo.addItem("Line", "line")
        self.plot_style_combo.addItem("Scatter", "scatter")
        self.plot_style_combo.currentIndexChanged.connect(self._on_plot_style_changed)
        toolbar.addWidget(self.plot_style_combo)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Create plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'Mass', units='g', color='k')
        self.plot_widget.setLabel('bottom', 'Time', color='k')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Set axis label and tick colors to black
        self.plot_widget.getAxis('left').setPen('k')
        self.plot_widget.getAxis('left').setTextPen('k')
        self.plot_widget.getAxis('bottom').setPen('k')
        self.plot_widget.getAxis('bottom').setTextPen('k')
        
        # Custom time axis formatter (always H:M:S for detail plot)
        from pyqtgraph import AxisItem
        class DetailTimeAxisItem(AxisItem):
            def tickStrings(self, values, scale, spacing):
                strings = []
                for v in values:
                    hours = int(v // 3600)
                    minutes = int((v % 3600) // 60)
                    seconds = int(v % 60)
                    strings.append(f"{hours}:{minutes:02d}:{seconds:02d}")
                return strings
        
        # Replace bottom axis
        self.plot_widget.setAxisItems({'bottom': DetailTimeAxisItem(orientation='bottom')})
        
        # Ensure bottom axis is also black
        bottom_axis = self.plot_widget.getAxis('bottom')
        bottom_axis.setPen('k')
        bottom_axis.setTextPen('k')
        
        layout.addWidget(self.plot_widget)
        
        # Plot items
        self.data_curve = self.plot_widget.plot(
            pen=pg.mkPen('k', width=2),
            symbol='o',
            symbolSize=3,
            symbolBrush='k'
        )
        self._apply_plot_style()
        
        # Boundary lines (draggable)
        from PySide6.QtCore import Qt as QtCore
        self.start_line = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=pg.mkPen('g', width=3, style=QtCore.DashLine),
            label='Start',
            labelOpts={'color': 'k', 'position': 0.5, 'anchors': [(1, 0.5), (1, 0.5)]}  # Anchor RIGHT edge, label appears LEFT of line
        )
        self.end_line = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=pg.mkPen('r', width=3, style=QtCore.DashLine),
            label='End',
            labelOpts={'color': 'k', 'position': 0.5, 'anchors': [(0, 0.5), (0, 0.5)]}  # Anchor LEFT edge, label appears RIGHT of line
        )
        
        self.plot_widget.addItem(self.start_line)
        self.plot_widget.addItem(self.end_line)
        
        self.start_line.hide()
        self.end_line.hide()
        
        # Connect drag signals
        self.start_line.sigPositionChanged.connect(self._on_boundary_moved)
        self.end_line.sigPositionChanged.connect(self._on_boundary_moved)

    def _on_plot_style_changed(self, *_args):
        """Handle detail plot style changes."""
        self.plot_style = self.plot_style_combo.currentData()
        self._apply_plot_style()

    def _apply_plot_style(self):
        """Apply current line/scatter rendering to the detail data curve."""
        if self.plot_style == "scatter":
            self.data_curve.setPen(None)
            self.data_curve.setSymbol('o')
            self.data_curve.setSymbolSize(5)
            self.data_curve.setSymbolBrush('k')
            self.data_curve.setSymbolPen(None)
            return

        self.data_curve.setPen(pg.mkPen('k', width=2))
        self.data_curve.setSymbol('o')
        self.data_curve.setSymbolSize(3)
        self.data_curve.setSymbolBrush('k')
        self.data_curve.setSymbolPen(None)

    def set_data(self, timestamp: np.ndarray, mass: np.ndarray):
        """Set full dataset.
        
        Args:
            timestamp: Time array
            mass: Mass array
        """
        self.timestamp = timestamp
        self.mass = mass
    
    def show_event(self, event: Event):
        """Show detail view for an event.
        
        Args:
            event: Event object to display
        """
        try:
            if self.timestamp is None or self.mass is None:
                print("DetailPlot.show_event: No data loaded")
                return
            
            if event is None:
                print("DetailPlot.show_event: Event is None")
                return
            
            # Block boundary change signals while setting up
            self._setting_event = True
            
            try:
                self.current_event = event
                
                # Calculate window
                t_start = max(0, event.start_time_s - self.window_padding_s)
                t_end = min(self.timestamp[-1], event.end_time_s + self.window_padding_s)
                
                # Find indices
                start_idx = np.searchsorted(self.timestamp, t_start)
                end_idx = np.searchsorted(self.timestamp, t_end)
                
                # Ensure valid indices
                if start_idx >= len(self.timestamp) or end_idx <= 0:
                    print(f"DetailPlot.show_event: Invalid indices {start_idx}-{end_idx}")
                    return
                
                # Extract window
                window_t = self.timestamp[start_idx:end_idx]
                window_m = self.mass[start_idx:end_idx]
                
                # Check for valid data
                if len(window_t) == 0 or len(window_m) == 0:
                    print(f"DetailPlot.show_event: Empty window data")
                    return
                
                # Update plot (full resolution)
                self.data_curve.setData(window_t, window_m)
                
                # Update boundary lines (signals blocked by _setting_event flag)
                self.start_line.setValue(event.start_time_s)
                self.end_line.setValue(event.end_time_s)
                self.start_line.show()
                self.end_line.show()
                
                # Set view range
                self.plot_widget.setXRange(t_start, t_end, padding=0.02)
                # Auto-range Y only (older pyqtgraph doesn't support axis parameter)
                try:
                    self.plot_widget.getViewBox().enableAutoRange(axis=pg.ViewBox.YAxis)
                    self.plot_widget.getViewBox().autoRange()
                except Exception as e:
                    # Fallback if enableAutoRange fails
                    print(f"DetailPlot: Auto-range fallback: {e}")
                    self.plot_widget.autoRange()
            finally:
                # Always unblock signals
                self._setting_event = False
                
        except Exception as e:
            self._setting_event = False  # Make sure to unblock on error
            print(f"ERROR in DetailPlot.show_event: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _on_boundary_moved(self):
        """Handle boundary line movement."""
        # Don't emit signals during initial event setup
        if self._setting_event:
            return
        
        if self.current_event is None:
            return
        
        new_start = self.start_line.value()
        new_end = self.end_line.value()
        
        # Ensure start < end
        if new_start >= new_end:
            return
        
        # Emit signal
        self.boundary_changed.emit(self.current_event.event_id, new_start, new_end)
    
    def clear(self):
        """Clear plot."""
        self.data_curve.setData([], [])
        self.start_line.hide()
        self.end_line.hide()
        self.current_event = None
    
    def enable_boundary_editing(self, enabled: bool):
        """Enable or disable boundary line dragging.
        
        Args:
            enabled: True to enable dragging
        """
        self.start_line.setMovable(enabled)
        self.end_line.setMovable(enabled)
