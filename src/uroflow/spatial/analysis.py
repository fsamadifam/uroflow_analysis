"""Spatial analysis of event locations within the cage."""

import csv
import numpy as np
from pathlib import Path
from typing import List, Optional, Tuple

from uroflow.core.types import Event


def get_spatial_events(
    events: List[Event],
    label_filter: Optional[str] = None,
) -> List[Event]:
    """Filter events that have spatial coordinates.

    Args:
        events: All events
        label_filter: If provided, only return events with this label
                      ("urine", "feces", or None for all)

    Returns:
        Events that have spatial_coords set
    """
    result = [e for e in events if e.spatial_coords is not None]
    if label_filter:
        result = [e for e in result if e.label_user == label_filter]
    return result


def extract_coordinates(
    events: List[Event],
) -> Tuple[np.ndarray, np.ndarray]:
    """Extract real-world x, y arrays from events with spatial coords.

    Args:
        events: Events (should already be filtered to those with spatial_coords)

    Returns:
        (x_cm, y_cm) arrays
    """
    coords = [(e.spatial_coords.real_x_cm, e.spatial_coords.real_y_cm)
              for e in events if e.spatial_coords is not None]
    if not coords:
        return np.array([]), np.array([])
    arr = np.array(coords)
    return arr[:, 0], arr[:, 1]


def create_spatial_heatmap(
    events: List[Event],
    cage_radius_cm: float,
    resolution: int = 50,
    sigma_cm: float = 2.0,
    label_filter: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create 2D density heatmap of event locations.

    Uses Gaussian kernel density estimation for smoothing.

    Args:
        events: List of events with spatial coordinates
        cage_radius_cm: Cage radius for setting plot bounds
        resolution: Grid resolution (NxN)
        sigma_cm: Gaussian smoothing kernel width in cm
        label_filter: Optional label filter ("urine", "feces", None)

    Returns:
        (X, Y, Z) arrays suitable for pcolormesh/imshow.
        Z values are masked outside the cage circle.
    """
    filtered = get_spatial_events(events, label_filter)
    x, y = extract_coordinates(filtered)

    x_edges = np.linspace(-cage_radius_cm, cage_radius_cm, resolution + 1)
    y_edges = np.linspace(-cage_radius_cm, cage_radius_cm, resolution + 1)
    X, Y = np.meshgrid(
        (x_edges[:-1] + x_edges[1:]) / 2,
        (y_edges[:-1] + y_edges[1:]) / 2,
    )

    Z = np.zeros_like(X)

    if len(x) == 0:
        return X, Y, Z

    # Gaussian kernel density
    for xi, yi in zip(x, y):
        dist_sq = (X - xi)**2 + (Y - yi)**2
        Z += np.exp(-dist_sq / (2 * sigma_cm**2))

    # Mask outside cage circle
    R = np.sqrt(X**2 + Y**2)
    Z[R > cage_radius_cm] = np.nan

    return X, Y, Z


def compute_radial_distribution(
    events: List[Event],
    cage_radius_cm: float,
    n_bins: int = 10,
    label_filter: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Histogram of events by distance from cage center.

    Args:
        events: Events with spatial coordinates
        cage_radius_cm: Cage radius
        n_bins: Number of radial bins
        label_filter: Optional label filter

    Returns:
        (bin_centers_cm, counts) arrays
    """
    filtered = get_spatial_events(events, label_filter)
    radii = np.array([e.spatial_coords.radius_cm for e in filtered])

    if len(radii) == 0:
        edges = np.linspace(0, cage_radius_cm, n_bins + 1)
        centers = (edges[:-1] + edges[1:]) / 2
        return centers, np.zeros(n_bins)

    edges = np.linspace(0, cage_radius_cm, n_bins + 1)
    counts, _ = np.histogram(radii, bins=edges)
    centers = (edges[:-1] + edges[1:]) / 2

    return centers, counts


def compute_angular_distribution(
    events: List[Event],
    n_sectors: int = 8,
    label_filter: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Histogram of events by angle (compass sectors).

    Args:
        events: Events with spatial coordinates
        n_sectors: Number of angular sectors
        label_filter: Optional label filter

    Returns:
        (sector_center_deg, counts) arrays.
        Sector centers are in degrees [0, 360).
    """
    filtered = get_spatial_events(events, label_filter)
    angles = np.array([e.spatial_coords.theta_deg for e in filtered])

    edges = np.linspace(0, 360, n_sectors + 1)
    counts, _ = np.histogram(angles, bins=edges)
    centers = (edges[:-1] + edges[1:]) / 2

    return centers, counts


def compute_spatial_statistics(
    events: List[Event],
    cage_radius_cm: float,
    label_filter: Optional[str] = None,
) -> dict:
    """Compute summary statistics for spatial distribution.

    Args:
        events: Events with spatial coordinates
        cage_radius_cm: Cage radius
        label_filter: Optional label filter

    Returns:
        Dictionary with statistics:
        - n_events: number of annotated events
        - mean_radius_cm: mean distance from center
        - std_radius_cm: standard deviation of distance
        - center_of_mass: (x, y) in cm
        - periphery_fraction: fraction of events in outer 50% of cage area
    """
    filtered = get_spatial_events(events, label_filter)
    if not filtered:
        return {
            "n_events": 0,
            "mean_radius_cm": 0.0,
            "std_radius_cm": 0.0,
            "center_of_mass": (0.0, 0.0),
            "periphery_fraction": 0.0,
        }

    x, y = extract_coordinates(filtered)
    radii = np.sqrt(x**2 + y**2)

    # Periphery = outer 50% of area -> r > radius * sqrt(0.5) ≈ 0.707 * radius
    periphery_threshold = cage_radius_cm * np.sqrt(0.5)
    periphery_count = np.sum(radii > periphery_threshold)

    return {
        "n_events": len(filtered),
        "mean_radius_cm": float(np.mean(radii)),
        "std_radius_cm": float(np.std(radii)),
        "center_of_mass": (float(np.mean(x)), float(np.mean(y))),
        "periphery_fraction": float(periphery_count / len(filtered)),
    }


def export_spatial_csv(
    events: List[Event],
    output_path: str,
    include_features: bool = True,
) -> int:
    """Export events with spatial coordinates to a dedicated spatial CSV.

    Args:
        events: All events (will filter to those with spatial coords)
        output_path: Output CSV path
        include_features: Whether to include event features columns

    Returns:
        Number of events exported
    """
    spatial_events = get_spatial_events(events)
    if not spatial_events:
        return 0

    output_path = Path(output_path)

    headers = [
        "event_id", "start_time_s", "end_time_s", "duration_s",
        "label", "wall_clock_time",
        "image_x", "image_y",
        "real_x_cm", "real_y_cm", "radius_cm", "theta_deg",
    ]
    if include_features:
        headers.extend(["delta_mass_g", "peak_slope_g_per_s"])

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for event in sorted(spatial_events, key=lambda e: e.start_time_s):
            sc = event.spatial_coords
            row = [
                event.event_id,
                f"{event.start_time_s:.3f}",
                f"{event.end_time_s:.3f}",
                f"{event.duration_s():.3f}",
                event.label_user,
                event.wall_clock_time,
                f"{sc.image_x:.1f}",
                f"{sc.image_y:.1f}",
                f"{sc.real_x_cm:.3f}",
                f"{sc.real_y_cm:.3f}",
                f"{sc.radius_cm:.3f}",
                f"{sc.theta_deg:.1f}",
            ]
            if include_features and event.features:
                row.extend([
                    f"{event.features.delta_mass_g:.4f}",
                    f"{event.features.peak_slope_g_per_s:.4f}",
                ])
            elif include_features:
                row.extend(["", ""])

            writer.writerow(row)

    return len(spatial_events)
