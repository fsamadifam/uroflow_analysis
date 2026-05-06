"""Event gallery with thumbnail views."""

import numpy as np
import pyqtgraph as pg
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QGridLayout,
    QLabel, QPushButton, QFrame, QFileDialog, QMessageBox
)
from PySide6.QtCore import Signal, Qt, QPointF, QRect
from PySide6.QtGui import QColor, QPixmap, QPainter, QPen, QPolygonF, QFont

from uroflow.core.types import Event


def _render_thumb_pixmap(timestamp: np.ndarray, mass: np.ndarray,
                         event: Event, padding_s: float = 5.0,
                         width: int = 190, height: int = 100) -> QPixmap:
    """Render an event trace to a static QPixmap using QPainter directly.

    Draws the trace as a polyline with start/end markers, avoiding live PlotWidgets.
    """
    margin = 4
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(255, 255, 255))

    t_start = max(0, event.start_time_s - padding_s)
    t_end = event.end_time_s + padding_s

    start_idx = np.searchsorted(timestamp, t_start)
    end_idx = np.searchsorted(timestamp, t_end)

    window_t = timestamp[start_idx:end_idx]
    window_m = mass[start_idx:end_idx]

    if len(window_t) < 2:
        return pixmap

    valid = np.isfinite(window_m)
    if not np.any(valid):
        return pixmap

    t_min, t_max = window_t[0], window_t[-1]
    m_min = float(np.nanmin(window_m[valid]))
    m_max = float(np.nanmax(window_m[valid]))
    if t_max == t_min:
        t_max = t_min + 1.0
    if m_max == m_min:
        m_max = m_min + 1.0

    draw_w = width - 2 * margin
    draw_h = height - 2 * margin

    def to_px(t, m):
        x = margin + (t - t_min) / (t_max - t_min) * draw_w
        y = margin + (1.0 - (m - m_min) / (m_max - m_min)) * draw_h
        return int(x), int(y)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Draw trace
    pen = QPen(QColor(0, 0, 0))
    pen.setWidth(1)
    painter.setPen(pen)

    points = QPolygonF()
    for j in range(len(window_t)):
        if valid[j]:
            x, y = to_px(window_t[j], window_m[j])
            points.append(QPointF(x, y))
    painter.drawPolyline(points)

    # Draw start marker (green vertical line)
    if t_min <= event.start_time_s <= t_max:
        sx = margin + (event.start_time_s - t_min) / (t_max - t_min) * draw_w
        pen_g = QPen(QColor(0, 180, 0))
        pen_g.setWidth(2)
        painter.setPen(pen_g)
        painter.drawLine(int(sx), margin, int(sx), height - margin)

    # Draw end marker (red vertical line)
    if t_min <= event.end_time_s <= t_max:
        ex = margin + (event.end_time_s - t_min) / (t_max - t_min) * draw_w
        pen_r = QPen(QColor(220, 0, 0))
        pen_r.setWidth(2)
        painter.setPen(pen_r)
        painter.drawLine(int(ex), margin, int(ex), height - margin)

    painter.end()
    return pixmap


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
            color = "rgba(255, 176, 0, 0.35)"
        elif self.event.label_user == "feces":
            color = "rgba(92, 46, 0, 0.28)"
        elif self.event.label_user == "bad":
            color = "lightcoral"
        else:
            color = "rgba(128, 128, 128, 0.35)"
        
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
        self.export_base_name = ""
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar with refresh button
        from PySide6.QtWidgets import QHBoxLayout
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(5, 5, 5, 0)
        
        self.refresh_btn = QPushButton("⟳ Refresh Thumbnails")
        self.refresh_btn.setStyleSheet("""
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
        self.refresh_btn.clicked.connect(self._rebuild_gallery)
        toolbar.addWidget(self.refresh_btn)

        self.save_gallery_btn = QPushButton("Save Gallery")
        self.save_gallery_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 5px 15px;
                border: 1px solid #388E3C;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #388E3C;
            }
        """)
        self.save_gallery_btn.clicked.connect(self._save_gallery_image)
        toolbar.addWidget(self.save_gallery_btn)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-size: 10px;")
        toolbar.addWidget(self.status_label)
        toolbar.addStretch()
        
        layout.addLayout(toolbar)
        
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

    def set_export_base_name(self, csv_path: str):
        """Set base filename (derived from CSV) used for gallery PNG export."""
        if not csv_path:
            self.export_base_name = ""
            return
        self.export_base_name = Path(csv_path).stem
    
    def update_events(self, events: list):
        """Update event list without rebuilding (call refresh to re-render).
        
        Args:
            events: Updated list of Event objects
        """
        self.events = events
        self.status_label.setText(f"{len(events)} events (stale — click Refresh)")
    
    def _rebuild_gallery(self):
        """Rebuild gallery thumbnails using pre-rendered pixmaps."""
        print(f"  EventGallery._rebuild_gallery: {len(self.events) if self.events else 0} events")
        
        # Clear existing
        for thumb in self.thumb_widgets:
            thumb.deleteLater()
        self.thumb_widgets.clear()
        
        if not self.events or self.timestamp is None:
            print("    No events or timestamp, skipping gallery")
            return
        
        n_cols = 3
        n_to_show = min(100, len(self.events))
        print(f"    Rendering {n_to_show} thumbnail pixmaps...")
        
        try:
            for i, event in enumerate(self.events[:n_to_show]):
                # Container frame
                frame = QFrame()
                frame.setFrameStyle(QFrame.Box | QFrame.Plain)
                frame.setLineWidth(1)
                frame.setFixedSize(200, 150)
                frame_layout = QVBoxLayout(frame)
                frame_layout.setContentsMargins(2, 2, 2, 2)
                frame_layout.setSpacing(1)

                # Info label
                label_text = f"#{i+1} "
                if event.label_user:
                    label_text += f"{event.label_user} | "
                if event.features:
                    label_text += f"{event.features.delta_mass_g:.2f}g {event.duration_s():.1f}s"
                info_label = QLabel(label_text)
                info_label.setStyleSheet("font-size: 15px; font-weight: bold; background: transparent;")
                frame_layout.addWidget(info_label)

                # Render trace to pixmap
                pixmap = _render_thumb_pixmap(self.timestamp, self.mass, event)
                img_label = QLabel()
                img_label.setPixmap(pixmap)
                img_label.setScaledContents(True)
                frame_layout.addWidget(img_label, stretch=1)

                # Style by label
                if event.label_user == "urine":
                    bg = "rgba(255, 176, 0, 0.35)"
                elif event.label_user == "feces":
                    bg = "rgba(92, 46, 0, 0.28)"
                elif event.label_user == "bad":
                    bg = "lightcoral"
                else:
                    bg = "rgba(128, 128, 128, 0.15)"
                frame.setStyleSheet(f"QFrame {{ background-color: {bg}; }}")

                # Make clickable
                frame.mousePressEvent = lambda evt, eid=event.event_id: self.event_selected.emit(eid)

                row = i // n_cols
                col = i % n_cols
                self.grid_layout.addWidget(frame, row, col)
                self.thumb_widgets.append(frame)
            
            self.grid_layout.setRowStretch(len(self.events) // n_cols + 1, 1)
            self.status_label.setText(f"{len(self.thumb_widgets)} events shown")
            print(f"    Gallery complete: {len(self.thumb_widgets)} thumbnails rendered")
            
        except Exception as e:
            self.status_label.setText(f"Error: {e}")
            print(f"    ERROR creating thumbnails: {e}")
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
            
            event = self.events[i]
            is_selected = (event.event_id == event_id)
            
            if is_selected:
                thumb.setStyleSheet("QFrame { background-color: lightblue; border: 3px solid blue; }")
                thumb.setLineWidth(3)
            else:
                if event.label_user == "urine":
                    bg = "rgba(255, 176, 0, 0.35)"
                elif event.label_user == "feces":
                    bg = "rgba(92, 46, 0, 0.28)"
                elif event.label_user == "bad":
                    bg = "lightcoral"
                else:
                    bg = "rgba(128, 128, 128, 0.15)"
                thumb.setStyleSheet(f"QFrame {{ background-color: {bg}; }}")
                thumb.setLineWidth(1)
    
    def clear(self):
        """Clear gallery."""
        for thumb in self.thumb_widgets:
            thumb.deleteLater()
        self.thumb_widgets.clear()
        self.events = []

    def _save_gallery_image(self):
        """Save a high-clarity gallery PNG with export-only layout settings."""
        if not self.events:
            QMessageBox.information(self, "Save Gallery", "No gallery thumbnails to save.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.export_base_name:
            default_name = f"{self.export_base_name}_gallery.png"
        else:
            default_name = f"event_gallery_{timestamp}.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Gallery Image",
            default_name,
            "PNG Images (*.png)"
        )

        if not file_path:
            return

        n_events = min(100, len(self.events))

        # Export-only layout: up to 10 columns for fewer rows in PNG output.
        export_cols = min(10, n_events) if n_events > 0 else 1
        frame_w = 260
        frame_h = 190
        label_h = 40
        margin = 10
        row_gap = 10
        col_gap = 10

        n_rows = int(np.ceil(n_events / export_cols))
        canvas_w = export_cols * frame_w + (export_cols + 1) * col_gap
        canvas_h = n_rows * frame_h + (n_rows + 1) * row_gap

        pixmap = QPixmap(canvas_w, canvas_h)
        pixmap.fill(QColor(255, 255, 255))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        for i, event in enumerate(self.events[:n_events]):
            row = i // export_cols
            col = i % export_cols
            x = col_gap + col * (frame_w + col_gap)
            y = row_gap + row * (frame_h + row_gap)

            if event.label_user == "urine":
                bg = QColor(255, 176, 0, 90)
            elif event.label_user == "feces":
                bg = QColor(92, 46, 0, 70)
            elif event.label_user == "bad":
                bg = QColor(240, 128, 128, 120)
            else:
                bg = QColor(128, 128, 128, 45)

            painter.fillRect(QRect(x, y, frame_w, frame_h), bg)
            painter.setPen(QPen(QColor(140, 140, 140)))
            painter.drawRect(QRect(x, y, frame_w, frame_h))

            label_text = f"#{i+1} "
            if event.label_user:
                label_text += f"{event.label_user} | "
            if event.features:
                label_text += f"{event.features.delta_mass_g:.2f}g {event.duration_s():.1f}s"
            painter.setPen(QPen(QColor(20, 20, 20)))
            label_font = QFont()
            label_font.setPointSize(13)
            label_font.setBold(True)
            painter.setFont(label_font)
            painter.drawText(
                QRect(x + margin, y + 4, frame_w - 2 * margin, label_h),
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                label_text
            )

            thumb = _render_thumb_pixmap(
                self.timestamp,
                self.mass,
                event,
                width=frame_w - 2 * margin,
                height=frame_h - label_h - margin
            )
            painter.drawPixmap(x + margin, y + label_h, thumb)

        painter.end()
        if pixmap.isNull():
            QMessageBox.warning(self, "Save Gallery", "Could not capture gallery image.")
            return

        if pixmap.save(file_path, "PNG"):
            self.status_label.setText(f"Saved gallery: {file_path}")
            QMessageBox.information(self, "Save Gallery", "Gallery image saved successfully.")
        else:
            QMessageBox.critical(self, "Save Gallery", "Failed to save gallery image.")
