"""Video frame extraction for calibration and annotation."""

import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Tuple


def extract_first_frame(video_path: str) -> Optional[np.ndarray]:
    """Extract the first frame from a video file.

    Args:
        video_path: Path to video file

    Returns:
        RGB numpy array (H, W, 3) or None if extraction fails
    """
    return extract_frame_at_time(video_path, 0.0)


def extract_frame_at_time(video_path: str, timestamp_s: float) -> Optional[np.ndarray]:
    """Extract a frame at a specific timestamp.

    Args:
        video_path: Path to video file
        timestamp_s: Time in seconds from start of video

    Returns:
        RGB numpy array (H, W, 3) or None if extraction fails
    """
    path = Path(video_path)
    if not path.exists():
        return None

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None

    try:
        if timestamp_s > 0:
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps > 0:
                frame_num = int(timestamp_s * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)

        ret, frame = cap.read()
        if not ret or frame is None:
            return None

        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    finally:
        cap.release()


def get_video_info(video_path: str) -> Optional[dict]:
    """Get video metadata.

    Args:
        video_path: Path to video file

    Returns:
        Dict with keys: width, height, fps, frame_count, duration_s
        or None if file cannot be opened
    """
    path = Path(video_path)
    if not path.exists():
        return None

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None

    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_s = frame_count / fps if fps > 0 else 0.0

        return {
            "width": width,
            "height": height,
            "fps": fps,
            "frame_count": frame_count,
            "duration_s": duration_s,
        }
    finally:
        cap.release()


def frame_to_qimage(frame: np.ndarray):
    """Convert RGB numpy array to QImage for display in PySide6.

    Args:
        frame: RGB numpy array (H, W, 3) with dtype uint8

    Returns:
        QImage object
    """
    from PySide6.QtGui import QImage

    h, w, ch = frame.shape
    bytes_per_line = ch * w
    return QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()


def frame_to_qpixmap(frame: np.ndarray):
    """Convert RGB numpy array to QPixmap for display in PySide6.

    Args:
        frame: RGB numpy array (H, W, 3) with dtype uint8

    Returns:
        QPixmap object
    """
    from PySide6.QtGui import QPixmap

    qimage = frame_to_qimage(frame)
    return QPixmap.fromImage(qimage)
