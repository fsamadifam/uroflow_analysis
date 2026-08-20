"""Reusable publication figures for reviewed uroflow events."""

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from matplotlib import rc_context
from matplotlib.figure import Figure
from matplotlib.patches import Circle

if TYPE_CHECKING:
    from uroflow.core.types import Project


LABEL_ORDER = ("urine", "feces")
COLORS = {
    "total": "#555555",
    "feces": "#4A1E05",
    "urine": "#FFA800",
}
PLOT_STYLE = {
    "axes.axisbelow": True,
    "axes.grid": True,
    "grid.alpha": 0.6,
    "grid.color": "#b0b0b0",
    "grid.linewidth": 0.8,
}


def project_to_dataframe(project: "Project") -> pd.DataFrame:
    """Convert the reviewed events in a project to plotting data."""
    calibration = project.spatial_calibration or {}
    cage_radius_cm = np.nan
    for method in ("ellipse", "homography"):
        method_data = calibration.get(method) or {}
        if method_data.get("cage_radius_cm") is not None:
            cage_radius_cm = method_data["cage_radius_cm"]
            break

    rows = []
    for event in project.events:
        features = event.features
        coords = event.spatial_coords
        rows.append({
            "start_time_s": event.start_time_s,
            "duration_s": event.duration_s(),
            "delta_mass_g": features.delta_mass_g if features else np.nan,
            "peak_slope_g_per_s": (
                features.peak_slope_g_per_s if features else np.nan
            ),
            "mean_slope_g_per_s": (
                features.mean_slope_g_per_s if features else np.nan
            ),
            "label_user": event.label_user,
            "real_x_cm": coords.real_x_cm if coords else np.nan,
            "real_y_cm": coords.real_y_cm if coords else np.nan,
            "radius_cm": coords.radius_cm if coords else np.nan,
            "calibration_cage_radius_cm": cage_radius_cm,
        })

    return pd.DataFrame(rows)


def prepare_figure_data(data: pd.DataFrame) -> pd.DataFrame:
    """Keep reviewed urine/feces events and calculate plot coordinates."""
    required = {"label_user", "start_time_s", "duration_s", "delta_mass_g"}
    missing = sorted(required.difference(data.columns))
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    df = data[data["label_user"].isin(LABEL_ORDER)].copy()
    if df.empty:
        raise ValueError("No urine or feces events are available for plotting.")

    numeric_columns = [
        "start_time_s",
        "duration_s",
        "delta_mass_g",
        "peak_slope_g_per_s",
        "mean_slope_g_per_s",
        "real_x_cm",
        "real_y_cm",
        "radius_cm",
        "calibration_cage_radius_cm",
    ]
    for column in numeric_columns:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    df["start_time_hours"] = df["start_time_s"] / 3600.0

    spatial_columns = {
        "real_x_cm",
        "real_y_cm",
        "radius_cm",
        "calibration_cage_radius_cm",
    }
    if spatial_columns.issubset(df.columns):
        radius = df["calibration_cage_radius_cm"].replace(0, np.nan)
        df["norm_x"] = df["real_x_cm"] / radius
        df["norm_y"] = df["real_y_cm"] / radius
        df["norm_r"] = df["radius_cm"] / radius

    return df


def _available_order(df: pd.DataFrame) -> list[str]:
    labels = set(df["label_user"].dropna())
    return [label for label in LABEL_ORDER if label in labels]


def _category_tick_labels(df: pd.DataFrame, order: list[str]) -> list[str]:
    return [
        f"{label.capitalize()} (n={(df['label_user'] == label).sum()})"
        for label in order
    ]


def _draw_box_strip(
    ax,
    df: pd.DataFrame,
    column: str,
    order: list[str],
) -> None:
    """Draw colored boxplots with deterministic jittered observations."""
    groups = [
        df.loc[df["label_user"] == label, column].dropna().to_numpy()
        for label in order
    ]
    positions = np.arange(len(order), dtype=float)
    boxplot = ax.boxplot(
        groups,
        positions=positions,
        widths=0.4,
        patch_artist=True,
        showmeans=True,
        showfliers=False,
        medianprops={"color": "black"},
        meanprops={
            "marker": "o",
            "markerfacecolor": "white",
            "markeredgecolor": "black",
            "markersize": 8,
        },
    )
    for patch, label in zip(boxplot["boxes"], order):
        patch.set_facecolor(COLORS[label])
        patch.set_alpha(0.7)

    random = np.random.default_rng(0)
    for position, label, values in zip(positions, order, groups):
        jitter = random.uniform(-0.08, 0.08, len(values))
        ax.scatter(
            position + jitter,
            values,
            s=64,
            color=COLORS[label],
            edgecolor="black",
            linewidth=1,
            zorder=3,
        )

    ax.set_xticks(positions)


def make_spatial_counts_figure(df: pd.DataFrame) -> Figure:
    spatial = df.dropna(subset=["norm_x", "norm_y"])
    if spatial.empty:
        raise ValueError("No spatially annotated events are available for plotting.")

    with rc_context(PLOT_STYLE):
        fig = Figure(figsize=(13, 6))
        ax_map, ax_counts = fig.subplots(1, 2)

        for radius in (0.25, 0.5, 0.75):
            ax_map.add_patch(Circle(
                (0, 0), radius, fill=False, color="gray",
                linestyle="--", linewidth=0.7, alpha=0.7,
            ))
        ax_map.add_patch(Circle(
            (0, 0), 1.0, fill=False, color="black", linewidth=2,
        ))

        for label in _available_order(spatial):
            group = spatial[spatial["label_user"] == label]
            ax_map.scatter(
                group["norm_x"], group["norm_y"], s=90,
                color=COLORS[label], alpha=0.9, edgecolors="black",
                linewidth=0.8, label=f"{label.capitalize()} (n={len(group)})",
            )

        ax_map.axhline(0, color="lightgray", linewidth=0.6)
        ax_map.axvline(0, color="lightgray", linewidth=0.6)
        ax_map.set_xlim(-1.15, 1.15)
        ax_map.set_ylim(-1.15, 1.15)
        ax_map.set_aspect("equal")
        ax_map.set_xlabel(r"Normalized X ($x / R_{cage}$)")
        ax_map.set_ylabel(r"Normalized Y ($y / R_{cage}$)")
        ax_map.set_title(
            f"Normalized Event Locations (n={len(spatial)})",
            fontweight="bold",
        )
        ax_map.legend(loc="upper right", frameon=True)

        counts = df["label_user"].value_counts()
        categories = ["Total", "Feces", "Urine"]
        values = [len(df), counts.get("feces", 0), counts.get("urine", 0)]
        bars = ax_counts.bar(
            categories, values,
            color=[COLORS["total"], COLORS["feces"], COLORS["urine"]],
            edgecolor="black", width=0.45,
        )
        for bar in bars:
            value = int(bar.get_height())
            ax_counts.text(
                bar.get_x() + bar.get_width() / 2,
                value + max(values) * 0.02,
                str(value), ha="center", va="bottom", fontweight="bold",
            )
        ax_counts.set_ylim(0, max(values) * 1.15)
        ax_counts.set_ylabel("Event Count")
        ax_counts.set_title("Event Counts: Total & Breakdown", fontweight="bold")
        ax_counts.grid(axis="y", linestyle=":", alpha=0.7)

        fig.tight_layout()
        return fig


def make_radial_figure(df: pd.DataFrame) -> Figure:
    spatial = df.dropna(subset=["norm_r"])
    if spatial.empty:
        raise ValueError("No spatially annotated events are available for plotting.")

    order = _available_order(spatial)
    with rc_context(PLOT_STYLE):
        fig = Figure(figsize=(13, 5))
        ax_box, ax_hist = fig.subplots(1, 2)

        _draw_box_strip(ax_box, spatial, "norm_r", order)
        ax_box.axhline(
            1.0, color="black", linestyle="--", linewidth=1.5,
            label=r"Cage Perimeter ($r/R = 1.0$)",
        )
        ax_box.set_ylim(0, max(1.15, spatial["norm_r"].max() * 1.1))
        ax_box.set_xlabel("Event Category")
        ax_box.set_ylabel(r"Normalized Radial Distance ($r / R_{cage}$)")
        ax_box.set_title("Radial Distance Boxplot by Event Type")
        ax_box.set_xticks(range(len(order)))
        ax_box.set_xticklabels(_category_tick_labels(spatial, order))
        ax_box.legend(loc="lower left", frameon=True)

        histogram_data = []
        histogram_colors = []
        histogram_labels = []
        for label in reversed(order):
            values = spatial.loc[spatial["label_user"] == label, "norm_r"]
            histogram_data.append(values)
            histogram_colors.append(COLORS[label])
            histogram_labels.append(f"{label.capitalize()} (n={len(values)})")

        upper = max(1.1, spatial["norm_r"].max() * 1.05)
        ax_hist.hist(
            histogram_data, bins=np.linspace(0, upper, 12), stacked=True,
            color=histogram_colors, label=histogram_labels,
            edgecolor="black", linewidth=0.8, alpha=0.85,
        )
        ax_hist.axvline(
            1.0, color="black", linestyle="--", linewidth=1.5,
            label="Cage Perimeter",
        )
        ax_hist.set_xlim(0, upper)
        ax_hist.set_xlabel(r"Normalized Radial Distance ($r / R_{cage}$)")
        ax_hist.set_ylabel("Event Count")
        ax_hist.set_title("Count Distribution of Radial Distance")
        ax_hist.legend(loc="upper left", frameon=True)

        fig.tight_layout()
        return fig


def _draw_feature_panel(
    ax,
    df: pd.DataFrame,
    column: str,
    ylabel: str,
    title: str,
) -> None:
    plot_data = df.dropna(subset=[column])
    order = _available_order(plot_data)
    if not order:
        raise ValueError(f"No {column} values are available for plotting.")
    _draw_box_strip(ax, plot_data, column, order)
    ax.set_xlabel("Event Category")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontweight="bold")
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(_category_tick_labels(plot_data, order))

    top_value = plot_data[column].max()
    offset = max(abs(top_value) * 0.04, 0.05)
    for index, label in enumerate(order):
        group = plot_data.loc[plot_data["label_user"] == label, column]
        ax.text(
            index, group.max() + offset, f"Mean: {group.mean():.2f}",
            ha="center", va="bottom", fontweight="bold",
        )
    low, high = ax.get_ylim()
    ax.set_ylim(min(0, low), max(high, top_value + offset * 3))


def make_mass_duration_figure(df: pd.DataFrame) -> Figure:
    with rc_context(PLOT_STYLE):
        fig = Figure(figsize=(13, 5))
        ax_mass, ax_duration = fig.subplots(1, 2)
        _draw_feature_panel(
            ax_mass, df, "delta_mass_g", r"Mass Change $\Delta m$ (g)",
            r"Event Mass Comparison ($\Delta m$)",
        )
        _draw_feature_panel(
            ax_duration, df, "duration_s", "Duration (s)",
            "Event Duration Comparison",
        )
        fig.tight_layout()
        return fig


def make_chronology_figure(df: pd.DataFrame) -> Figure:
    plot_data = df.dropna(subset=["start_time_hours", "delta_mass_g"])
    if plot_data.empty:
        raise ValueError("No event times and mass changes are available for plotting.")

    with rc_context(PLOT_STYLE):
        fig = Figure(figsize=(9, 5))
        ax = fig.subplots()
        for label in _available_order(plot_data):
            group = plot_data[plot_data["label_user"] == label]
            ax.scatter(
                group["start_time_hours"], group["delta_mass_g"],
                color=COLORS[label], s=90, edgecolor="black", linewidth=0.8,
                alpha=0.85, label=f"{label.capitalize()} (n={len(group)})",
            )
            ax.vlines(
                group["start_time_hours"], 0, group["delta_mass_g"],
                colors=COLORS[label], alpha=0.5, linestyles=":", linewidth=1.2,
            )

        ax.set_xlabel("Experiment Elapsed Time (Hours)")
        ax.set_ylabel(r"Mass Change $\Delta m$ (g)")
        ax.set_title("Event Chronology Over Experiment Time", fontweight="bold")
        ax.set_ylim(bottom=0)
        ax.legend(loc="upper left", frameon=True)
        fig.tight_layout()
        return fig


def build_publication_figures(
    data: pd.DataFrame,
) -> list[tuple[str, str, Figure]]:
    """Build the standard figure set for display or export."""
    df = prepare_figure_data(data)
    builders = (
        ("fig1_spatial_and_counts", "Spatial & Counts", make_spatial_counts_figure),
        ("fig2_radial_distance_analysis", "Radial Distance", make_radial_figure),
        ("fig3_mass_and_duration", "Mass & Duration", make_mass_duration_figure),
        ("fig4_event_chronology", "Chronology", make_chronology_figure),
    )
    return [
        (stem, title, builder(df))
        for stem, title, builder in builders
    ]


def save_publication_figures(
    figures: list[tuple[str, str, Figure]],
    output_dir: str | Path,
    formats: tuple[str, ...] | list[str] = ("png", "svg"),
    dpi: int = 300,
) -> list[Path]:
    """Save a built publication figure set."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for stem, _title, figure in figures:
        for file_format in formats:
            path = output_dir / f"{stem}.{file_format.lower().lstrip('.')}"
            figure.savefig(path, dpi=dpi)
            saved_paths.append(path)

    return saved_paths


def generate_publication_figures(
    data: pd.DataFrame,
    output_dir: str | Path,
    formats: tuple[str, ...] | list[str] = ("png", "svg"),
    dpi: int = 300,
) -> list[Path]:
    """Build and save the standard four-figure publication set."""
    figures = build_publication_figures(data)
    try:
        return save_publication_figures(figures, output_dir, formats, dpi)
    finally:
        for _stem, _title, figure in figures:
            figure.clear()
