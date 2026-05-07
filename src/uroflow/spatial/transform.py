"""Coordinate transformation from distorted image space to real circular cage space."""

import cv2
import numpy as np
from typing import Tuple, Optional, List

from uroflow.spatial.calibration import (
    CalibrationData,
    EllipseCalibration,
    HomographyCalibration,
)


def fit_ellipse_to_points(
    points: List[Tuple[float, float]],
) -> Optional[EllipseCalibration]:
    """Fit an ellipse to a set of clicked points using OpenCV.

    Args:
        points: List of (x, y) pixel coordinates on the ellipse boundary.
                Minimum 5 points required.

    Returns:
        EllipseCalibration with fitted parameters, or None if fitting fails.
        cage_radius_cm is set to 0 (must be provided by user separately).
    """
    if len(points) < 5:
        return None

    pts = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    try:
        (cx, cy), (width, height), angle_deg = cv2.fitEllipse(pts)
    except cv2.error:
        return None

    semi_major = max(width, height) / 2.0
    semi_minor = min(width, height) / 2.0
    angle_rad = np.radians(angle_deg)
    if width < height:
        angle_rad += np.pi / 2.0

    return EllipseCalibration(
        center_x=cx,
        center_y=cy,
        semi_major=semi_major,
        semi_minor=semi_minor,
        angle_rad=angle_rad,
        cage_radius_cm=0.0,
        clicked_points=list(points),
    )


def compute_homography(
    src_points: List[Tuple[float, float]],
    dst_points: List[Tuple[float, float]],
) -> Optional[np.ndarray]:
    """Compute homography matrix from point correspondences.

    Args:
        src_points: Points in distorted image (minimum 4)
        dst_points: Corresponding ideal positions (same count)

    Returns:
        3x3 homography matrix, or None if computation fails
    """
    if len(src_points) < 4 or len(src_points) != len(dst_points):
        return None

    src = np.array(src_points, dtype=np.float64)
    dst = np.array(dst_points, dtype=np.float64)

    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    return H


# --- Point transformation functions ---


def transform_point_ellipse(
    x: float,
    y: float,
    cal: EllipseCalibration,
) -> Tuple[float, float]:
    """Transform a point from image space to real circular space using ellipse calibration.

    Algorithm:
        1. Translate so ellipse center is origin
        2. Flip x-axis (camera is bottom-up, creating horizontal mirror)
        3. Rotate to align with ellipse principal axes
        4. Scale the minor axis to equal the major axis (ellipse -> circle)
        5. Scale to real-world units (cm)

    Args:
        x, y: Pixel coordinates in image
        cal: Ellipse calibration parameters

    Returns:
        (x_cm, y_cm) in real circular coordinate system.
        Origin is cage center, units are cm.
        Corrected for bottom-up camera mirror effect.
    """
    # Negate x to correct for horizontal mirror from bottom-up camera
    dx = -(x - cal.center_x)
    dy = y - cal.center_y

    cos_a = np.cos(-cal.angle_rad)
    sin_a = np.sin(-cal.angle_rad)
    rx = dx * cos_a - dy * sin_a
    ry = dx * sin_a + dy * cos_a

    # Scale minor axis to match major axis (circle normalization)
    if cal.semi_minor > 0:
        ry *= cal.semi_major / cal.semi_minor

    # Convert to real units
    scale = cal.cage_radius_cm / cal.semi_major if cal.semi_major > 0 else 1.0
    x_cm = rx * scale
    y_cm = ry * scale

    return x_cm, y_cm


def transform_point_homography(
    x: float,
    y: float,
    cal: HomographyCalibration,
) -> Tuple[float, float]:
    """Transform a point using homography matrix.

    Args:
        x, y: Pixel coordinates in distorted image
        cal: Homography calibration parameters

    Returns:
        (x_cm, y_cm) in real coordinate system
    """
    pt = np.array([[[x, y]]], dtype=np.float64)
    transformed = cv2.perspectiveTransform(pt, cal.matrix)
    return float(transformed[0, 0, 0]), float(transformed[0, 0, 1])


def transform_point(
    x: float,
    y: float,
    cal_data: CalibrationData,
) -> Optional[Tuple[float, float]]:
    """Transform a point using the active calibration method.

    Args:
        x, y: Pixel coordinates in image
        cal_data: Calibration container

    Returns:
        (x_cm, y_cm) or None if calibration is invalid
    """
    if not cal_data.is_valid():
        return None

    if cal_data.method == "ellipse" and cal_data.ellipse is not None:
        return transform_point_ellipse(x, y, cal_data.ellipse)
    elif cal_data.method == "homography" and cal_data.homography is not None:
        return transform_point_homography(x, y, cal_data.homography)

    return None


# --- Inverse transforms (real -> image) ---


def inverse_transform_ellipse(
    x_cm: float,
    y_cm: float,
    cal: EllipseCalibration,
) -> Tuple[float, float]:
    """Transform from real coordinates back to image pixel coordinates.

    Args:
        x_cm, y_cm: Real-world coordinates in cm
        cal: Ellipse calibration

    Returns:
        (x_px, y_px) pixel coordinates in image
        Accounts for bottom-up camera mirror correction.
    """
    scale = cal.semi_major / cal.cage_radius_cm if cal.cage_radius_cm > 0 else 1.0
    rx = x_cm * scale
    ry = y_cm * scale

    if cal.semi_minor > 0:
        ry *= cal.semi_minor / cal.semi_major

    cos_a = np.cos(cal.angle_rad)
    sin_a = np.sin(cal.angle_rad)
    dx = rx * cos_a - ry * sin_a
    dy = rx * sin_a + ry * cos_a

    # Negate dx to reverse the horizontal mirror correction
    return cal.center_x - dx, cal.center_y + dy


def inverse_transform_homography(
    x_cm: float,
    y_cm: float,
    cal: HomographyCalibration,
) -> Optional[Tuple[float, float]]:
    """Transform from real coordinates back to image using inverse homography.

    Args:
        x_cm, y_cm: Real-world coordinates
        cal: Homography calibration

    Returns:
        (x_px, y_px) or None if inverse cannot be computed
    """
    H_inv = np.linalg.inv(cal.matrix)
    pt = np.array([[[x_cm, y_cm]]], dtype=np.float64)
    transformed = cv2.perspectiveTransform(pt, H_inv)
    return float(transformed[0, 0, 0]), float(transformed[0, 0, 1])


def inverse_transform_point(
    x_cm: float,
    y_cm: float,
    cal_data: CalibrationData,
) -> Optional[Tuple[float, float]]:
    """Inverse transform from real space to image space.

    Args:
        x_cm, y_cm: Real-world coordinates
        cal_data: Calibration container

    Returns:
        (x_px, y_px) or None
    """
    if not cal_data.is_valid():
        return None

    if cal_data.method == "ellipse" and cal_data.ellipse is not None:
        return inverse_transform_ellipse(x_cm, y_cm, cal_data.ellipse)
    elif cal_data.method == "homography" and cal_data.homography is not None:
        return inverse_transform_homography(x_cm, y_cm, cal_data.homography)

    return None


# --- Utility functions ---


def point_to_polar(x_cm: float, y_cm: float) -> Tuple[float, float]:
    """Convert Cartesian (x, y) to polar (radius, theta_deg).

    Args:
        x_cm, y_cm: Cartesian coordinates (origin at cage center)

    Returns:
        (radius_cm, theta_deg) where theta is measured from positive x-axis,
        counterclockwise, in degrees [0, 360).
    """
    radius = np.sqrt(x_cm**2 + y_cm**2)
    theta = np.degrees(np.arctan2(y_cm, x_cm)) % 360.0
    return radius, theta


def generate_ellipse_overlay_points(
    cal: EllipseCalibration,
    n_points: int = 100,
) -> np.ndarray:
    """Generate points along the fitted ellipse for visualization overlay.

    Args:
        cal: Ellipse calibration parameters
        n_points: Number of points to generate around the ellipse

    Returns:
        Array of shape (n_points, 2) with (x, y) pixel coordinates
    """
    theta = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    x_local = cal.semi_major * np.cos(theta)
    y_local = cal.semi_minor * np.sin(theta)

    cos_a = np.cos(cal.angle_rad)
    sin_a = np.sin(cal.angle_rad)
    x_rot = x_local * cos_a - y_local * sin_a + cal.center_x
    y_rot = x_local * sin_a + y_local * cos_a + cal.center_y

    return np.column_stack([x_rot, y_rot])


def generate_grid_overlay(
    cal_data: CalibrationData,
    n_radial: int = 5,
    n_angular: int = 12,
) -> List[np.ndarray]:
    """Generate concentric circles and radial lines in image space for overlay.

    Args:
        cal_data: Active calibration
        n_radial: Number of concentric circles
        n_angular: Number of radial lines

    Returns:
        List of polyline arrays, each shape (N, 2) in image pixel coordinates
    """
    if not cal_data.is_valid():
        return []

    if cal_data.method == "ellipse":
        radius_cm = cal_data.ellipse.cage_radius_cm
    else:
        radius_cm = cal_data.homography.cage_radius_cm

    lines = []
    pts_per_circle = 72

    # Concentric circles
    for i in range(1, n_radial + 1):
        r = radius_cm * i / n_radial
        theta = np.linspace(0, 2 * np.pi, pts_per_circle, endpoint=True)
        circle_pts = []
        for t in theta:
            x_cm = r * np.cos(t)
            y_cm = r * np.sin(t)
            px = inverse_transform_point(x_cm, y_cm, cal_data)
            if px is not None:
                circle_pts.append(px)
        if circle_pts:
            lines.append(np.array(circle_pts))

    # Radial lines
    for i in range(n_angular):
        angle = 2 * np.pi * i / n_angular
        radial_pts = []
        for r in np.linspace(0, radius_cm, 20):
            x_cm = r * np.cos(angle)
            y_cm = r * np.sin(angle)
            px = inverse_transform_point(x_cm, y_cm, cal_data)
            if px is not None:
                radial_pts.append(px)
        if radial_pts:
            lines.append(np.array(radial_pts))

    return lines
