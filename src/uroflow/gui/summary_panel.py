"""Project summary panel widget."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QScrollArea,
    QGroupBox, QFrame
)
from PySide6.QtCore import Qt
from typing import Optional, List
import numpy as np

from uroflow.core.types import Event


class SummaryPanel(QWidget):
    """Panel to display project-wide summary statistics."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.events = []
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
        
        # Event Counts
        counts_group = QGroupBox("Event Counts")
        counts_layout = QFormLayout()
        counts_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        self.total_events_label = QLabel("—")
        counts_layout.addRow("Total Events:", self.total_events_label)
        
        self.urine_events_label = QLabel("—")
        counts_layout.addRow("Urine Events:", self.urine_events_label)
        
        self.feces_events_label = QLabel("—")
        counts_layout.addRow("Feces Events:", self.feces_events_label)
        
        self.bad_events_label = QLabel("—")
        counts_layout.addRow("Bad Events:", self.bad_events_label)
        
        self.unlabeled_events_label = QLabel("—")
        counts_layout.addRow("Unlabeled Events:", self.unlabeled_events_label)
        
        counts_group.setLayout(counts_layout)
        content_layout.addWidget(counts_group)
        
        # Mass Statistics
        mass_group = QGroupBox("Mass Statistics")
        mass_layout = QFormLayout()
        mass_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        self.total_urine_mass_label = QLabel("—")
        mass_layout.addRow("Total Urine Mass:", self.total_urine_mass_label)
        
        self.avg_urine_mass_label = QLabel("—")
        mass_layout.addRow("Avg Urine Mass:", self.avg_urine_mass_label)
        
        self.total_feces_mass_label = QLabel("—")
        mass_layout.addRow("Total Feces Mass:", self.total_feces_mass_label)
        
        self.avg_feces_mass_label = QLabel("—")
        mass_layout.addRow("Avg Feces Mass:", self.avg_feces_mass_label)
        
        self.total_combined_mass_label = QLabel("—")
        mass_layout.addRow("Total Mass (U+F):", self.total_combined_mass_label)
        
        mass_group.setLayout(mass_layout)
        content_layout.addWidget(mass_group)
        
        # Duration Statistics
        duration_group = QGroupBox("Duration Statistics")
        duration_layout = QFormLayout()
        duration_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        self.avg_urine_duration_label = QLabel("—")
        duration_layout.addRow("Avg Urine Duration:", self.avg_urine_duration_label)
        
        self.avg_feces_duration_label = QLabel("—")
        duration_layout.addRow("Avg Feces Duration:", self.avg_feces_duration_label)
        
        self.total_event_duration_label = QLabel("—")
        duration_layout.addRow("Total Event Duration:", self.total_event_duration_label)
        
        duration_group.setLayout(duration_layout)
        content_layout.addWidget(duration_group)
        
        # Add stretch at bottom
        content_layout.addStretch()
        
        scroll.setWidget(content)
        layout.addWidget(scroll)
    
    def set_events(self, events: Optional[List[Event]]):
        """Set events to compute summary statistics.
        
        Args:
            events: List of Event objects or None to clear
        """
        self.events = events or []
        
        if not self.events:
            self._clear_summary()
            return
        
        # Compute statistics
        total_events = len(self.events)
        
        # Event counts by label
        urine_events = [e for e in self.events if e.label_user == "urine"]
        feces_events = [e for e in self.events if e.label_user == "feces"]
        bad_events = [e for e in self.events if e.label_user == "bad"]
        unlabeled_events = [e for e in self.events if not e.label_user or e.label_user == ""]
        
        n_urine = len(urine_events)
        n_feces = len(feces_events)
        n_bad = len(bad_events)
        n_unlabeled = len(unlabeled_events)
        
        # Mass statistics
        urine_masses = [e.features.delta_mass_g for e in urine_events 
                       if e.features and np.isfinite(e.features.delta_mass_g)]
        feces_masses = [e.features.delta_mass_g for e in feces_events 
                       if e.features and np.isfinite(e.features.delta_mass_g)]
        
        total_urine_mass = sum(urine_masses) if urine_masses else 0.0
        total_feces_mass = sum(feces_masses) if feces_masses else 0.0
        total_combined_mass = total_urine_mass + total_feces_mass
        
        avg_urine_mass = np.mean(urine_masses) if urine_masses else 0.0
        avg_feces_mass = np.mean(feces_masses) if feces_masses else 0.0
        
        # Duration statistics
        urine_durations = [e.duration_s() for e in urine_events]
        feces_durations = [e.duration_s() for e in feces_events]
        all_durations = [e.duration_s() for e in self.events]
        
        avg_urine_duration = np.mean(urine_durations) if urine_durations else 0.0
        avg_feces_duration = np.mean(feces_durations) if feces_durations else 0.0
        total_event_duration = sum(all_durations) if all_durations else 0.0
        
        # Update labels - Event Counts
        self.total_events_label.setText(f"{total_events}")
        self.urine_events_label.setText(f"{n_urine} ({n_urine/total_events*100:.1f}%)" if total_events > 0 else "0")
        self.feces_events_label.setText(f"{n_feces} ({n_feces/total_events*100:.1f}%)" if total_events > 0 else "0")
        self.bad_events_label.setText(f"{n_bad} ({n_bad/total_events*100:.1f}%)" if total_events > 0 else "0")
        self.unlabeled_events_label.setText(f"{n_unlabeled} ({n_unlabeled/total_events*100:.1f}%)" if total_events > 0 else "0")
        
        # Update labels - Mass Statistics
        self.total_urine_mass_label.setText(f"{total_urine_mass:.3f} g")
        self.avg_urine_mass_label.setText(f"{avg_urine_mass:.3f} g" if n_urine > 0 else "—")
        self.total_feces_mass_label.setText(f"{total_feces_mass:.3f} g")
        self.avg_feces_mass_label.setText(f"{avg_feces_mass:.3f} g" if n_feces > 0 else "—")
        self.total_combined_mass_label.setText(f"{total_combined_mass:.3f} g")
        
        # Update labels - Duration Statistics
        self.avg_urine_duration_label.setText(
            f"{avg_urine_duration:.2f} s ({avg_urine_duration/60:.2f} min)" if n_urine > 0 else "—"
        )
        self.avg_feces_duration_label.setText(
            f"{avg_feces_duration:.2f} s ({avg_feces_duration/60:.2f} min)" if n_feces > 0 else "—"
        )
        self.total_event_duration_label.setText(
            f"{total_event_duration:.2f} s ({total_event_duration/60:.2f} min, {total_event_duration/3600:.2f} hr)"
        )
    
    def _clear_summary(self):
        """Clear all summary fields."""
        labels = [
            self.total_events_label, self.urine_events_label, self.feces_events_label,
            self.bad_events_label, self.unlabeled_events_label,
            self.total_urine_mass_label, self.avg_urine_mass_label,
            self.total_feces_mass_label, self.avg_feces_mass_label,
            self.total_combined_mass_label,
            self.avg_urine_duration_label, self.avg_feces_duration_label,
            self.total_event_duration_label
        ]
        
        for label in labels:
            label.setText("—")
