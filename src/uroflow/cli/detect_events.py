"""CLI tool for baseline event detection (Milestone 0).

Reads CSV + config → segments → detect → write events_auto.csv + project.json
"""

import argparse
import sys
from pathlib import Path

from uroflow.io.load_csv import load_uroflow_csv, find_acquisition_event_windows
from uroflow.io.load_config import load_session_config
from uroflow.core.types import DetectionParams, Project
from uroflow.core.segments import find_segments_and_gaps
from uroflow.core.detect import detect_events_in_segments, detect_from_acquisition_flags
from uroflow.core.features import compute_features_for_events
from uroflow.core.overlap import resolve_overlaps, remove_duplicates
from uroflow.core.project_io import save_project, export_events_csv


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Uroflow event detection CLI (Milestone 0)',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument('csv_path', help='Path to uroflow CSV file')
    parser.add_argument('config_path', help='Path to session_config.json file')
    parser.add_argument(
        '--output', '-o',
        default='.',
        help='Output directory for results'
    )
    parser.add_argument(
        '--use-acquisition-flags',
        action='store_true',
        help='Use acquisition event flags from CSV as initial candidates'
    )
    parser.add_argument(
        '--skip-auto-detect',
        action='store_true',
        help='Skip auto-detection (only use acquisition flags)'
    )
    
    args = parser.parse_args()
    
    try:
        run_detection(
            csv_path=args.csv_path,
            config_path=args.config_path,
            output_dir=args.output,
            use_acquisition_flags=args.use_acquisition_flags,
            skip_auto_detect=args.skip_auto_detect
        )
        print("\n✓ Detection complete!")
        return 0
        
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        return 1


def run_detection(csv_path: str,
                 config_path: str,
                 output_dir: str = '.',
                 use_acquisition_flags: bool = True,
                 skip_auto_detect: bool = False):
    """Run complete detection pipeline.
    
    Args:
        csv_path: Path to CSV file
        config_path: Path to session config JSON
        output_dir: Output directory for results
        use_acquisition_flags: Whether to use acquisition event flags
        skip_auto_detect: Skip auto-detection algorithm
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading data from {csv_path}...")
    timestamp, mass, acquisition_events, metadata = load_uroflow_csv(csv_path)
    print(f"  Loaded {len(timestamp):,} samples")
    print(f"  Duration: {timestamp[-1] - timestamp[0]:.1f} seconds ({(timestamp[-1] - timestamp[0]) / 3600:.1f} hours)")
    
    print(f"\nLoading config from {config_path}...")
    config = load_session_config(config_path)
    
    print("\nDetecting segments and gaps...")
    detection_params = DetectionParams.from_session_config(config)
    
    # Use default dt_factor=5.0 for segment detection
    segments, gaps = find_segments_and_gaps(timestamp, mass, dt_factor=5.0)
    print(f"  Found {len(segments)} segments and {len(gaps)} gaps")
    
    total_valid_samples = sum(len(seg) for seg in segments)
    valid_fraction = total_valid_samples / len(timestamp) if len(timestamp) > 0 else 0
    print(f"  Valid data: {valid_fraction * 100:.1f}%")
    
    # Collect all events
    all_events = []
    
    # Use acquisition flags if requested
    if use_acquisition_flags and acquisition_events.any():
        print("\nConverting acquisition flags to events...")
        acq_windows = find_acquisition_event_windows(timestamp, acquisition_events, min_gap_s=1.0)
        acq_events = detect_from_acquisition_flags(timestamp, mass, acq_windows, segments)
        print(f"  Found {len(acq_events)} acquisition-flagged events")
        all_events.extend(acq_events)
    
    # Run auto-detection if not skipped
    if not skip_auto_detect:
        print("\nRunning auto-detection...")
        print(f"  Parameters:")
        print(f"    Threshold: {detection_params.threshold_g} g")
        print(f"    Diff test time: {detection_params.diff_test_time_s} s")
        print(f"    Min event length: {detection_params.min_event_len_s} s")
        print(f"    Max event length: {detection_params.max_event_len_s} s")
        print(f"    Min gap merge: {detection_params.min_gap_merge_s} s")
        
        auto_events = detect_events_in_segments(timestamp, mass, segments, detection_params)
        print(f"  Detected {len(auto_events)} candidate events")
        all_events.extend(auto_events)
    
    if not all_events:
        print("\n⚠ No events detected!")
        return
    
    print(f"\nResolving overlaps...")
    print(f"  Events before: {len(all_events)}")
    all_events = remove_duplicates(all_events)
    print(f"  After dedup: {len(all_events)}")
    all_events = resolve_overlaps(all_events)
    print(f"  After overlap resolution: {len(all_events)}")
    
    print(f"\nComputing features...")
    all_events = compute_features_for_events(all_events, timestamp, mass, segments)
    
    # Print summary statistics
    unlabeled = len([e for e in all_events if not e.is_labeled()])
    needs_manual = len([e for e in all_events if e.needs_manual])
    print(f"  Unlabeled: {unlabeled}")
    print(f"  Needs manual review: {needs_manual}")
    
    # Create project
    print(f"\nCreating project...")
    project = Project(
        input_csv_path=str(Path(csv_path).absolute()),
        session_config_path=str(Path(config_path).absolute()),
        session_config_snapshot=config,
        detection_params=detection_params,
        events=all_events
    )
    
    # Save outputs
    project_path = output_dir / "project.json"
    events_csv_path = output_dir / "events_auto.csv"
    
    print(f"\nSaving outputs...")
    save_project(project, str(project_path))
    print(f"  ✓ Saved project: {project_path}")
    
    export_events_csv(all_events, str(events_csv_path))
    print(f"  ✓ Saved events CSV: {events_csv_path}")
    
    print(f"\nSummary:")
    print(f"  Total events: {len(all_events)}")
    print(f"  By source:")
    for source in ['auto', 'acquisition', 'manual']:
        count = len([e for e in all_events if e.source == source])
        if count > 0:
            print(f"    {source}: {count}")


if __name__ == '__main__':
    sys.exit(main())
