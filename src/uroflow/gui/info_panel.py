"""Event information panel widget."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QScrollArea,
    QGroupBox, QFrame
)
from PySide6.QtCore import Qt
from typing import Optional

from uroflow.core.types import Event


class InfoPanel(QWidget):
    """Panel to display detailed event information."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_event = None
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        # Content widget
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(10)
        
        # Event Identity
        identity_group = QGroupBox("Event Identity")
        identity_layout = QFormLayout()
        identity_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        self.event_id_label = QLabel("—")
        self.event_id_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.event_id_label.setWordWrap(True)
        identity_layout.addRow("Event ID:", self.event_id_label)
        
        self.source_label = QLabel("—")
        identity_layout.addRow("Source:", self.source_label)
        
        self.label_label = QLabel("—")
        identity_layout.addRow("Label:", self.label_label)
        
        self.locked_label = QLabel("—")
        identity_layout.addRow("Locked:", self.locked_label)
        
        self.needs_manual_label = QLabel("—")
        identity_layout.addRow("Needs Manual:", self.needs_manual_label)
        
        identity_group.setLayout(identity_layout)
        content_layout.addWidget(identity_group)
        
        # Timing Information
        timing_group = QGroupBox("Timing")
        timing_layout = QFormLayout()
        timing_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        self.start_time_label = QLabel("—")
        timing_layout.addRow("Start Time:", self.start_time_label)
        
        self.end_time_label = QLabel("—")
        timing_layout.addRow("End Time:", self.end_time_label)
        
        self.duration_label = QLabel("—")
        timing_layout.addRow("Duration:", self.duration_label)
        
        timing_group.setLayout(timing_layout)
        content_layout.addWidget(timing_group)
        
        # Features
        features_group = QGroupBox("Features")
        features_layout = QFormLayout()
        features_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        self.delta_mass_label = QLabel("—")
        features_layout.addRow("Δ Mass:", self.delta_mass_label)
        
        self.peak_slope_label = QLabel("—")
        features_layout.addRow("Peak Slope:", self.peak_slope_label)
        
        self.mean_slope_label = QLabel("—")
        features_layout.addRow("Mean Slope:", self.mean_slope_label)
        
        self.oscillation_label = QLabel("—")
        features_layout.addRow("Oscillation Score:", self.oscillation_label)
        
        features_group.setLayout(features_layout)
        content_layout.addWidget(features_group)
        
        # Metadata
        metadata_group = QGroupBox("Metadata")
        metadata_layout = QFormLayout()
        metadata_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        self.created_label = QLabel("—")
        metadata_layout.addRow("Created:", self.created_label)
        
        self.modified_label = QLabel("—")
        metadata_layout.addRow("Last Modified:", self.modified_label)
        
        self.crosses_gap_label = QLabel("—")
        metadata_layout.addRow("Crosses Gap:", self.crosses_gap_label)
        
        self.notes_label = QLabel("—")
        self.notes_label.setWordWrap(True)
        self.notes_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        metadata_layout.addRow("Notes:", self.notes_label)
        
        metadata_group.setLayout(metadata_layout)
        content_layout.addWidget(metadata_group)
        
        # Add stretch at bottom
        content_layout.addStretch()
        
        scroll.setWidget(content)
        layout.addWidget(scroll)
    
    def set_event(self, event: Optional[Event]):
        """Set event to display.
        
        Args:
            event: Event object or None to clear
        """
        self.current_event = event
        
        if event is None:
            self._clear_info()
            return
        
        # Event Identity - show short UUID for now (human-friendly ID will be shown in table)
        short_id = event.event_id[:8] if event.event_id else "—"
        self.event_id_label.setText(f"{short_id}... (UUID)")
        self.source_label.setText(event.source or "—")
        self.label_label.setText(event.label_user or "Unlabeled")
        self.locked_label.setText("Yes" if event.locked else "No")
        self.needs_manual_label.setText("Yes" if event.needs_manual else "No")
        
        # Timing
        self.start_time_label.setText(f"{event.start_time_s:.3f} s")
        self.end_time_label.setText(f"{event.end_time_s:.3f} s")
        self.duration_label.setText(f"{event.duration_s():.3f} s ({event.duration_s()/60:.2f} min)")
        
        # Features
        if event.features:
            f = event.features
            self.delta_mass_label.setText(f"{f.delta_mass_g:.4f} g" if f.delta_mass_g is not None else "—")
            self.peak_slope_label.setText(f"{f.peak_slope_g_per_s:.4f} g/s" if f.peak_slope_g_per_s is not None else "—")
            self.mean_slope_label.setText(f"{f.mean_slope_g_per_s:.4f} g/s" if f.mean_slope_g_per_s is not None else "—")
            self.oscillation_label.setText(f"{f.oscillation_score:.4f}" if f.oscillation_score is not None else "—")
        else:
            self.delta_mass_label.setText("—")
            self.peak_slope_label.setText("—")
            self.mean_slope_label.setText("—")
            self.oscillation_label.setText("—")
        
        # Metadata
        self.created_label.setText(event.created_at or "—")
        self.modified_label.setText(event.modified_at or "—")
        if event.features:
            self.crosses_gap_label.setText("Yes" if event.features.crosses_gap else "No")
        else:
            self.crosses_gap_label.setText("—")
        self.notes_label.setText(event.notes or "—")
    
    def _clear_info(self):
        """Clear all info fields."""
        labels = [
            self.event_id_label, self.source_label, self.label_label,
            self.locked_label, self.needs_manual_label,
            self.start_time_label, self.end_time_label, self.duration_label,
            self.delta_mass_label, self.peak_slope_label, self.oscillation_label, 
            self.plateau_label, self.coverage_label,
            self.created_label, self.modified_label, self.crosses_gap_label, self.notes_label
        ]
        
        for label in labels:
            label.setText("—")
