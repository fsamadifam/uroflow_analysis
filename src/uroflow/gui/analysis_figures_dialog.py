"""Tabbed preview and export dialog for analysis figures."""

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from uroflow.reporting.figures import (
    build_publication_figures,
    generate_publication_figures,
    project_to_dataframe,
)


class AnalysisFiguresDialog(QDialog):
    """Show the standard analysis figures and export them together."""

    def __init__(self, project, default_output_dir: str | Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Analysis Figures")
        self.resize(1100, 760)
        self._default_output_dir = Path(default_output_dir)
        self._data = project_to_dataframe(project)
        self._figures = build_publication_figures(self._data)

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._canvases = []
        for _stem, title, figure in self._figures:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            canvas = FigureCanvas(figure)
            self._canvases.append(canvas)
            page_layout.addWidget(canvas)
            self._tabs.addTab(page, title)
        layout.addWidget(self._tabs)

        buttons = QHBoxLayout()

        save_png_button = QPushButton("Save Current PNG...")
        save_png_button.clicked.connect(lambda: self._save_current("png"))
        buttons.addWidget(save_png_button)

        save_svg_button = QPushButton("Save Current SVG...")
        save_svg_button.clicked.connect(lambda: self._save_current("svg"))
        buttons.addWidget(save_svg_button)

        buttons.addStretch()

        generate_button = QPushButton("Generate Publication Figures...")
        generate_button.clicked.connect(self._generate_all)
        buttons.addWidget(generate_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _save_current(self, file_format: str):
        current_index = self._tabs.currentIndex()
        stem, _title, _preview_figure = self._figures[current_index]
        default_path = self._default_output_dir / f"{stem}.{file_format}"
        file_filter = (
            "PNG Images (*.png)" if file_format == "png" else "SVG Images (*.svg)"
        )
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Save Current Figure as {file_format.upper()}",
            str(default_path),
            file_filter,
        )
        if not output_path:
            return

        path = Path(output_path).with_suffix(f".{file_format}")
        export_figures = []
        try:
            export_figures = build_publication_figures(self._data)
            figure = export_figures[current_index][2]
            figure.savefig(path, dpi=300)
            self._default_output_dir = path.parent
            QMessageBox.information(self, "Figure Saved", f"Saved figure to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Figure Save Error", str(exc))
        finally:
            for _stem, _title, figure in export_figures:
                figure.clear()

    def _generate_all(self):
        output_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Figure Output Folder",
            str(self._default_output_dir),
        )
        if not output_dir:
            return

        try:
            paths = generate_publication_figures(self._data, output_dir)
            self._default_output_dir = Path(output_dir)
            QMessageBox.information(
                self,
                "Publication Figures Generated",
                f"Generated {len(paths)} files in:\n{output_dir}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Figure Generation Error", str(exc))
