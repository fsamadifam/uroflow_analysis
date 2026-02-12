# Uroflow Analysis GUI

GUI tool for analyzing 24-hour rat uroflowmetry data with auto-detection, manual labeling, and event management.

## Features

- **Auto-detection**: Segment-wise event detection with deterministic thresholds
- **Manual labeling**: Hotkey-based rapid annotation (U/F/B for urine/feces/bad)
- **Event deletion**: Remove false positives with undo/redo support
- **Manual windows**: Box tool for creating custom event boundaries
- **Boundary editing**: Drag event start/end with real-time feature recomputation
- **Event gallery**: Visual thumbnail overview of all detected events
- **Triage filters**: Sort and filter by unlabeled, needs manual, duration, delta mass
- **Project persistence**: Save/load analysis state with JSON serialization

## Installation

```bash
pip install -e .
```

## Usage

### CLI Mode (Baseline Detection)

```bash
uroflow-detect path/to/data.csv path/to/session_config.json --output output_dir/
```

Generates:
- `events_auto.csv`: Detected events with features
- `project.json`: Full project state for GUI

### GUI Mode

```bash
uroflow-gui path/to/project.json
```

Or create new project:

```bash
uroflow-gui --csv path/to/data.csv --config path/to/session_config.json
```

## Keyboard Shortcuts

- `U` / `F` / `B`: Label event as urine / feces / bad
- `Delete`: Remove selected event
- `→` / `←`: Next / previous event
- `Shift+→` / `Shift+←`: Next / previous unlabeled event
- `[` / `]`: Nudge start boundary
- `{` / `}`: Nudge end boundary
- `Ctrl+S`: Save project
- `Ctrl+Z` / `Ctrl+Y`: Undo / redo

## Design Principles

1. **No imputation**: Missing data stays missing; no interpolation or forward-filling
2. **Segment-wise computation**: Events computed only within contiguous valid spans
3. **Non-overlapping events**: Deterministic overlap resolution with priority rules
4. **Immutable raw data**: All edits stored in project state, not raw CSV

## Data Format

### Input CSV

Required columns:
- `mass` (float): Mass in grams (can contain NaN)
- `timestamp` (float): Seconds since session start
- `wall_clock_time` (str, optional): Wall clock timestamp
- `event` (str, optional): Acquisition flags ('y'/'n')
- `cage_id`, `rat_id` (optional): Metadata

### Session Config (JSON)

```json
{
  "cage_id": "83728",
  "rat_id": 1,
  "start_date": "2025-11-19",
  "start_time": "10:52:09",
  "config_snapshot": {
    "threshold": 0.05,
    "diff_test_time": 5.0
  }
}
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
