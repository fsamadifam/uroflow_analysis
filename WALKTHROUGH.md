# Uroflow Analysis Walkthrough

This walkthrough covers a typical session from raw data to reviewed event exports. For installation, supported inputs, and the shortcut reference, see [README.md](README.md).

## 1. Organize the session files

A convenient session folder contains the source files together:

```text
session-folder/
├── uroflow_<session>.csv
├── session_config.json
└── videos/                  # optional
    └── Replay YYYY-MM-DD HH-MM-SS.mp4
```

Video matching expects filenames that begin with `Replay YYYY-MM-DD HH-MM-SS`; supported extensions are `.mkv`, `.mp4`, `.avi`, `.mov`, and `.webm`. The CSV needs `wall_clock_time`, and the config needs `start_date` and `start_time`, for matching across the session and midnight rollover.

## 2. Start or reopen an analysis

Launch the application:

```bash
uroflow-gui
```

Choose **File > New Project**, select the CSV, and then select the session configuration JSON. If a sibling `videos` folder is found, the application offers to use it; otherwise, a video folder can be skipped or selected manually.

Creating a project loads and segments the trace. If the CSV contains acquisition flags, those events are loaded, but slope-based detection does not run automatically. Save the new project with `Ctrl+S` early so periodic autosave has a destination.

To continue an earlier review, choose **File > Open Project** or pass the project JSON to `uroflow-gui`. If the source CSV or config moved, the application asks you to locate it.

## 3. Get oriented in the workspace

The left side contains two synchronized plots:

- The **overview plot** shows the complete trace, gaps, and event regions. Use box zoom and the scrollbars to move through a zoomed trace, or click **Reset Zoom**.
- The **detail plot** follows the selected event. Drag its start and end boundary lines to refine the event; timing and derived features update automatically.

The right side contains four tabs:

- **Events** provides the sortable, filterable review table and video/location actions.
- **Gallery** renders event thumbnails and can save the gallery as a PNG.
- **Info** shows measurements for the selected event.
- **Summary** aggregates the reviewed events.

Click an event region, table row, or gallery thumbnail to synchronize the selection. Use **Center Plot** (`Ctrl+Shift+C`) when the overview is zoomed away from the selected event. The **Show event markers** checkbox can hide event overlays without changing the project.

## 4. Detect and classify events

Click **Detect Events** above the overview. The dialog separates the settings into four groups:

- **Slope detection** controls the smoothing window and positive-slope threshold.
- **Event filtering** controls duration, gap merging, and minimum cumulative mass change.
- **Advanced parameters** control event-window expansion, baseline estimation, and the required fraction of valid samples.
- **Classification parameters** control the heuristic urine/feces labels.

For a first pass, start with the defaults. Lower slope or mass thresholds generally find more candidates and more noise; larger smoothing windows suppress noise but can blur short events.

The main options have important effects:

- **Clear existing auto/acquisition events before detection** replaces unlocked detected events. Manual and locked events are preserved.
- **Also detect from acquisition flags** supplements slope-based detection with flags from the CSV.
- **Auto-classify events as urine/feces** applies heuristic labels after detection.
- **Classify existing events only** changes labels without creating or removing events.

Review auto-classification as a starting point, not as a substitute for manual review.

## 5. Review the event list

Work through the **Events** table in chronological order:

1. Select an event and inspect the overview, detail trace, feature values, and—when available—its video.
2. Press `U`, `F`, or `B` to label it as urine, feces, or bad. The **Label** cell also provides a drop-down editor.
3. Refine the event by dragging the boundary lines in the detail plot.
4. Check **Locked** for a trusted event that future detection passes should preserve.
5. Check **Needs Manual** when the event requires later adjudication.
6. Delete false candidates with `Delete`, `Backspace`, the table button, or the row context menu.

Use the **Unlabeled only**, **Needs manual**, **Needs location**, and label filters to create focused review queues. The search box matches event IDs and notes. `Ctrl+Z` and `Ctrl+Y` undo or redo label, delete, and detection commands during the current session.

To add a missed event, click **+ Create New Event**, move the green region over the event, adjust its edges, and click **Add Event**. The new event is marked as a manual source and its features are calculated immediately.

## 6. Review associated video (optional)

Set or change the folder through **File > Set Video Folder**. The status bar reports how many parseable video files were found.

Select an event and click **Open Event Video**, double-click its table row, or use the row context menu. Matching uses the event's wall-clock time and the timestamp encoded in each video filename. When several files are plausible, the application asks you to choose.

If no video is found, check all three inputs: the CSV's `wall_clock_time`, the config's `start_date`/`start_time`, and the `Replay YYYY-MM-DD HH-MM-SS` filename pattern.

## 7. Add spatial locations (optional)

Spatial annotation requires the optional OpenCV and Matplotlib packages, a video folder, and a valid camera calibration.

1. Click **Calibrate Camera**.
2. Select a representative video and enter the real cage radius.
3. Click at least five points along the visible edge of the circular cage.
4. Click **Fit & Preview**, inspect the fitted ellipse, and save the calibration.
5. In the Events table, select an event and click **Mark Event Location**.
6. Move the frame-time slider if needed, click the event position in the image, and confirm the location.

Use the **Needs location** filter to find unfinished annotations. The **Spatial Analysis** button opens urine/feces filters, location plots, summary statistics, spatial CSV export, and plot export. Recalibrating later offers to recompute real-world coordinates from the saved image points.

## 8. Save and export

Use `Ctrl+S` throughout review. The project JSON is the editable source of truth; the events CSV is the analysis-ready snapshot.

When review is complete:

1. Save the project.
2. Click **Export Events CSV** in the Events tab or use `Ctrl+E`.
3. Optionally save a gallery PNG from the Gallery tab.
4. If locations were annotated, open **Spatial Analysis** to export its CSV or figures.

Exports do not replace the project JSON. Reopen the JSON whenever labels, event boundaries, or locations need further editing.

## Troubleshooting

- **`uroflow-gui` is not recognized:** activate the virtual environment and reinstall with `python -m pip install -e .`.
- **A new project shows few or no events:** click **Detect Events**; automatic slope detection is intentionally a separate step.
- **A project opens but cannot find its data:** select the relocated CSV and config when prompted, then save the project to retain the new paths.
- **Video buttons are disabled:** set a video folder through the File menu.
- **Videos are present but do not match:** verify the required filename timestamps and session clock metadata.
- **Spatial tools fail to import:** install `opencv-python` and `matplotlib` in the same environment as Uroflow Analysis.
- **Recent work is not autosaving:** save a new project once to establish its project JSON path.
