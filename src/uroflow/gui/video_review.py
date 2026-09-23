"""Embedded video review synchronized to the selected event's wall clock."""

from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from uroflow.core.video import find_matching_videos, get_video_files
from uroflow.spatial.frame_extractor import frame_to_qpixmap


class VideoReviewPane(QWidget):
    """Show a matched clip, seek by frame, and correct the video clock."""

    clock_offset_changed = Signal(float)
    annotation_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._event = None
        self._session_config = {}
        self._video_files = []
        self._matches = []
        self._choices = {}
        self._capture = None
        self._video_path = None
        self._frame_count = 0
        self._fps = 0.0
        self._current_frame = -1
        self._pixmap = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._play_next)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        top = QHBoxLayout()
        top.addWidget(QLabel("Matched video:"))
        self.match_combo = QComboBox()
        self.match_combo.currentIndexChanged.connect(self._on_match_changed)
        top.addWidget(self.match_combo, 1)
        layout.addLayout(top)

        self.match_label = QLabel("Select an event to match a video")
        self.match_label.setWordWrap(True)
        layout.addWidget(self.match_label)

        self.frame_label = QLabel("No frame")
        self.frame_label.setAlignment(Qt.AlignCenter)
        self.frame_label.setMinimumHeight(180)
        self.frame_label.setStyleSheet("background: #171717; color: #ddd;")
        layout.addWidget(self.frame_label, 1)

        controls = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self._toggle_play)
        controls.addWidget(self.play_button)
        self.prev_button = QPushButton("◀ Frame")
        self.prev_button.clicked.connect(lambda: self.step_frame(-1))
        controls.addWidget(self.prev_button)
        self.next_button = QPushButton("Frame ▶")
        self.next_button.clicked.connect(lambda: self.step_frame(1))
        controls.addWidget(self.next_button)
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.valueChanged.connect(self.seek_frame)
        controls.addWidget(self.frame_slider, 1)
        self.time_label = QLabel("—")
        controls.addWidget(self.time_label)
        layout.addLayout(controls)

        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel("Video clock offset:"))
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-3600.0, 3600.0)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setSingleStep(0.1)
        self.offset_spin.setSuffix(" s")
        self.offset_spin.setToolTip(
            "Seconds added to video filename timestamps to align them with the recording clock"
        )
        self.offset_spin.valueChanged.connect(self.clock_offset_changed.emit)
        offset_row.addWidget(self.offset_spin)
        offset_row.addStretch()
        self.annotation_button = QPushButton("Mark location at this frame")
        self.annotation_button.clicked.connect(self.annotation_requested.emit)
        offset_row.addWidget(self.annotation_button)
        layout.addLayout(offset_row)
        self.timing_note = QLabel("Frame alignment assumes the filename time marks the end of the clip.")
        self.timing_note.setStyleSheet("color: #666;")
        layout.addWidget(self.timing_note)
        self._set_frame_controls_enabled(False)

    @property
    def selected_video_path(self):
        return self._video_path

    @property
    def current_frame(self):
        return max(0, self._current_frame)

    def set_context(self, folder_path, session_config, clock_offset_s):
        """Refresh video inventory and matching settings for a project."""
        self._stop_playback()
        self._choices.clear()
        self._video_files = get_video_files(folder_path) if folder_path else []
        self._session_config = session_config or {}
        self.offset_spin.blockSignals(True)
        self.offset_spin.setValue(clock_offset_s)
        self.offset_spin.blockSignals(False)
        self.set_event(self._event)

    def set_event(self, event):
        """Match the event and seek to its estimated position in the clip."""
        self._stop_playback()
        self._event = event
        config = self._session_config
        if event is None:
            self._matches = []
            message = "Select an event to match a video"
        elif not self._video_files:
            self._matches = []
            message = "No timestamped videos found in the selected folder"
        elif not event.wall_clock_time or not config.get("start_date") or not config.get("start_time"):
            self._matches = []
            message = "Event or session wall clock time is missing"
        else:
            self._matches = find_matching_videos(
                event, self._video_files, config["start_date"], config["start_time"],
                max_delay_after_event_s=60.0, clock_offset_s=self.offset_spin.value(),
            )
            message = f"No video matched event at {event.wall_clock_time}" if not self._matches else ""

        self.match_combo.blockSignals(True)
        self.match_combo.clear()
        for path, _, delay_s in self._matches:
            self.match_combo.addItem(f"{path.name} ({delay_s:+.3f} s)", str(path))
        if self._matches:
            preferred = self._choices.get(event.event_id)
            paths = [str(match[0]) for match in self._matches]
            self.match_combo.setCurrentIndex(paths.index(preferred) if preferred in paths else 0)
        self.match_combo.blockSignals(False)
        if self._matches:
            self._on_match_changed(self.match_combo.currentIndex())
        else:
            self._close_capture()
            self.match_label.setText(message)

    def _on_match_changed(self, index):
        if index < 0 or index >= len(self._matches):
            return
        path, _, delay_s = self._matches[index]
        path = str(path)
        self._choices[self._event.event_id] = path
        self.match_label.setText(
            f"{Path(path).name} — corrected video save time {delay_s:+.3f} s from event"
        )
        if path != self._video_path:
            self._close_capture()
            capture = cv2.VideoCapture(path)
            if not capture.isOpened():
                capture.release()
                self.match_label.setText(f"{Path(path).name} matched, but the video could not be decoded")
                return
            self._capture = capture
            self._video_path = path
            self._fps = capture.get(cv2.CAP_PROP_FPS)
            self._frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if self._fps <= 0 or self._frame_count <= 0:
                self._close_capture()
                self.match_label.setText(f"{Path(path).name} matched, but frame timing is unavailable")
                return
            self.frame_slider.blockSignals(True)
            self.frame_slider.setRange(0, self._frame_count - 1)
            self.frame_slider.blockSignals(False)
            self._set_frame_controls_enabled(True)
        # Replay files are named for their save time. Estimate the event frame
        # by counting backward from the clip end using the corrected delay.
        frame = round((self._frame_count / self._fps - delay_s) * self._fps)
        self.seek_frame(max(0, min(frame, self._frame_count - 1)))

    def seek_frame(self, index):
        if self._capture is None or not 0 <= index < self._frame_count:
            return
        if index != self._current_frame + 1:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self._capture.read()
        if not ok or frame is None:
            self._stop_playback()
            self.match_label.setText("Matched video, but this frame could not be decoded")
            return
        self._current_frame = index
        self._pixmap = frame_to_qpixmap(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        self._scale_frame()
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(index)
        self.frame_slider.blockSignals(False)
        self.time_label.setText(f"Frame {index + 1}/{self._frame_count} · {index / self._fps:.3f} s")

    def step_frame(self, delta):
        self._stop_playback()
        if self._capture is not None:
            self.seek_frame(max(0, min(self._current_frame + delta, self._frame_count - 1)))

    def _toggle_play(self):
        if self._timer.isActive():
            self._stop_playback()
        elif self._capture is not None:
            if self._current_frame >= self._frame_count - 1:
                self.seek_frame(0)
            self._timer.start(max(1, round(1000 / self._fps)))
            self.play_button.setText("Pause")

    def _play_next(self):
        if self._current_frame >= self._frame_count - 1:
            self._stop_playback()
        else:
            self.seek_frame(self._current_frame + 1)

    def _stop_playback(self):
        self._timer.stop()
        self.play_button.setText("Play")

    def _set_frame_controls_enabled(self, enabled):
        for widget in (self.play_button, self.prev_button, self.next_button,
                       self.frame_slider, self.annotation_button):
            widget.setEnabled(enabled)

    def _close_capture(self):
        self._stop_playback()
        if self._capture is not None:
            self._capture.release()
        self._capture = None
        self._video_path = None
        self._frame_count = 0
        self._fps = 0.0
        self._current_frame = -1
        self._pixmap = None
        self.frame_label.clear()
        self.frame_label.setText("No frame")
        self.time_label.setText("—")
        self._set_frame_controls_enabled(False)

    def _scale_frame(self):
        if self._pixmap is not None:
            self.frame_label.setPixmap(self._pixmap.scaled(
                self.frame_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_frame()

    def closeEvent(self, event):
        self._close_capture()
        super().closeEvent(event)
