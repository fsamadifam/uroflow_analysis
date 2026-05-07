"""Calibration data structures and persistence."""

import json
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple


@dataclass
class EllipseCalibration:
    """Ellipse-to-circle calibration parameters.

    The visible circular cage floor appears as an ellipse in the camera frame
    due to perspective distortion.
    """
    center_x: float
    center_y: float
    semi_major: float
    semi_minor: float
    angle_rad: float
    cage_radius_cm: float
    clicked_points: List[Tuple[float, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "center_x": self.center_x,
            "center_y": self.center_y,
            "semi_major": self.semi_major,
            "semi_minor": self.semi_minor,
            "angle_rad": self.angle_rad,
            "cage_radius_cm": self.cage_radius_cm,
            "clicked_points": self.clicked_points,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EllipseCalibration":
        return cls(
            center_x=d["center_x"],
            center_y=d["center_y"],
            semi_major=d["semi_major"],
            semi_minor=d["semi_minor"],
            angle_rad=d["angle_rad"],
            cage_radius_cm=d["cage_radius_cm"],
            clicked_points=[tuple(p) for p in d.get("clicked_points", [])],
        )


@dataclass
class HomographyCalibration:
    """Perspective transform calibration using a homography matrix.

    Maps points from the distorted camera view to an ideal top-down
    circular coordinate system.
    """
    matrix: np.ndarray  # 3x3 homography
    src_points: List[Tuple[float, float]]  # Points in distorted image
    dst_points: List[Tuple[float, float]]  # Corresponding ideal positions
    cage_radius_cm: float
    image_width: int = 0
    image_height: int = 0

    def to_dict(self) -> dict:
        return {
            "matrix": self.matrix.tolist(),
            "src_points": self.src_points,
            "dst_points": self.dst_points,
            "cage_radius_cm": self.cage_radius_cm,
            "image_width": self.image_width,
            "image_height": self.image_height,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HomographyCalibration":
        return cls(
            matrix=np.array(d["matrix"], dtype=np.float64),
            src_points=[tuple(p) for p in d["src_points"]],
            dst_points=[tuple(p) for p in d["dst_points"]],
            cage_radius_cm=d["cage_radius_cm"],
            image_width=d.get("image_width", 0),
            image_height=d.get("image_height", 0),
        )


@dataclass
class CalibrationData:
    """Container holding the active calibration for a session."""
    method: str  # "ellipse" or "homography"
    ellipse: Optional[EllipseCalibration] = None
    homography: Optional[HomographyCalibration] = None
    calibration_frame_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        d = {
            "method": self.method,
            "calibration_frame_path": self.calibration_frame_path,
            "created_at": self.created_at,
        }
        if self.ellipse is not None:
            d["ellipse"] = self.ellipse.to_dict()
        if self.homography is not None:
            d["homography"] = self.homography.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationData":
        ellipse = None
        homography = None
        if "ellipse" in d:
            ellipse = EllipseCalibration.from_dict(d["ellipse"])
        if "homography" in d:
            homography = HomographyCalibration.from_dict(d["homography"])
        return cls(
            method=d["method"],
            ellipse=ellipse,
            homography=homography,
            calibration_frame_path=d.get("calibration_frame_path", ""),
            created_at=d.get("created_at", ""),
        )

    def is_valid(self) -> bool:
        """Check if calibration has required data for its method."""
        if self.method == "ellipse":
            return self.ellipse is not None and self.ellipse.semi_major > 0
        elif self.method == "homography":
            return (
                self.homography is not None
                and self.homography.matrix is not None
                and len(self.homography.src_points) >= 4
            )
        return False


def save_calibration(cal_data: CalibrationData, config_path: str) -> None:
    """Save calibration data into session_config.json.

    Adds or updates the 'spatial_calibration' key in the config file.

    Args:
        cal_data: CalibrationData to save
        config_path: Path to session_config.json
    """
    path = Path(config_path)
    if path.exists():
        with open(path, "r") as f:
            config = json.load(f)
    else:
        config = {}

    config["spatial_calibration"] = cal_data.to_dict()

    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def load_calibration(config_path: str) -> Optional[CalibrationData]:
    """Load calibration data from session_config.json.

    Args:
        config_path: Path to session_config.json

    Returns:
        CalibrationData or None if not present/invalid
    """
    path = Path(config_path)
    if not path.exists():
        return None

    try:
        with open(path, "r") as f:
            config = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    cal_dict = config.get("spatial_calibration")
    if cal_dict is None:
        return None

    try:
        return CalibrationData.from_dict(cal_dict)
    except (KeyError, TypeError, ValueError):
        return None
