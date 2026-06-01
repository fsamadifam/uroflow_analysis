"""Spatial analysis visualization dialog."""

import numpy as np
from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QFileDialog, QMessageBox, QTabWidget,
    QWidget, QFormLayout,
)
from PySide6.QtCore import Qt

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Circle

from uroflow.core.types import Event
from uroflow.spatial.calibration import CalibrationData
from uroflow.spatial.analysis import (
    get_spatial_events,
    extract_coordinates,
    create_spatial_heatmap,
    compute_radial_distribution,
    compute_angular_distribution,
    compute_spatial_statistics,
    export_spatial_csv,
)


class SpatialAnalysisDialog(QDialog):
    """Dialog showing spatial analysis of annotated event locations."""

    def __init__(
        self,
        events: List[Event],
        calibration: Optional[CalibrationData] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Spatial Analysis")
        self.resize(900, 700)

        self._events = events
        self._calibration = calibration
        self._cage_radius_cm = 20.0

        if calibration and calibration.is_valid():
            if calibration.method == "ellipse" and calibration.ellipse:
                self._cage_radius_cm = calibration.ellipse.cage_radius_cm
            elif calibration.method == "homography" and calibration.homography:
                self._cage_radius_cm = calibration.homography.cage_radius_cm

        self._setup_ui()
        self._update_plots()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Controls
        controls_layout = QHBoxLayout()

        controls_layout.addWidget(QLabel("Filter:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["All Events", "Urine Only", "Feces Only"])
        self._filter_combo.currentTextChanged.connect(self._update_plots)
        controls_layout.addWidget(self._filter_combo)

        controls_layout.addStretch()

        export_btn = QPushButton("Export CSV...")
        export_btn.clicked.connect(self._export_csv)
        controls_layout.addWidget(export_btn)

        save_plot_btn = QPushButton("Save Plot...")
        save_plot_btn.clicked.connect(self._save_plot)
        controls_layout.addWidget(save_plot_btn)

        layout.addLayout(controls_layout)

        # Tab widget for different visualizations
        self._tabs = QTabWidget()

        # Tab 1: Scatter plot / map
        self._scatter_fig = Figure(figsize=(6, 6), dpi=100)
        self._scatter_canvas = FigureCanvas(self._scatter_fig)
        self._tabs.addTab(self._scatter_canvas, "Event Map")

        # Tab 2: Heatmap
        self._heatmap_fig = Figure(figsize=(6, 6), dpi=100)
        self._heatmap_canvas = FigureCanvas(self._heatmap_fig)
        self._tabs.addTab(self._heatmap_canvas, "Heatmap")

        # Tab 3: Distributions
        self._dist_fig = Figure(figsize=(8, 4), dpi=100)
        self._dist_canvas = FigureCanvas(self._dist_fig)
        self._tabs.addTab(self._dist_canvas, "Distributions")

        layout.addWidget(self._tabs)

        # Statistics panel
        stats_group = QGroupBox("Summary Statistics")
        stats_layout = QFormLayout(stats_group)
        self._stats_labels = {}
        for key in ["n_events", "mean_radius", "std_radius", "center_of_mass", "periphery"]:
            label = QLabel("-")
            stats_layout.addRow(f"{key.replace('_', ' ').title()}:", label)
            self._stats_labels[key] = label
        layout.addWidget(stats_group)

        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _get_label_filter(self) -> Optional[str]:
        text = self._filter_combo.currentText()
        if text == "Urine Only":
            return "urine"
        elif text == "Feces Only":
            return "feces"
        return None

    def _update_plots(self):
        label_filter = self._get_label_filter()
        radius = self._cage_radius_cm

        filtered = get_spatial_events(self._events, label_filter)
        x, y = extract_coordinates(filtered)

        self._draw_scatter(x, y, filtered, radius)
        self._draw_heatmap(filtered, radius, label_filter)
        self._draw_distributions(filtered, radius, label_filter)
        self._update_statistics(filtered, radius, label_filter)

    def _draw_scatter(self, x: np.ndarray, y: np.ndarray, events: List[Event], radius: float):
        self._scatter_fig.clear()
        ax = self._scatter_fig.add_subplot(111, aspect="equal")

        # Draw cage boundary
        cage_circle = Circle((0, 0), radius, fill=False, edgecolor="black", linewidth=2)
        ax.add_patch(cage_circle)

        # Draw concentric guides
        for r in np.linspace(radius / 4, radius, 4):
            guide = Circle((0, 0), r, fill=False, edgecolor="gray", linewidth=0.5, linestyle="--")
            ax.add_patch(guide)

        # Plot events with color by label
        if len(x) > 0:
            colors = []
            for e in events:
                if e.label_user == "urine":
                    colors.append("#FFB000")
                elif e.label_user == "feces":
                    colors.append("#5C2E00")
                else:
                    colors.append("#808080")

            ax.scatter(x, y, c=colors, s=60, edgecolors="black", linewidths=0.5, zorder=5)

        ax.set_xlim(-radius * 1.15, radius * 1.15)
        ax.set_ylim(-radius * 1.15, radius * 1.15)
        ax.set_xlabel("X (cm)")
        ax.set_ylabel("Y (cm)")
        ax.set_title(f"Event Locations (n={len(x)})")
        ax.axhline(0, color="lightgray", linewidth=0.5)
        ax.axvline(0, color="lightgray", linewidth=0.5)

        self._scatter_fig.tight_layout()
        self._scatter_canvas.draw()

    def _draw_heatmap(self, events: List[Event], radius: float, label_filter: Optional[str]):
        self._heatmap_fig.clear()
        ax = self._heatmap_fig.add_subplot(111, aspect="equal")

        X, Y, Z = create_spatial_heatmap(
            self._events, radius, resolution=50, sigma_cm=2.0, label_filter=label_filter
        )

        if np.nanmax(Z) > 0:
            im = ax.pcolormesh(X, Y, Z, cmap="hot", shading="auto")
            self._heatmap_fig.colorbar(im, ax=ax, label="Density")

        cage_circle = Circle((0, 0), radius, fill=False, edgecolor="white", linewidth=2)
        ax.add_patch(cage_circle)

        ax.set_xlim(-radius * 1.1, radius * 1.1)
        ax.set_ylim(-radius * 1.1, radius * 1.1)
        ax.set_xlabel("X (cm)")
        ax.set_ylabel("Y (cm)")
        ax.set_title("Event Density Heatmap")
        ax.set_facecolor("black")

        self._heatmap_fig.tight_layout()
        self._heatmap_canvas.draw()

    def _draw_distributions(self, events: List[Event], radius: float, label_filter: Optional[str]):
        self._dist_fig.clear()

        # Radial distribution
        ax1 = self._dist_fig.add_subplot(121)
        centers, counts = compute_radial_distribution(
            self._events, radius, n_bins=8, label_filter=label_filter
        )
        ax1.bar(centers, counts, width=radius / 8 * 0.8, color="#2196F3", edgecolor="black")
        ax1.set_xlabel("Distance from center (cm)")
        ax1.set_ylabel("Count")
        ax1.set_title("Radial Distribution")

        # Angular distribution (polar)
        ax2 = self._dist_fig.add_subplot(122, projection="polar")
        sector_centers, sector_counts = compute_angular_distribution(
            self._events, n_sectors=8, label_filter=label_filter
        )
        theta = np.radians(sector_centers)
        width = 2 * np.pi / len(sector_centers)
        ax2.bar(theta, sector_counts, width=width * 0.9, color="#FF9800", edgecolor="black", alpha=0.7)
        ax2.set_title("Angular Distribution", pad=15)

        self._dist_fig.tight_layout()
        self._dist_canvas.draw()

    def _update_statistics(self, events: List[Event], radius: float, label_filter: Optional[str]):
        stats = compute_spatial_statistics(self._events, radius, label_filter)

        self._stats_labels["n_events"].setText(str(stats["n_events"]))
        self._stats_labels["mean_radius"].setText(f"{stats['mean_radius_cm']:.2f} cm")
        self._stats_labels["std_radius"].setText(f"{stats['std_radius_cm']:.2f} cm")
        cx, cy = stats["center_of_mass"]
        self._stats_labels["center_of_mass"].setText(f"({cx:.2f}, {cy:.2f}) cm")
        self._stats_labels["periphery"].setText(f"{stats['periphery_fraction']:.1%}")

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Spatial CSV", "spatial_events.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return

        calibration_dict = self._calibration.to_dict() if self._calibration else None
        n = export_spatial_csv(
            self._events,
            path,
            spatial_calibration=calibration_dict,
        )
        QMessageBox.information(
            self, "Export Complete",
            f"Exported {n} events with spatial coordinates to:\n{path}"
        )

    def _save_plot(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Plot", "spatial_analysis.png",
            "PNG Images (*.png);;PDF (*.pdf);;All Files (*)"
        )
        if not path:
            return

        current_tab = self._tabs.currentIndex()
        if current_tab == 0:
            self._scatter_fig.savefig(path, dpi=150, bbox_inches="tight")
        elif current_tab == 1:
            self._heatmap_fig.savefig(path, dpi=150, bbox_inches="tight")
        elif current_tab == 2:
            self._dist_fig.savefig(path, dpi=150, bbox_inches="tight")

        QMessageBox.information(self, "Saved", f"Plot saved to:\n{path}")
