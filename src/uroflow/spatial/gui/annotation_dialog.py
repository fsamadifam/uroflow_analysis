"""Dialog for annotating event locations on video frames."""

import numpy as np
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QStatusBar, QSlider, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPen, QColor, QBrush, QPainterPath

from uroflow.spatial.frame_extractor import (
    extract_first_frame,
    extract_frame_at_time,
    frame_to_qpixmap,
    get_video_info,
)
from uroflow.spatial.calibration import CalibrationData
from uroflow.spatial.transform import (
    transform_point,
    point_to_polar,
    generate_grid_overlay,
)


class AnnotationGraphicsView(QGraphicsView):
    """Graphics view that captures click positions for event annotation.

    Left-click to mark location (crosshair cursor).
    Middle-click or Ctrl+left-click to pan.
    Scroll wheel to zoom.
    """

    point_clicked = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
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


class EventAnnotationDialog(QDialog):
    """Dialog for marking the spatial location of an event on a video frame.

    Shows the video frame with calibration overlay and allows user to
    click to mark where the event (void/feces) occurred.
    """

    location_selected = Signal(float, float, float, float)  # img_x, img_y, real_x, real_y

    def __init__(
        self,
        video_path: str,
        calibration: CalibrationData,
        event_label: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Mark Event Location - {Path(video_path).name}")
        self.resize(900, 700)

        self._video_path = video_path
        self._calibration = calibration
        self._event_label = event_label
        self._frame: Optional[np.ndarray] = None
        self._marker_item: Optional[QGraphicsEllipseItem] = None
        self._selected_point: Optional[Tuple[float, float]] = None
        self._video_info: Optional[dict] = None

        self._setup_ui()
        self._load_frame()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Info bar
        info_layout = QHBoxLayout()
        self._info_label = QLabel("Click on the event location in the frame")
        self._info_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        info_layout.addWidget(self._info_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)

        # Frame time slider
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("Time:"))
        self._time_slider = QSlider(Qt.Horizontal)
        self._time_slider.setRange(0, 100)
        self._time_slider.setValue(0)
        self._time_slider.valueChanged.connect(self._on_slider_changed)
        slider_layout.addWidget(self._time_slider)
        self._time_label = QLabel("0.0 s")
        slider_layout.addWidget(self._time_label)
        layout.addLayout(slider_layout)

        # Graphics view
        self._scene = QGraphicsScene()
        self._view = AnnotationGraphicsView()
        self._view.setScene(self._scene)
        self._view.point_clicked.connect(self._on_point_clicked)
        layout.addWidget(self._view)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._confirm_btn = QPushButton("Confirm Location")
        self._confirm_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-weight: bold; padding: 6px 20px; }"
        )
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.clicked.connect(self._confirm)
        btn_layout.addWidget(self._confirm_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        # Status
        self._status = QStatusBar()
        layout.addWidget(self._status)

    def _load_frame(self):
        """Load first frame from video."""
        self._video_info = get_video_info(self._video_path)
        frame = extract_first_frame(self._video_path)
        if frame is None:
            self._status.showMessage("Failed to load video frame")
            return

        self._frame = frame

        if self._video_info:
            total_frames = self._video_info.get("frame_count", 100)
            self._time_slider.setRange(0, total_frames - 1)

        self._display_frame(frame)

    def _display_frame(self, frame: np.ndarray):
        """Display frame and calibration overlay."""
        pixmap = frame_to_qpixmap(frame)
        self._scene.clear()
        self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        self._marker_item = None

        # Draw calibration grid overlay
        if self._calibration is not None and self._calibration.is_valid():
            lines = generate_grid_overlay(self._calibration, n_radial=4, n_angular=8)
            pen = QPen(QColor(0, 200, 255, 100), 1)
            for line_pts in lines:
                if len(line_pts) < 2:
                    continue
                path = QPainterPath()
                path.moveTo(line_pts[0, 0], line_pts[0, 1])
                for i in range(1, len(line_pts)):
                    path.lineTo(line_pts[i, 0], line_pts[i, 1])
                self._scene.addPath(path, pen)

    def _on_slider_changed(self, value: int):
        """Seek to a different frame in the video."""
        if not self._video_info:
            return
        fps = self._video_info.get("fps", 30)
        timestamp_s = value / fps if fps > 0 else 0
        self._time_label.setText(f"{timestamp_s:.1f} s")

        frame = extract_frame_at_time(self._video_path, timestamp_s)
        if frame is not None:
            self._frame = frame
            self._display_frame(frame)

    def _on_point_clicked(self, x: float, y: float):
        """Handle click on frame to mark event location."""
        self._selected_point = (x, y)

        # Remove previous marker
        if self._marker_item is not None:
            self._scene.removeItem(self._marker_item)

        # Draw marker
        size = 16
        pen = QPen(QColor(255, 255, 0), 3)
        brush = QBrush(QColor(255, 255, 0, 80))
        self._marker_item = self._scene.addEllipse(
            x - size / 2, y - size / 2, size, size, pen, brush
        )

        # Optional: Show coordinates in status bar instead
        if self._calibration is not None and self._calibration.is_valid():
            result = transform_point(x, y, self._calibration)
            if result is not None:
                x_cm, y_cm = result
                r_cm, theta = point_to_polar(x_cm, y_cm)
                self._status.showMessage(
                    f"Location: ({x_cm:.2f}, {y_cm:.2f}) cm, r={r_cm:.2f} cm, θ={theta:.1f}°"
                )
            else:
                self._status.showMessage("Transform failed")
        else:
            self._status.showMessage(f"Point selected at ({x:.0f}, {y:.0f}) px")

        self._confirm_btn.setEnabled(True)

    def _confirm(self):
        """Confirm selection and emit signal."""
        if self._selected_point is None:
            return

        x, y = self._selected_point
        if self._calibration is not None and self._calibration.is_valid():
            result = transform_point(x, y, self._calibration)
            if result is not None:
                self.location_selected.emit(x, y, result[0], result[1])
                self.accept()
                return

        # No calibration or transform failed - emit with NaN for real coords
        self.location_selected.emit(x, y, float("nan"), float("nan"))
        self.accept()

    def get_result(self) -> Optional[Tuple[float, float, float, float]]:
        """Get the annotated location after dialog closes.

        Returns:
            (image_x, image_y, real_x_cm, real_y_cm) or None if cancelled
        """
        if self._selected_point is None:
            return None
        x, y = self._selected_point
        if self._calibration is not None and self._calibration.is_valid():
            result = transform_point(x, y, self._calibration)
            if result is not None:
                return (x, y, result[0], result[1])
        return (x, y, float("nan"), float("nan"))
