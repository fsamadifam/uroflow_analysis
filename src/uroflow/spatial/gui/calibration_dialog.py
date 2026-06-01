"""Interactive calibration dialog for spatial coordinate mapping."""

import numpy as np
from pathlib import Path
from typing import Optional, List, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QGroupBox, QFileDialog,
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
    QGraphicsPixmapItem, QGraphicsPathItem, QStatusBar,
    QMessageBox, QSplitter, QWidget, QFormLayout,
)
from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import (
    QPixmap, QPen, QColor, QBrush, QPainterPath, QTransform,
)

from uroflow.spatial.frame_extractor import (
    extract_first_frame,
    extract_frame_at_time,
    frame_to_qpixmap,
    get_video_info,
)
from uroflow.spatial.calibration import (
    CalibrationData,
    EllipseCalibration,
)
from uroflow.spatial.transform import (
    fit_ellipse_to_points,
    generate_ellipse_overlay_points,
    generate_grid_overlay,
    transform_point,
    point_to_polar,
)


class ClickableGraphicsView(QGraphicsView):
    """QGraphicsView that emits click positions in scene coordinates.

    Left-click to place a point (crosshair cursor).
    Middle-click + drag or Ctrl+left-click + drag to pan.
    Scroll wheel to zoom.
    """

    point_clicked = Signal(float, float)
    point_right_clicked = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setCursor(Qt.CrossCursor)
        self._panning = False
        self._pan_start = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier
        ):
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        elif event.button() == Qt.LeftButton and event.modifiers() == Qt.NoModifier:
            scene_pos = self.mapToScene(event.pos())
            self.point_clicked.emit(scene_pos.x(), scene_pos.y())
        elif event.button() == Qt.RightButton:
            scene_pos = self.mapToScene(event.pos())
            self.point_right_clicked.emit(scene_pos.x(), scene_pos.y())
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            self._pan_start = None
            self.setCursor(Qt.CrossCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(factor, factor)
        else:
            self.scale(1.0 / factor, 1.0 / factor)


class CalibrationDialog(QDialog):
    """Dialog for interactive spatial calibration of cage camera view."""

    calibration_saved = Signal(object)  # CalibrationData

    def __init__(self, video_folder: str = "", config_path: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Spatial Calibration")
        self.resize(1200, 800)

        self._video_folder = video_folder
        self._config_path = config_path
        self._frame: Optional[np.ndarray] = None
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._clicked_points: List[Tuple[float, float]] = []
        self._point_items: List[QGraphicsEllipseItem] = []
        self._ellipse_overlay: Optional[QGraphicsPathItem] = None
        self._grid_overlays: List[QGraphicsPathItem] = []
        self._current_calibration: Optional[CalibrationData] = None
        self._calibration_frame_path = ""

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Top controls - compact single row
        top_layout = QHBoxLayout()

        self._load_btn = QPushButton("Select Video...")
        self._load_btn.clicked.connect(self._load_video_frame)
        top_layout.addWidget(self._load_btn)
        
        self._frame_label = QLabel("No frame loaded")
        self._frame_label.setStyleSheet("color: #666;")
        top_layout.addWidget(self._frame_label)
        
        top_layout.addSpacing(20)
        
        top_layout.addWidget(QLabel("Cage radius:"))
        self._radius_spin = QDoubleSpinBox()
        self._radius_spin.setRange(1.0, 100.0)
        self._radius_spin.setValue(20.0)
        self._radius_spin.setSuffix(" cm")
        self._radius_spin.setDecimals(1)
        top_layout.addWidget(self._radius_spin)

        top_layout.addStretch()
        layout.addLayout(top_layout)

        # Main splitter: image view and reference/instructions
        splitter = QSplitter(Qt.Horizontal)

        # Image view (left)
        image_widget = QWidget()
        image_layout = QVBoxLayout(image_widget)
        image_layout.setContentsMargins(0, 0, 0, 0)

        self._scene = QGraphicsScene()
        self._view = ClickableGraphicsView()
        self._view.setScene(self._scene)
        self._view.point_clicked.connect(self._on_point_clicked)
        self._view.point_right_clicked.connect(self._on_right_click)
        image_layout.addWidget(self._view)
        splitter.addWidget(image_widget)

        # Right panel: reference circle (for homography) or instructions
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 4, 4, 4)

        self._instructions_label = QLabel()
        self._instructions_label.setWordWrap(True)
        self._instructions_label.setStyleSheet(
            "padding: 8px; background: #f0f0f0; border-radius: 4px; color: #333;"
        )
        self._instructions_label.setText(
            "ELLIPSE CALIBRATION\n\n"
            "Click 5 or more points along the visible edge of the "
            "circular cage grating.\n\n"
            "Tips:\n"
            "• Spread points evenly along the visible arc\n"
            "• You only need the visible portion (occlusion is OK)\n"
            "• More points = better fit\n"
            "• Right-click to test a point after fitting\n"
            "• Scroll to zoom, middle-click or Ctrl+drag to pan"
        )
        right_layout.addWidget(self._instructions_label)

        # Point list display
        self._points_label = QLabel("Points: 0")
        self._points_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(self._points_label)

        # Test area
        self._test_label = QLabel("")
        self._test_label.setWordWrap(True)
        self._test_label.setStyleSheet("color: #333; font-size: 11px;")
        right_layout.addWidget(self._test_label)

        right_layout.addStretch()
        splitter.addWidget(right_widget)

        splitter.setSizes([1000, 250])
        layout.addWidget(splitter)

        # Bottom buttons
        btn_layout = QHBoxLayout()

        self._clear_btn = QPushButton("Clear Points")
        self._clear_btn.clicked.connect(self._clear_points)
        btn_layout.addWidget(self._clear_btn)

        self._undo_btn = QPushButton("Undo Last Point")
        self._undo_btn.clicked.connect(self._undo_last_point)
        btn_layout.addWidget(self._undo_btn)

        btn_layout.addStretch()

        self._fit_btn = QPushButton("Fit && Preview")
        self._fit_btn.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; "
            "font-weight: bold; padding: 6px 20px; }"
        )
        self._fit_btn.clicked.connect(self._fit_and_preview)
        btn_layout.addWidget(self._fit_btn)

        self._save_btn = QPushButton("Save Calibration")
        self._save_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-weight: bold; padding: 6px 20px; }"
        )
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_calibration)
        btn_layout.addWidget(self._save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        # Status bar
        self._status = QStatusBar()
        layout.addWidget(self._status)

    # --- Frame Loading ---

    def _load_video_frame(self):
        """Open file dialog to select video and extract first frame."""
        start_dir = self._video_folder if self._video_folder else ""
        video_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video for Calibration",
            start_dir,
            "Video Files (*.mkv *.mp4 *.avi *.mov *.webm);;All Files (*)",
        )
        if not video_path:
            return

        self._status.showMessage("Extracting frame...")
        frame = extract_first_frame(video_path)
        if frame is None:
            QMessageBox.warning(
                self, "Error", f"Could not extract frame from:\n{video_path}"
            )
            self._status.clearMessage()
            return

        self._frame = frame
        self._calibration_frame_path = video_path
        self._display_frame(frame)
        self._frame_label.setText(Path(video_path).name)
        self._status.showMessage(
            f"Frame loaded: {frame.shape[1]}x{frame.shape[0]}", 3000
        )
        self._clear_points()

    def _display_frame(self, frame: np.ndarray):
        """Display frame in the graphics view."""
        pixmap = frame_to_qpixmap(frame)
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        self._point_items.clear()
        self._ellipse_overlay = None
        self._grid_overlays.clear()

    # --- Point Interaction ---

    def _on_point_clicked(self, x: float, y: float):
        """Handle left-click on the image to add a calibration point."""
        if self._frame is None:
            return

        self._add_point(x, y)

    def _on_right_click(self, x: float, y: float):
        """Right-click to test transformation at a point."""
        if self._current_calibration is None or not self._current_calibration.is_valid():
            self._test_label.setText("No valid calibration yet. Fit first.")
            return

        result = transform_point(x, y, self._current_calibration)
        if result is None:
            self._test_label.setText("Transform failed.")
            return

        x_cm, y_cm = result
        r_cm, theta = point_to_polar(x_cm, y_cm)
        radius_cm = self._radius_spin.value()
        inside = "INSIDE" if r_cm <= radius_cm else "OUTSIDE"

        self._test_label.setText(
            f"Test point ({x:.0f}, {y:.0f}) px\n"
            f"  -> ({x_cm:.2f}, {y_cm:.2f}) cm\n"
            f"  -> r={r_cm:.2f} cm, theta={theta:.1f} deg\n"
            f"  [{inside} cage]"
        )

        # Draw test marker
        pen = QPen(QColor(0, 200, 200), 2)
        size = 10
        self._scene.addEllipse(x - size / 2, y - size / 2, size, size, pen)

    def _add_point(self, x: float, y: float):
        """Add a calibration point and draw marker."""
        self._clicked_points.append((x, y))

        # Draw point marker
        size = 8
        pen = QPen(QColor(255, 50, 50), 2)
        brush = QBrush(QColor(255, 50, 50, 100))
        item = self._scene.addEllipse(
            x - size / 2, y - size / 2, size, size, pen, brush
        )
        self._point_items.append(item)

        self._update_points_label()

    def _undo_last_point(self):
        """Remove the last added point."""
        if not self._clicked_points:
            return
        self._clicked_points.pop()
        if self._point_items:
            item = self._point_items.pop()
            self._scene.removeItem(item)
        self._update_points_label()

    def _clear_points(self):
        """Remove all calibration points."""
        self._clicked_points.clear()
        for item in self._point_items:
            self._scene.removeItem(item)
        self._point_items.clear()
        self._remove_overlays()
        self._current_calibration = None
        self._save_btn.setEnabled(False)
        self._update_points_label()
        self._test_label.setText("")

    def _update_points_label(self):
        n = len(self._clicked_points)
        needed = max(0, 5 - n)
        if needed > 0:
            self._points_label.setText(f"Points: {n} (need {needed} more)")
        else:
            self._points_label.setText(f"Points: {n} (ready to fit)")


    # --- Fitting ---

    def _fit_and_preview(self):
        """Fit calibration model to clicked points and show preview overlay."""
        cage_radius = self._radius_spin.value()
        self._fit_ellipse(cage_radius)

    def _fit_ellipse(self, cage_radius_cm: float):
        """Fit ellipse to clicked points."""
        if len(self._clicked_points) < 5:
            QMessageBox.warning(
                self, "Not Enough Points",
                f"Need at least 5 points for ellipse fitting.\n"
                f"Currently have {len(self._clicked_points)}."
            )
            return

        cal = fit_ellipse_to_points(self._clicked_points)
        if cal is None:
            QMessageBox.warning(
                self, "Fit Failed",
                "Ellipse fitting failed. Try adding more points or "
                "ensure they lie on the cage edge."
            )
            return

        cal.cage_radius_cm = cage_radius_cm

        self._current_calibration = CalibrationData(
            method="ellipse",
            ellipse=cal,
            calibration_frame_path=self._calibration_frame_path,
        )

        self._remove_overlays()
        self._draw_ellipse_overlay(cal)
        self._draw_grid_overlay()

        self._save_btn.setEnabled(True)
        self._status.showMessage(
            f"Ellipse fit: center=({cal.center_x:.0f}, {cal.center_y:.0f}), "
            f"axes=({cal.semi_major:.0f}, {cal.semi_minor:.0f}), "
            f"angle={np.degrees(cal.angle_rad):.1f} deg",
            5000,
        )

    # --- Overlay Drawing ---

    def _draw_ellipse_overlay(self, cal: EllipseCalibration):
        """Draw the fitted ellipse on the image."""
        points = generate_ellipse_overlay_points(cal)
        if len(points) < 2:
            return

        path = QPainterPath()
        path.moveTo(points[0, 0], points[0, 1])
        for i in range(1, len(points)):
            path.lineTo(points[i, 0], points[i, 1])
        path.closeSubpath()

        pen = QPen(QColor(0, 255, 0), 2)
        self._ellipse_overlay = self._scene.addPath(path, pen)

    def _draw_grid_overlay(self):
        """Draw transformation grid on the image."""
        if self._current_calibration is None:
            return

        lines = generate_grid_overlay(self._current_calibration)
        pen = QPen(QColor(0, 200, 255, 150), 1)

        for line_pts in lines:
            if len(line_pts) < 2:
                continue
            path = QPainterPath()
            path.moveTo(line_pts[0, 0], line_pts[0, 1])
            for i in range(1, len(line_pts)):
                path.lineTo(line_pts[i, 0], line_pts[i, 1])
            item = self._scene.addPath(path, pen)
            self._grid_overlays.append(item)

    def _remove_overlays(self):
        """Remove all overlay graphics."""
        if self._ellipse_overlay is not None:
            self._scene.removeItem(self._ellipse_overlay)
            self._ellipse_overlay = None
        for item in self._grid_overlays:
            self._scene.removeItem(item)
        self._grid_overlays.clear()

    # --- Save ---

    def _save_calibration(self):
        """Accept calibration so the parent window can save it with the project."""
        if self._current_calibration is None or not self._current_calibration.is_valid():
            QMessageBox.warning(self, "Invalid", "No valid calibration to save.")
            return

        self._status.showMessage("Calibration saved to project.", 3000)
        self.calibration_saved.emit(self._current_calibration)
        self.accept()
