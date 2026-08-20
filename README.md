# Uroflow Analysis

Uroflow Analysis is a desktop application for reviewing long-duration uroflowmetry recordings. It combines event detection, manual review, labeling, video matching, and optional spatial annotation in one project-based workflow.

## Features

- Load mass/time-series data from CSV with session metadata from JSON.
- Detect candidate events with configurable slope and mass-change thresholds.
- Review events in synchronized overview, detail, table, gallery, info, and summary views.
- Label events as urine, feces, or bad; adjust boundaries; create or delete events; and undo or redo review actions.
- Match events to timestamped video files.
- Optionally calibrate the cage, mark event locations, and preview or export standardized analysis figures.
- Save the complete review state to a project JSON and export a flat events CSV.

For the complete first-session workflow, see [WALKTHROUGH.md](WALKTHROUGH.md).

## Requirements

- Python 3.10 or newer
- A desktop environment capable of running Qt
- A uroflow CSV and a session configuration JSON
- Optional: timestamped video files for video review and location annotation

## Installation

From the repository root, create a virtual environment and install the package in editable mode:

```bash
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

On macOS or Linux:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

If `python` is not available as a command on Windows, use `py` in its place. Camera calibration and location-based figures also require OpenCV and Matplotlib:

```bash
python -m pip install opencv-python matplotlib
```

For development dependencies, use `python -m pip install -e ".[dev]"`.

## Quick start

1. Start the application with `uroflow-gui`. On Windows, `run_gui.bat` is also available when `uroflow-gui` is on `PATH`.
2. Choose **File > New Project**, then select the uroflow CSV and `session_config.json`. Selecting a video folder is optional.
3. Click **Detect Events**, review the settings, and run detection. Creating a project initially loads acquisition-flag events only; automatic slope detection runs when this button is used.
4. Review and label the candidates in the **Events** table or plots.
5. Press `Ctrl+S` to save the project JSON, then use **Export Events CSV** when the review is ready for downstream analysis.

The application can also open inputs directly from the command line:

```bash
# Create a new project from source data
uroflow-gui --csv path/to/uroflow.csv --config path/to/session_config.json

# Reopen a saved review
uroflow-gui path/to/project_session-name.json
```

Quote paths that contain spaces.

Publication figures can be generated from either a saved project or an exported
events CSV without opening the GUI:

```bash
uroflow-figures path/to/project.json --output path/to/figures
```

The command creates PNG and SVG versions of the available figures at 300 DPI.
A saved project with an accessible raw uroflow CSV produces all six figures;
an events CSV produces the five event-level figures because it does not contain
the raw signal needed for the raw trace figure.

## Input data

### Uroflow CSV

| Column | Status | Description |
| --- | --- | --- |
| `timestamp` | Required | Numeric time in seconds relative to the session. |
| `mass` | Required | Numeric mass in grams; invalid samples may be `NaN`. |
| `wall_clock_time` | Optional | Sample time used to display event times and match videos. |
| `event` | Optional | Acquisition flag. `y`, `yes`, `true`, and `1` are treated as flagged values, case-insensitively. |
| `cage_id`, `rat_id` | Optional | Sample-level metadata loaded with the recording. |

### Session configuration JSON

The file must contain valid JSON. The commonly used metadata fields are `cage_id`, `rat_id`, `start_date`, and `start_time`; end time, acquisition settings, and spatial calibration may also be present. Detection parameters are selected in the **Detect Events** dialog and stored in the saved project.

## Saved files and exports

- **Project JSON** preserves source-file paths, detection settings, events, labels, edits, video-folder selection, and spatial calibration. Keep the source CSV and config with the project when moving an analysis; the application will prompt for replacements if their saved paths cannot be found.
- **Events CSV** contains event timing, labels, source, review flags, computed features, spatial coordinates, and calibration metadata where available.
- **Gallery PNG** is available from the **Gallery** tab.
- **Analysis Figures** previews the spatial/count, radial-distance,
  mass/duration, chronology, cumulative-output, and raw-trace figures. The
  selected plot can be saved as PNG or SVG. **Generate Publication Figures**
  exports the complete set in both formats after locations have been annotated.

Resizing the **Analysis Figures** window changes only the on-screen preview.
Saved figures are rebuilt at their fixed publication canvas sizes and do not
inherit the resized on-screen preview dimensions.

New projects are not autosaved until they have been saved once. After a project path exists, the application autosaves approximately every five minutes and again when it closes.

## Keyboard shortcuts

| Action | Shortcut |
| --- | --- |
| Previous / next event | `Left` / `Right` |
| Label urine / feces / bad | `U` / `F` / `B` |
| Delete selected event | `Delete` or `Backspace` |
| Center overview on selected event | `Ctrl+Shift+C` |
| New / open / save / save as | `Ctrl+N` / `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S` |
| Export events CSV | `Ctrl+E` |
| Undo / redo | `Ctrl+Z` / `Ctrl+Y` |
| Quit | `Ctrl+Q` |

On macOS, standard application shortcuts may use `Command` instead of `Ctrl`.
