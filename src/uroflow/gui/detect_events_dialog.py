"""Dialog for configuring and running event detection."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QDialogButtonBox, QGroupBox, QFormLayout,
    QCheckBox, QSpinBox
)
from PySide6.QtCore import Qt

from uroflow.core.types import DetectionParams


class DetectEventsDialog(QDialog):
    """Dialog for configuring event detection parameters."""
    
    def __init__(self, current_params: DetectionParams = None, parent=None):
        """Initialize the dialog.
        
        Args:
            current_params: Current detection parameters (or None for defaults)
            parent: Parent widget
        """
        super().__init__(parent)
        
        # Use defaults if no params provided
        self.params = current_params or DetectionParams.default()
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the dialog UI."""
        self.setWindowTitle("Detect Events")
        self.setMinimumWidth(450)
        
        layout = QVBoxLayout(self)
        
        # Info label
        info_label = QLabel(
            "Configure parameters for automatic event detection.\n"
            "Leave as defaults for typical uroflowmetry data."
        )
        info_label.setStyleSheet("color: #666; margin-bottom: 10px;")
        layout.addWidget(info_label)
        
        # Detection Parameters Group
        detect_group = QGroupBox("Detection Threshold Parameters")
        detect_layout = QFormLayout()
        
        # Rolling Window Duration
        self.diff_test_time_spin = QDoubleSpinBox()
        self.diff_test_time_spin.setRange(1.0, 30.0)
        self.diff_test_time_spin.setValue(self.params.diff_test_time_s)
        self.diff_test_time_spin.setDecimals(1)
        self.diff_test_time_spin.setSuffix(" s")
        self.diff_test_time_spin.setSingleStep(0.5)
        self.diff_test_time_spin.setToolTip(
            "Duration of rolling window for computing mass change.\n"
            "Larger values smooth out noise but may miss fast events."
        )
        detect_layout.addRow("Rolling Window:", self.diff_test_time_spin)
        
        # Mass Change Threshold
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.01, 1.0)
        self.threshold_spin.setValue(self.params.threshold_g)
        self.threshold_spin.setDecimals(3)
        self.threshold_spin.setSuffix(" g")
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setToolTip(
            "Minimum mass change (in grams) to trigger event detection.\n"
            "Lower values detect more events (including noise)."
        )
        detect_layout.addRow("Mass Threshold:", self.threshold_spin)
        
        detect_group.setLayout(detect_layout)
        layout.addWidget(detect_group)
        
        # Event Filtering Group
        filter_group = QGroupBox("Event Filtering Parameters")
        filter_layout = QFormLayout()
        
        # Minimum Event Duration
        self.min_event_len_spin = QDoubleSpinBox()
        self.min_event_len_spin.setRange(0.5, 30.0)
        self.min_event_len_spin.setValue(self.params.min_event_len_s)
        self.min_event_len_spin.setDecimals(1)
        self.min_event_len_spin.setSuffix(" s")
        self.min_event_len_spin.setSingleStep(0.5)
        self.min_event_len_spin.setToolTip(
            "Minimum event duration. Events shorter than this are discarded."
        )
        filter_layout.addRow("Min Event Duration:", self.min_event_len_spin)
        
        # Maximum Event Duration
        self.max_event_len_spin = QDoubleSpinBox()
        self.max_event_len_spin.setRange(5.0, 300.0)
        self.max_event_len_spin.setValue(self.params.max_event_len_s)
        self.max_event_len_spin.setDecimals(1)
        self.max_event_len_spin.setSuffix(" s")
        self.max_event_len_spin.setSingleStep(5.0)
        self.max_event_len_spin.setToolTip(
            "Maximum event duration. Events longer than this are discarded.\n"
            "Helps filter out long artifacts (e.g., evaporation over hours)."
        )
        filter_layout.addRow("Max Event Duration:", self.max_event_len_spin)
        
        # Gap Merge Distance
        self.min_gap_merge_spin = QDoubleSpinBox()
        self.min_gap_merge_spin.setRange(0.1, 10.0)
        self.min_gap_merge_spin.setValue(self.params.min_gap_merge_s)
        self.min_gap_merge_spin.setDecimals(1)
        self.min_gap_merge_spin.setSuffix(" s")
        self.min_gap_merge_spin.setSingleStep(0.5)
        self.min_gap_merge_spin.setToolTip(
            "Maximum gap between detections to merge into single event.\n"
            "Events separated by less than this are combined."
        )
        filter_layout.addRow("Merge Gap:", self.min_gap_merge_spin)
        
        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)
        
        # Advanced Parameters Group (collapsed by default)
        advanced_group = QGroupBox("Advanced Parameters")
        advanced_layout = QFormLayout()
        
        # Minimum Valid Fraction
        self.min_valid_frac_spin = QDoubleSpinBox()
        self.min_valid_frac_spin.setRange(0.5, 1.0)
        self.min_valid_frac_spin.setValue(self.params.min_valid_frac)
        self.min_valid_frac_spin.setDecimals(2)
        self.min_valid_frac_spin.setSingleStep(0.05)
        self.min_valid_frac_spin.setToolTip(
            "Minimum fraction of valid (non-NaN) samples required\n"
            "in rolling window for computation."
        )
        advanced_layout.addRow("Min Valid Fraction:", self.min_valid_frac_spin)
        
        advanced_group.setLayout(advanced_layout)
        layout.addWidget(advanced_group)
        
        # Classification Parameters Group
        classify_group = QGroupBox("Classification Parameters")
        classify_layout = QFormLayout()
        
        # Urine minimum mass
        self.urine_min_mass_spin = QDoubleSpinBox()
        self.urine_min_mass_spin.setRange(0.01, 10.0)
        self.urine_min_mass_spin.setValue(0.1)
        self.urine_min_mass_spin.setDecimals(3)
        self.urine_min_mass_spin.setSuffix(" g")
        self.urine_min_mass_spin.setSingleStep(0.01)
        self.urine_min_mass_spin.setToolTip(
            "Minimum mass change (grams) for urine classification.\n"
            "Urine events typically have gradual ramp-like mass increases."
        )
        classify_layout.addRow("Urine Min Mass:", self.urine_min_mass_spin)
        
        # Feces minimum mass
        self.feces_min_mass_spin = QDoubleSpinBox()
        self.feces_min_mass_spin.setRange(0.01, 10.0)
        self.feces_min_mass_spin.setValue(0.05)
        self.feces_min_mass_spin.setDecimals(3)
        self.feces_min_mass_spin.setSuffix(" g")
        self.feces_min_mass_spin.setSingleStep(0.01)
        self.feces_min_mass_spin.setToolTip(
            "Minimum mass change (grams) for feces classification.\n"
            "Feces events typically have sudden jump-like mass increases."
        )
        classify_layout.addRow("Feces Min Mass:", self.feces_min_mass_spin)
        
        # Slope ratio threshold
        self.slope_ratio_spin = QDoubleSpinBox()
        self.slope_ratio_spin.setRange(1.0, 10.0)
        self.slope_ratio_spin.setValue(2.5)
        self.slope_ratio_spin.setDecimals(2)
        self.slope_ratio_spin.setSingleStep(0.1)
        self.slope_ratio_spin.setToolTip(
            "Slope ratio threshold for classification.\n"
            "Below this = urine (gradual ramp), Above = feces (sudden jump).\n"
            "Ratio = peak_slope / average_slope"
        )
        classify_layout.addRow("Slope Ratio Threshold:", self.slope_ratio_spin)
        
        classify_group.setLayout(classify_layout)
        layout.addWidget(classify_group)
        
        # Options Group
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout()
        
        self.clear_existing_check = QCheckBox("Clear existing auto-detected events before detection")
        self.clear_existing_check.setChecked(True)
        self.clear_existing_check.setToolTip(
            "If checked, removes all existing auto-detected events before running.\n"
            "Manual and acquisition events are preserved."
        )
        options_layout.addWidget(self.clear_existing_check)
        
        self.use_acquisition_check = QCheckBox("Also detect from acquisition flags (if present)")
        self.use_acquisition_check.setChecked(True)
        self.use_acquisition_check.setToolTip(
            "If checked, creates events from acquisition system flags\n"
            "in addition to auto-detection."
        )
        options_layout.addWidget(self.use_acquisition_check)
        
        self.auto_classify_check = QCheckBox("Auto-classify events as urine/feces (heuristic)")
        self.auto_classify_check.setChecked(True)
        self.auto_classify_check.setToolTip(
            "If checked, applies simple rule-based classification:\n"
            "• Urine: Mass gain ≥0.3g, duration ≥3s, smooth slope\n"
            "• Feces: Mass gain <0.5g, duration <5s, stable plateau\n"
            "Uncertain events are flagged for manual review."
        )
        options_layout.addWidget(self.auto_classify_check)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # Spacer
        layout.addStretch()
        
        # Reset to defaults button
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._reset_to_defaults)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addWidget(reset_btn)
        button_layout.addStretch()
        
        self.detect_btn = QPushButton("Detect Events")
        self.detect_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 8px 20px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.detect_btn.clicked.connect(self.accept)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(self.detect_btn)
        
        layout.addLayout(button_layout)
    
    def _reset_to_defaults(self):
        """Reset all parameters to default values."""
        defaults = DetectionParams.default()
        
        self.diff_test_time_spin.setValue(defaults.diff_test_time_s)
        self.threshold_spin.setValue(defaults.threshold_g)
        self.min_event_len_spin.setValue(defaults.min_event_len_s)
        self.max_event_len_spin.setValue(defaults.max_event_len_s)
        self.min_gap_merge_spin.setValue(defaults.min_gap_merge_s)
        self.min_valid_frac_spin.setValue(defaults.min_valid_frac)
    
    def get_detection_params(self) -> DetectionParams:
        """Get the configured detection parameters.
        
        Returns:
            DetectionParams with user-configured values
        """
        return DetectionParams(
            diff_test_time_s=self.diff_test_time_spin.value(),
            threshold_g=self.threshold_spin.value(),
            min_event_len_s=self.min_event_len_spin.value(),
            max_event_len_s=self.max_event_len_spin.value(),
            min_gap_merge_s=self.min_gap_merge_spin.value(),
            min_valid_frac=self.min_valid_frac_spin.value()
        )
    
    def should_clear_existing(self) -> bool:
        """Check if existing auto events should be cleared."""
        return self.clear_existing_check.isChecked()
    
    def should_use_acquisition(self) -> bool:
        """Check if acquisition flags should be used."""
        return self.use_acquisition_check.isChecked()
    
    def should_auto_classify(self) -> bool:
        """Check if auto-classification should be applied."""
        return self.auto_classify_check.isChecked()
    
    def get_classification_params(self) -> dict:
        """Get classification parameters.
        
        Returns:
            Dictionary with classification parameters
        """
        return {
            'urine_min_mass_g': self.urine_min_mass_spin.value(),
            'feces_min_mass_g': self.feces_min_mass_spin.value(),
            'slope_ratio_threshold': self.slope_ratio_spin.value()
        }
