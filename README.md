# Uroflow Analysis

Uroflow Analysis GUI

## Install

```bash
pip install -e .
```

Dev: `pip install -e ".[dev]"` then `pytest`.

## Commands

```bash
uroflow-detect <data.csv> <session_config.json> --output <dir>
uroflow-gui <dir>/project.json
uroflow-gui --csv <data.csv> --config <session_config.json>
```

`uroflow-detect` writes `project.json` and `events_auto.csv`. Use **QUICKSTART.md** for a full walkthrough and shortcuts.

## Shortcuts

`U`/`F`/`B` urine/feces/bad · `Delete` remove · `→`/`←` next/prev · `Shift+→`/`Shift+←` unlabeled · `[` `]` / `{` `}` nudge start/end · `Ctrl+S` save · `Ctrl+Z`/`Ctrl+Y` undo/redo · `Ctrl+E` export CSV · `Ctrl+O`/`Ctrl+N`/`Ctrl+Q` open/new/quit

## Data

CSV needs `timestamp`, `mass` (g); optional `wall_clock_time`, `event` (acquisition flags), `cage_id`, `rat_id`. Session JSON: cage/rat ids, start date/time, `config_snapshot.threshold` and `diff_test_time` (see `example_data/`).



