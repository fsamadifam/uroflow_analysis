"""Dialog for creating events with visual region selection."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QDialogButtonBox, QGroupBox, QFormLayout
)
from PySide6.QtCore import Qt


class CreateEventDialog(QDialog):
    """Dialog for creating a new event by visually selecting a region."""
    
    def __init__(self, timestamp: np.ndarray, mass: np.ndarray, 
                 default_center: float = None, parent=None):
        """Initialize the dialog.
        
        Args:
            timestamp: Full timestamp array
            mass: Full mass array
            default_center: Default center time for the view (optional)
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.timestamp = timestamp
        self.mass = mass
        self.result_start = None
        self.result_end = None
        
        # Default view window
        self.window_size = 60.0  # 60 seconds visible
        min_time = float(timestamp[0])
        max_time = float(timestamp[-1])
        
        if default_center is None:
            default_center = (min_time + max_time) / 2
        
        self.view_center = default_center
        self.min_time = min_time
        self.max_time = max_time
        
        self._setup_ui()
        self._update_plot()
    
    def _setup_ui(self):
        """Setup the dialog UI."""
        self.setWindowTitle("Create New Event")
        self.setMinimumSize(800, 500)
        
        layout = QVBoxLayout(self)
        
        # Instructions
        instructions = QLabel(
            "1. Use the navigation controls to find the region\n"
            "2. Drag the green (start) and red (end) lines to set event boundaries\n"
            "3. Click 'Create Event' when done"
        )
        instructions.setStyleSheet("color: #666; margin-bottom: 10px;")
        layout.addWidget(instructions)
        
        # Navigation controls
        nav_group = QGroupBox("Navigation")
        nav_layout = QHBoxLayout()
        
        # Center time control
        nav_layout.addWidget(QLabel("Center Time:"))
        self.center_spin = QDoubleSpinBox()
        self.center_spin.setRange(self.min_time, self.max_time)
        self.center_spin.setValue(self.view_center)
        self.center_spin.setDecimals(1)
        self.center_spin.setSuffix(" s")
        self.center_spin.setSingleStep(10.0)
        self.center_spin.valueChanged.connect(self._on_center_changed)
        nav_layout.addWidget(self.center_spin)
        
        # Quick navigation buttons
        nav_layout.addWidget(QLabel("  "))
        
        btn_back_60 = QPushButton("◀◀ -60s")
        btn_back_60.clicked.connect(lambda: self._move_view(-60))
        nav_layout.addWidget(btn_back_60)
        
        btn_back_10 = QPushButton("◀ -10s")
        btn_back_10.clicked.connect(lambda: self._move_view(-10))
        nav_layout.addWidget(btn_back_10)
        
        btn_fwd_10 = QPushButton("+10s ▶")
        btn_fwd_10.clicked.connect(lambda: self._move_view(10))
        nav_layout.addWidget(btn_fwd_10)
        
        btn_fwd_60 = QPushButton("+60s ▶▶")
        btn_fwd_60.clicked.connect(lambda: self._move_view(60))
        nav_layout.addWidget(btn_fwd_60)
        
        nav_layout.addStretch()
        
        # Window size control
        nav_layout.addWidget(QLabel("Window:"))
        self.window_spin = QDoubleSpinBox()
        self.window_spin.setRange(10, 300)
        self.window_spin.setValue(self.window_size)
        self.window_spin.setDecimals(0)
        self.window_spin.setSuffix(" s")
        self.window_spin.setSingleStep(10)
        self.window_spin.valueChanged.connect(self._on_window_changed)
        nav_layout.addWidget(self.window_spin)
        
        nav_group.setLayout(nav_layout)
        layout.addWidget(nav_group)
        
        # Plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'Mass', units='g')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Data curve
        self.data_curve = self.plot_widget.plot(
            pen=pg.mkPen('k', width=2),
            symbol='o',
            symbolSize=3,
            symbolBrush='k'
        )
        
        # Selection region (draggable)
        default_start = self.view_center - 5
        default_end = self.view_center + 5
        
        self.selection_region = pg.LinearRegionItem(
            values=[default_start, default_end],
            brush=pg.mkBrush(100, 200, 100, 80),
            movable=True
        )
        self.selection_region.sigRegionChanged.connect(self._on_region_changed)
        self.plot_widget.addItem(self.selection_region)
        
        layout.addWidget(self.plot_widget, stretch=1)
        
        # Event info display
        info_group = QGroupBox("Selected Event")
        info_layout = QFormLayout()
        
        self.start_label = QLabel(f"{default_start:.2f} s")
        info_layout.addRow("Start:", self.start_label)
        
        self.end_label = QLabel(f"{default_end:.2f} s")
        info_layout.addRow("End:", self.end_label)
        
        self.duration_label = QLabel(f"{default_end - default_start:.2f} s")
        info_layout.addRow("Duration:", self.duration_label)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.create_btn = QPushButton("Create Event")
        self.create_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 8px 20px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.create_btn.clicked.connect(self._on_create)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(self.create_btn)
        
        layout.addLayout(button_layout)
    
    def _update_plot(self):
        """Update the plot view."""
        # Calculate view bounds
        half_window = self.window_size / 2
        view_start = max(self.min_time, self.view_center - half_window)
        view_end = min(self.max_time, self.view_center + half_window)
        
        # Find data indices
        start_idx = np.searchsorted(self.timestamp, view_start)
        end_idx = np.searchsorted(self.timestamp, view_end)
        
        # Extract window data
        window_t = self.timestamp[start_idx:end_idx]
        window_m = self.mass[start_idx:end_idx]
        
        # Update plot
        self.data_curve.setData(window_t, window_m)
        self.plot_widget.setXRange(view_start, view_end, padding=0.02)
        
        # Auto-range Y
        try:
            self.plot_widget.getViewBox().enableAutoRange(axis=pg.ViewBox.YAxis)
        except:
            self.plot_widget.autoRange()
    
    def _on_center_changed(self, value):
        """Handle center time change."""
        self.view_center = value
        self._update_plot()
    
    def _on_window_changed(self, value):
        """Handle window size change."""
        self.window_size = value
        self._update_plot()
    
    def _move_view(self, delta_s: float):
        """Move the view by delta seconds."""
        new_center = self.view_center + delta_s
        new_center = max(self.min_time + self.window_size/2, 
                        min(new_center, self.max_time - self.window_size/2))
        self.center_spin.setValue(new_center)
    
    def _on_region_changed(self):
        """Handle region selection change."""
        region = self.selection_region.getRegion()
        start = min(region)
        end = max(region)
        duration = end - start
        
        self.start_label.setText(f"{start:.2f} s")
        self.end_label.setText(f"{end:.2f} s")
        self.duration_label.setText(f"{duration:.2f} s")
        
        # Validate
        if duration < 0.5:
            self.create_btn.setEnabled(False)
            self.duration_label.setStyleSheet("color: red;")
        else:
            self.create_btn.setEnabled(True)
            self.duration_label.setStyleSheet("")
    
    def _on_create(self):
        """Handle create button click."""
        region = self.selection_region.getRegion()
        self.result_start = min(region)
        self.result_end = max(region)
        
        if self.result_end - self.result_start < 0.5:
            return
        
        self.accept()
    
    def get_event_times(self) -> tuple:
        """Get the selected event times.
        
        Returns:
            Tuple of (start_time, end_time) or (None, None) if cancelled
        """
        return (self.result_start, self.result_end)
