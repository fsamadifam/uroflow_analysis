# Uroflow Analysis GUI - Quick Start Guide

## Installation

```bash
cd uroflow_analysis
pip install -e .
```

This installs:
- `uroflow-detect`: CLI detection tool
- `uroflow-gui`: GUI application
- All dependencies (PySide6, pyqtgraph, numpy, pandas)

---

## Quick Test with Example Data

### 1. Run CLI Detection

```bash
uroflow-detect \
  example_data/2025_11_19_10_52_09_cage83728_rat1/uroflow_2025_11_19_10_52_09_cage83728_rat1.csv \
  example_data/2025_11_19_10_52_09_cage83728_rat1/session_config.json \
  --output output/
```

**Output:**
```
Loading data from ...
  Loaded 1,728,570 samples
  Duration: 86434.0 seconds (24.0 hours)

Detecting segments and gaps...
  Found 143 segments and 144 gaps
  Valid data: 98.5%

Running auto-detection...
  Parameters:
    Threshold: 0.05 g
    Diff test time: 5.0 s
  Detected 156 candidate events

Resolving overlaps...
  After overlap resolution: 142 events

Summary:
  Total events: 142
  By source:
    acquisition: 38
    auto: 104
```

**Files created:**
- `output/project.json`: Full project state
- `output/events_auto.csv`: Detected events with features

---

### 2. Launch GUI

```bash
uroflow-gui output/project.json
```

**What you'll see:**
- **Overview Plot** (top): 24-hour trace with event overlays
- **Detail Plot** (bottom): Zoomed view around selected event
- **Event Table** (right): All events with columns for ID, start time, duration, delta mass, label
- **Gallery Tab**: Thumbnail grid of events

---

## Workflow

### A. Explore Events

1. **Click** any event in the overview plot or table to select it
2. **Arrow keys** (→/←) to navigate next/previous
3. **Filter** events:
   - Check "Unlabeled only" to see only unlabeled events
   - Check "Needs manual" to see events crossing gaps
   - Use dropdown to filter by label

### B. Label Events

1. Select an event
2. Press hotkey:
   - `U` = urine
   - `F` = feces
   - `B` = bad (artifact)
3. Event color changes immediately
4. Continue to next event

### C. Delete False Positives

1. Select event
2. Press `Delete` key
3. Confirm deletion
4. Use `Ctrl+Z` to undo if needed

### D. Save and Export

1. `Ctrl+S` to save project (or wait for autosave every 5 min)
2. **File → Export Events CSV** to get labeled results
3. Output CSV includes all metadata

---

## Keyboard Shortcuts Reference

### Navigation
| Key | Action |
|-----|--------|
| `→` | Next event |
| `←` | Previous event |
| `Shift+→` | Next unlabeled (with filter on) |
| `Shift+←` | Previous unlabeled (with filter on) |

### Labeling
| Key | Action |
|-----|--------|
| `U` | Label as urine |
| `F` | Label as feces |
| `B` | Label as bad/artifact |

### Editing
| Key | Action |
|-----|--------|
| `Delete` | Delete selected event |
| `Ctrl+Z` | Undo last action |
| `Ctrl+Y` | Redo |

### File Operations
| Key | Action |
|-----|--------|
| `Ctrl+N` | New project |
| `Ctrl+O` | Open project |
| `Ctrl+S` | Save project |
| `Ctrl+E` | Export events CSV |
| `Ctrl+Q` | Quit |

---

## Tips & Tricks

### Fast Labeling Workflow

1. Enable "Unlabeled only" filter
2. Press `U`/`F`/`B` to label
3. Press `→` to go to next unlabeled
4. Repeat

### Review Flagged Events

1. Enable "Needs manual" filter
2. These are events that:
   - Cross gaps in data
   - Have low coverage (<50% valid samples)
3. Review these carefully

### Undo/Redo

- All actions are undoable: labeling, deletion, boundary edits
- Undo stack holds last 100 actions
- Check menu for what will be undone: "Undo: Label event as 'urine'"

### Filtering & Sorting

- **Click column headers** to sort by that column
- **Sort by Duration** to see longest events first
- **Sort by Delta Mass** to see largest mass changes
- **Search box**: Filter by event ID or notes

---

## Customizing Detection Parameters

Edit detection parameters when creating new project or via CLI:

```bash
uroflow-detect data.csv config.json \
  --dt-factor 10.0  # More aggressive gap detection
```

Or edit `project.json` manually and reload.

---

## Troubleshooting

### GUI doesn't start
```bash
# Check dependencies
pip install PySide6 pyqtgraph numpy pandas

# Try running with explicit path
python -m uroflow.gui.app
```

### CSV load error
- Check required columns: `timestamp`, `mass`
- Check for corrupted data (non-numeric values)
- Use CLI `--help` to see validation options

### Plot rendering slow
- Overview plot automatically downsamples to ~10k points
- For very large files (>5M samples), consider preprocessing

### Gallery empty
- Gallery shows first 50 events by default
- This is for performance with large event counts
- Can be increased in `gallery.py` (line 131)

---

## Output Files

### project.json
```json
{
  "input_csv_path": "path/to/data.csv",
  "session_config_path": "path/to/config.json",
  "detection_params": { ... },
  "events": [
    {
      "event_id": "uuid-here",
      "start_idx": 1000,
      "end_idx": 2000,
      "start_time_s": 50.0,
      "end_time_s": 100.0,
      "label_user": "urine",
      "source": "auto",
      "features": { ... }
    },
    ...
  ],
  "created_at": "2026-02-02T...",
  "last_modified": "2026-02-02T..."
}
```

### events_labeled.csv
```csv
event_id,start_idx,end_idx,start_time_s,end_time_s,duration_s,source,locked,label_user,notes,delta_mass_g,peak_slope_g_per_s,...
abc123,1000,2000,50.0,100.0,50.0,auto,False,urine,,2.345,0.156,...
```

---

## Next Steps

1. **Process your own data**:
   ```bash
   uroflow-detect my_data.csv my_config.json
   uroflow-gui project.json
   ```

2. **Adjust detection parameters** based on your data characteristics

3. **Label events** using the fast keyboard workflow

4. **Export results** for downstream analysis (statistics, plots, etc.)

5. **Iterate**: Re-run detection with different parameters if needed
