# Quick start

## Install

```bash
cd uroflow_analysis
pip install -e .
```

## Example

```bash
uroflow-detect \
  example_data/2025_11_19_10_52_09_cage83728_rat1/uroflow_2025_11_19_10_52_09_cage83728_rat1.csv \
  example_data/2025_11_19_10_52_09_cage83728_rat1/session_config.json \
  --output output/

uroflow-gui output/project.json
```

Outputs: `output/project.json`, `output/events_auto.csv`.

## GUI

Overview (full trace + events), detail view, sortable table, gallery. Select from plot or table; filter unlabeled / needs manual; `Ctrl+S` saves (autosave ~5 min); **File → Export Events CSV** for labels + metadata.

## Shortcuts

| Navigation | Labeling | Edit / file |
|------------|----------|-------------|
| `→` / `←` next/prev | `U` / `F` / `B` | `Delete` remove |
| `Shift+→` / `Shift+←` unlabeled | | `Ctrl+Z` / `Ctrl+Y` |
| | | `Ctrl+S` save · `Ctrl+E` export · `Ctrl+N`/`Ctrl+O`/`Ctrl+Q` |

Boundary nudge: `[` `]` start, `{` `}` end.





