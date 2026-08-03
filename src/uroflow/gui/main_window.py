"""Main window for uroflow analysis GUI."""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QLabel, QFileDialog, QMessageBox, QStatusBar,
    QMenuBar, QPushButton, QProgressDialog, QApplication,
    QDialog, QFormLayout, QDoubleSpinBox, QDialogButtonBox, QMenu
)
from PySide6.QtCore import Qt, Signal, QTimer, QObject
from PySide6.QtGui import QAction, QKeySequence
from pathlib import Path
from typing import Optional
import time
import numpy as np

from uroflow.core.types import Project, DetectionParams
from uroflow.core.project_io import (
    load_project, save_project, autosave_project, standard_session_name,
)
from uroflow.core.video import find_sibling_videos_folder, get_video_files
from uroflow.io.load_csv import load_uroflow_csv, find_acquisition_event_windows
from uroflow.io.load_config import load_session_config
from uroflow.core.segments import find_segments_and_gaps
from uroflow.core.detect import detect_events_in_segments, detect_from_acquisition_flags
from uroflow.core.features import compute_features_for_events
from uroflow.core.overlap import resolve_overlaps, remove_duplicates
from uroflow.gui.plots import OverviewPlot, DetailPlot
from uroflow.gui.event_widget import EventWidget
from uroflow.gui.gallery import EventGallery
from uroflow.gui.info_panel import InfoPanel
from uroflow.gui.summary_panel import SummaryPanel
from uroflow.gui.actions import UndoStack, LabelEventCommand, DeleteEventCommand, DetectEventsCommand
from uroflow.gui.detect_events_dialog import DetectEventsDialog


def _event_interval_distance_s(event, reference_event) -> float:
    """Return seconds between two event windows, or 0 if they overlap."""
    if event.overlaps_with(reference_event):
        return 0.0
    if event.end_time_s <= reference_event.start_time_s:
        return reference_event.start_time_s - event.end_time_s
    return event.start_time_s - reference_event.end_time_s


def _filter_supplemental_acquisition_events(acq_events: list,
                                            reference_events: list,
                                            min_separation_s: float) -> tuple[list, int]:
    """Keep acquisition events only when they are not near refined events."""
    if not acq_events or not reference_events:
        return acq_events, 0

    filtered = []
    skipped = 0

    for acq_event in acq_events:
        has_nearby_reference = any(
            _event_interval_distance_s(acq_event, reference_event) <= min_separation_s
            for reference_event in reference_events
        )

        if has_nearby_reference:
            skipped += 1
            continue

        acq_event.needs_manual = True
        if acq_event.notes:
            acq_event.notes += " (no nearby auto detection)"
        else:
            acq_event.notes = "From acquisition flags (no nearby auto detection)"
        filtered.append(acq_event)

    return filtered, skipped


class MainWindow(QMainWindow):
    """Main application window."""
    
    # Signals
    project_loaded = Signal()
    current_event_changed = Signal(str)  # event_id
    
    def __init__(self):
        super().__init__()
        
        try:
            # State
            self.project = None
            self.project_path = None
            self.last_save_time = None
            self.autosave_interval = 300.0  # 5 minutes
            
            # Data arrays (loaded with project)
            self.timestamp = None
            self.mass = None
            self.segments = None
            self.gaps = None
            self.metadata = None
            
            # Current selection
            self.current_event_id = None
            self._selecting_event = False  # Flag to prevent recursive selection
            
            # Undo/redo stack
            self.undo_stack = UndoStack()
            
            # Debounce timer for boundary changes (prevents crash from rapid updates)
            self._boundary_change_timer = QTimer()
            self._boundary_change_timer.setSingleShot(True)
            self._boundary_change_timer.timeout.connect(self._apply_boundary_change)
            self._pending_boundary_change = None  # (event_id, start, end)
            
            # Setup UI
            self.setWindowTitle("Uroflow Analysis")
            self.resize(1920, 1080)
            
            print("Setting up UI...")
            self._setup_ui()
            print("Creating menus...")
            self._create_menus()
            print("Creating status bar...")
            self._create_status_bar()
            print("Setting up autosave timer...")
            self._setup_autosave_timer()
            
            self.show_welcome_message()
            print("MainWindow initialization complete!")
            
        except Exception as e:
            import traceback
            error_msg = f"Error initializing MainWindow:\n\n{str(e)}\n\n{traceback.format_exc()}"
            print(error_msg)
            QMessageBox.critical(None, "Initialization Error", error_msg)
            raise
    
    def _setup_ui(self):
        """Setup main UI layout."""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Main splitter (horizontal)
        main_splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(main_splitter)
        
        # Left panel: plots
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)
        
        # Overview plot
        self.overview_plot = OverviewPlot()
        self.overview_plot.setMinimumHeight(200)
        self.overview_plot.event_clicked.connect(self._on_event_selected)
        self.overview_plot.manual_event_requested.connect(self._on_manual_event_requested)
        self.overview_plot.create_event_confirmed.connect(self._on_manual_event_requested)
        self.overview_plot.detect_events_requested.connect(self._show_detect_events_dialog)
        self.overview_plot.calibrate_camera_requested.connect(
            self._open_calibration_dialog
        )
        self.overview_plot.spatial_analysis_requested.connect(
            self._open_spatial_analysis
        )
        left_layout.addWidget(self.overview_plot, stretch=2)
        
        # Detail plot
        self.detail_plot = DetailPlot()
        self.detail_plot.setMinimumHeight(200)
        self.detail_plot.boundary_changed.connect(self._on_boundary_changed)
        left_layout.addWidget(self.detail_plot, stretch=1)
        
        main_splitter.addWidget(left_panel)
        
        # Right panel: tabs
        right_panel = QTabWidget()
        
        # Event table tab
        self.event_widget = EventWidget()
        self.event_widget.event_selected.connect(self._on_event_selected)
        self.event_widget.center_plot_requested.connect(self._on_center_plot_requested)
        self.event_widget.next_event_requested.connect(self._on_next_event)
        self.event_widget.prev_event_requested.connect(self._on_prev_event)
        self.event_widget.delete_event_requested.connect(self._delete_event)
        self.event_widget.event_label_changed.connect(self._on_table_event_label_changed)
        self.event_widget.mark_event_location_requested.connect(
            self._open_annotation_dialog
        )
        right_panel.addTab(self.event_widget, "Events")
        
        # Event gallery tab
        self.event_gallery = EventGallery()
        self.event_gallery.event_selected.connect(self._on_event_selected)
        right_panel.addTab(self.event_gallery, "Gallery")
        
        # Info tab
        self.info_widget = InfoPanel()
        right_panel.addTab(self.info_widget, "Info")
        
        # Summary tab
        self.summary_widget = SummaryPanel()
        right_panel.addTab(self.summary_widget, "Summary")
        
        main_splitter.addWidget(right_panel)
        
        # Set splitter sizes (60% plots, 40% table/gallery)
        main_splitter.setSizes([960, 640])
    
    def _create_menus(self):
        """Create menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        new_action = QAction("&New Project...", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self.new_project_dialog)
        file_menu.addAction(new_action)
        
        open_action = QAction("&Open Project...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.open_project_dialog)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        save_action = QAction("&Save Project", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_project_action)
        file_menu.addAction(save_action)
        
        save_as_action = QAction("Save Project &As...", self)
        save_as_action.setShortcut(QKeySequence.SaveAs)
        save_as_action.triggered.connect(self.save_project_as_dialog)
        file_menu.addAction(save_as_action)
        
        file_menu.addSeparator()
        
        export_action = QAction("&Export Events CSV...", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self.export_events_dialog)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        video_folder_action = QAction("Set &Video Folder...", self)
        video_folder_action.triggered.connect(self._select_video_folder_dialog)
        file_menu.addAction(video_folder_action)
        
        file_menu.addSeparator()
        
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        
        self.undo_action = QAction("&Undo", self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.triggered.connect(self._do_undo)
        edit_menu.addAction(self.undo_action)
        
        self.redo_action = QAction("&Redo", self)
        self.redo_action.setShortcut(QKeySequence.Redo)
        self.redo_action.triggered.connect(self._do_redo)
        edit_menu.addAction(self.redo_action)
        
        self._update_undo_redo_actions()
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)
    
    def _create_status_bar(self):
        """Create status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Status labels
        self.status_label = QLabel("No project loaded")
        self.status_bar.addWidget(self.status_label)
        
        self.status_bar.addPermanentWidget(QLabel("|"))
        
        self.events_count_label = QLabel("0 events")
        self.status_bar.addPermanentWidget(self.events_count_label)
        
        self.status_bar.addPermanentWidget(QLabel("|"))
        
        self.unlabeled_count_label = QLabel("0 unlabeled")
        self.status_bar.addPermanentWidget(self.unlabeled_count_label)
        
        self.status_bar.addPermanentWidget(QLabel("|"))
        
        self.video_folder_label = QLabel("Video: not set")
        self.status_bar.addPermanentWidget(self.video_folder_label)
    
    def _setup_autosave_timer(self):
        """Setup autosave timer."""
        self.autosave_timer = QTimer()
        self.autosave_timer.timeout.connect(self.autosave)
        self.autosave_timer.start(60000)  # Check every minute
    
    def show_welcome_message(self):
        """Show welcome message in status bar."""
        self.status_label.setText("Welcome! Open a project or create a new one from File menu")
    
    def load_project(self, project_path: str):
        """Load project from file."""
        try:
            # Load project
            project = load_project(project_path)
            if not self._resolve_missing_project_files(project, project_path):
                return

            # Show progress dialog
            progress = QProgressDialog("Loading project...", None, 0, 4, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setValue(0)

            self.project = project
            self.project_path = project_path
            progress.setValue(1)
            
            # Load CSV data
            progress.setLabelText("Loading CSV data...")
            self.timestamp, self.mass, _, self.metadata = load_uroflow_csv(self.project.input_csv_path)
            # Add timestamp to metadata for wall clock time lookup
            if self.metadata is None:
                self.metadata = {}
            self.metadata['timestamp'] = self.timestamp
            progress.setValue(2)
            
            # Compute segments (use default dt_factor=5.0 for gap detection)
            progress.setLabelText("Computing segments...")
            self.segments, self.gaps = find_segments_and_gaps(
                self.timestamp, self.mass,
                dt_factor=5.0
            )
            progress.setValue(3)
            
            # Populate wall_clock_time for events that don't have it (backwards compatibility)
            self._populate_event_wall_clock_times()
            
            # Update UI
            progress.setLabelText("Updating UI...")
            self.last_save_time = time.time()
            self._update_ui_after_load()
            progress.setValue(4)
            
            self.status_label.setText(f"Loaded: {Path(project_path).name}")
            self.project_loaded.emit()
            
            # Prompt for video folder if not set
            if not self.project.video_folder_path:
                self._prompt_video_folder_for_existing_project()
            
        except Exception as e:
            QMessageBox.critical(self, "Error Loading Project", str(e))

    def _resolve_missing_project_files(self, project: Project, project_path: str) -> bool:
        """Let the user replace saved input paths that are no longer available.

        Moving a project independently of its source files is common.  The
        project retains its analysis state, while the replacement paths point
        it at the same CSV and session configuration in their new locations.
        """
        csv_is_missing = not Path(project.input_csv_path).is_file()
        config_is_missing = not Path(project.session_config_path).is_file()
        if not csv_is_missing and not config_is_missing:
            return True

        missing_files = []
        if csv_is_missing:
            missing_files.append(f"CSV file:\n{project.input_csv_path}")
        if config_is_missing:
            missing_files.append(f"Session config file:\n{project.session_config_path}")

        QMessageBox.warning(
            self,
            "Project Files Not Found",
            "The project refers to file(s) that could not be found:\n\n"
            + "\n\n".join(missing_files)
            + "\n\nSelect the replacement file(s) to continue loading the project.",
        )

        project_folder = str(Path(project_path).parent)
        csv_path = project.input_csv_path
        config_path = project.session_config_path
        config_snapshot = project.session_config_snapshot

        if csv_is_missing:
            csv_path, _ = QFileDialog.getOpenFileName(
                self, "Locate Project CSV File", project_folder, "CSV Files (*.csv)"
            )
            if not csv_path:
                return False

        if config_is_missing:
            config_start_folder = str(Path(csv_path).parent) if csv_path else project_folder
            config_path, _ = QFileDialog.getOpenFileName(
                self,
                "Locate Session Config File",
                config_start_folder,
                "JSON Files (*.json)",
            )
            if not config_path:
                return False
            # The selected config is now the project's source of truth.
            config_snapshot = load_session_config(config_path)

        project.input_csv_path = str(Path(csv_path).absolute())
        project.session_config_path = str(Path(config_path).absolute())
        project.session_config_snapshot = config_snapshot
        project.update_modified()
        return True
    
    def _prompt_video_folder_for_existing_project(self):
        """Prompt user to select video folder for an existing project without one."""
        # Check for sibling videos folder first
        default_folder = find_sibling_videos_folder(self.project.input_csv_path)
        
        if default_folder:
            reply = QMessageBox.question(
                self, "Select Video Folder",
                f"This project has no video folder set.\n\n"
                f"Found videos folder:\n{default_folder}\n\n"
                f"Use this folder?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Ignore,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.Yes:
                self.set_video_folder(default_folder)
                return
            elif reply == QMessageBox.Ignore:
                return
        
        # Ask if they want to select a folder
        reply = QMessageBox.question(
            self, "Select Video Folder",
            "This project has no video folder set.\n\n"
            "Would you like to select one now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            folder = QFileDialog.getExistingDirectory(
                self, "Select Video Folder",
                str(Path(self.project.input_csv_path).parent)
            )
            if folder:
                self.set_video_folder(folder)
    
    def create_new_project(self, csv_path: str, config_path: str, video_folder: Optional[str] = None):
        """Create new project from CSV and config.
        
        Args:
            csv_path: Path to uroflow CSV file
            config_path: Path to session config JSON file
            video_folder: Optional path to video folder
        """
        print(f"\n{'='*60}")
        print(f"create_new_project called")
        print(f"  CSV: {csv_path}")
        print(f"  Config: {config_path}")
        print(f"  Video folder: {video_folder}")
        print(f"{'='*60}\n")
        
        try:
            # Validate paths first
            if not Path(csv_path).exists():
                QMessageBox.critical(self, "Error", f"CSV file not found: {csv_path}")
                return
            
            if not Path(config_path).exists():
                QMessageBox.critical(self, "Error", f"Config file not found: {config_path}")
                return
            
            # Show progress dialog
            progress = QProgressDialog("Creating project...", None, 0, 6, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setCancelButton(None)  # Disable cancel button
            progress.setValue(0)
            progress.show()
            QApplication.processEvents()  # Process events to show dialog
            
            # Load data
            progress.setLabelText("Loading CSV...")
            QApplication.processEvents()
            timestamp, mass, acquisition_events, metadata = load_uroflow_csv(csv_path)
            progress.setValue(1)
            QApplication.processEvents()
            
            progress.setLabelText("Loading config...")
            QApplication.processEvents()
            config = load_session_config(config_path)
            progress.setValue(2)
            QApplication.processEvents()
            
            # Create detection params
            detection_params = DetectionParams.from_session_config(config)
            
            # Find segments (use default dt_factor=5.0 for gap detection)
            progress.setLabelText("Finding segments...")
            QApplication.processEvents()
            segments, gaps = find_segments_and_gaps(timestamp, mass, dt_factor=5.0)
            progress.setValue(3)
            QApplication.processEvents()
            
            # Load only acquisition events (no auto-detection on load)
            progress.setLabelText("Loading acquisition events...")
            QApplication.processEvents()
            events = []
            
            # From acquisition flags only
            if acquisition_events.any():
                from uroflow.io.load_csv import find_acquisition_event_windows
                from uroflow.core.detect import detect_from_acquisition_flags
                acq_windows = find_acquisition_event_windows(timestamp, acquisition_events)
                acq_events = detect_from_acquisition_flags(timestamp, mass, acq_windows, segments)
                events.extend(acq_events)
                print(f"Loaded {len(acq_events)} acquisition events")
            
            progress.setValue(4)
            QApplication.processEvents()
            
            # Compute features for acquisition events only
            if events:
                progress.setLabelText("Computing features...")
                QApplication.processEvents()
                from uroflow.core.features import compute_features_for_events
                events = compute_features_for_events(
                    events,
                    timestamp,
                    mass,
                    segments,
                    metadata,
                    baseline_window_s=detection_params.baseline_window_s,
                )
                print(f"Computed features for {len(events)} events")
            
            progress.setValue(5)
            QApplication.processEvents()
            
            # Create project
            self.project = Project(
                input_csv_path=str(Path(csv_path).absolute()),
                session_config_path=str(Path(config_path).absolute()),
                session_config_snapshot=config,
                detection_params=detection_params,
                events=events,
                video_folder_path=video_folder
            )
            
            self.timestamp = timestamp
            self.mass = mass
            self.segments = segments
            self.gaps = gaps
            self.metadata = metadata
            # Add timestamp to metadata for wall clock time lookup
            if self.metadata is None:
                self.metadata = {}
            self.metadata['timestamp'] = timestamp
            
            # Update UI
            progress.setLabelText("Updating UI...")
            QApplication.processEvents()
            self._update_ui_after_load()
            progress.setValue(6)
            QApplication.processEvents()
            
            # Close progress dialog
            progress.close()
            
            self.status_label.setText(f"New project created ({len(events)} events)")
            self.project_loaded.emit()
            
        except Exception as e:
            import traceback
            error_msg = f"Error creating project:\n\n{str(e)}\n\n{traceback.format_exc()}"
            print(f"\n{'='*60}")
            print(f"ERROR IN create_new_project:")
            print(error_msg)
            print(f"{'='*60}\n")
            
            try:
                QMessageBox.critical(self, "Error Creating Project", error_msg)
            except:
                print("Failed to show error dialog")
            
            # Don't re-raise - keep window open
            return
    
    def _update_ui_after_load(self):
        """Update UI components after loading project."""
        print(f"_update_ui_after_load called")
        print(f"  Project: {self.project is not None}")
        print(f"  Timestamp: {self.timestamp is not None}, len={len(self.timestamp) if self.timestamp is not None else 0}")
        print(f"  Mass: {self.mass is not None}, len={len(self.mass) if self.mass is not None else 0}")
        print(f"  Segments: {len(self.segments) if self.segments else 0}")
        print(f"  Gaps: {len(self.gaps) if self.gaps else 0}")
        
        if self.project:
            n_events = len(self.project.events)
            n_unlabeled = len(self.project.get_unlabeled_events())
            print(f"  Events: {n_events}")
            print(f"  Unlabeled: {n_unlabeled}")
            
            self.events_count_label.setText(f"{n_events} events")
            self.unlabeled_count_label.setText(f"{n_unlabeled} unlabeled")
            
            # Update plots
            print("  Updating overview plot...")
            self.overview_plot.set_data(
                self.timestamp, self.mass,
                self.segments, self.gaps,
                self.project.events
            )
            print("  Updating detail plot...")
            self.detail_plot.set_data(self.timestamp, self.mass)
            
            # Update event table
            print("  Updating event table...")
            self.event_widget.set_events(self.project.events, self.metadata)
            self.event_widget.set_session_config(self.project.session_config_snapshot)
            
            # Update event gallery
            print("  Updating event gallery...")
            try:
                self.event_gallery.set_export_base_name(self.project.input_csv_path)
                self.event_gallery.set_data(self.timestamp, self.mass, self.project.events)
            except Exception as e:
                print(f"  ERROR updating gallery: {e}")
                import traceback
                traceback.print_exc()
            
            # Update summary panel
            print("  Updating summary panel...")
            try:
                self.summary_widget.set_events(self.project.events)
            except Exception as e:
                print(f"  ERROR updating summary: {e}")
                import traceback
                traceback.print_exc()
            
            # Update video folder status
            print("  Updating video folder status...")
            self._update_video_folder_status()
            
            # Notify event widget about video folder
            if self.project.video_folder_path:
                self.event_widget.set_video_folder(
                    self.project.video_folder_path,
                    self.project.session_config_snapshot
                )
            
            # Select first event if available
            if self.project.events:
                print(f"  Selecting first event: {self.project.events[0].event_id}")
                try:
                    self.current_event_id = self.project.events[0].event_id
                    self._on_event_selected(self.current_event_id)
                    print(f"  Event selected successfully")
                except Exception as e:
                    print(f"  ERROR selecting event: {e}")
                    import traceback
                    traceback.print_exc()
            
            print("  UI update complete!")
            print("  Forcing UI refresh...")
            QApplication.processEvents()  # Force UI update
            print("  All done! GUI should be visible and responsive.")
            print(f"{'='*60}\n")
    
    def _populate_event_wall_clock_times(self):
        """Populate wall_clock_time for events that don't have it.
        
        This provides backwards compatibility for projects created before
        wall_clock_time was populated on events.
        """
        if not self.project or not self.metadata:
            return
        
        wall_clock_times = self.metadata.get('wall_clock_time')
        if wall_clock_times is None:
            return
        
        n_updated = 0
        for event in self.project.events:
            if not event.wall_clock_time:
                idx = event.start_idx
                if 0 <= idx < len(wall_clock_times):
                    wct = wall_clock_times[idx]
                    if wct:
                        event.wall_clock_time = str(wct)
                        n_updated += 1
        
        if n_updated > 0:
            print(f"  Populated wall_clock_time for {n_updated} events")
    
    def new_project_dialog(self):
        """Show new project dialog."""
        csv_path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV File", "", "CSV Files (*.csv)"
        )
        
        if csv_path:
            config_path, _ = QFileDialog.getOpenFileName(
                self, "Select Session Config", str(Path(csv_path).parent), "JSON Files (*.json)"
            )
            
            if config_path:
                # Ask for optional video folder
                video_folder = self._prompt_video_folder(csv_path)
                self.create_new_project(csv_path, config_path, video_folder)
    
    def _prompt_video_folder(self, csv_path: str) -> Optional[str]:
        """Prompt user to select video folder (optional).
        
        Pre-fills with sibling 'videos' folder if it exists.
        
        Args:
            csv_path: Path to CSV file (for finding sibling folder)
            
        Returns:
            Video folder path or None if skipped
        """
        # Check for sibling videos folder
        default_folder = find_sibling_videos_folder(csv_path)
        
        if default_folder:
            # Ask if they want to use the detected folder
            reply = QMessageBox.question(
                self, "Video Folder Found",
                f"Found videos folder:\n{default_folder}\n\nUse this folder for event videos?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.Yes:
                return default_folder
            elif reply == QMessageBox.Cancel:
                return None
            # If No, continue to folder selection dialog
        
        # Show folder selection dialog
        reply = QMessageBox.question(
            self, "Select Video Folder",
            "Would you like to select a video folder?\n\n"
            "(You can skip this and set it later)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            folder = QFileDialog.getExistingDirectory(
                self, "Select Video Folder",
                str(Path(csv_path).parent) if csv_path else ""
            )
            return folder if folder else None
        
        return None
    
    def _update_video_folder_status(self):
        """Update the video folder status label."""
        if self.project and self.project.video_folder_path:
            folder_path = Path(self.project.video_folder_path)
            if folder_path.exists():
                # Count video files
                videos = get_video_files(str(folder_path))
                n_videos = len(videos)
                self.video_folder_label.setText(f"Video: {folder_path.name} ({n_videos} files)")
            else:
                self.video_folder_label.setText(f"Video: {folder_path.name} (not found)")
        else:
            self.video_folder_label.setText("Video: not set")
    
    def set_video_folder(self, folder_path: Optional[str]):
        """Set the video folder for the current project.
        
        Args:
            folder_path: Path to video folder, or None to clear
        """
        if not self.project:
            return
        
        self.project.video_folder_path = folder_path
        self.project.update_modified()
        self._update_video_folder_status()
        
        # Notify event widget about video folder change
        if hasattr(self, 'event_widget'):
            self.event_widget.set_video_folder(
                folder_path,
                self.project.session_config_snapshot if self.project else None
            )
    
    def _select_video_folder_dialog(self):
        """Show dialog to select or change video folder."""
        if not self.project:
            QMessageBox.warning(self, "No Project", "Please load a project first.")
            return
        
        # Show current folder if set
        current_folder = self.project.video_folder_path or ""
        
        if current_folder:
            reply = QMessageBox.question(
                self, "Change Video Folder",
                f"Current video folder:\n{current_folder}\n\n"
                "Do you want to change it?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Reset,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                return
            elif reply == QMessageBox.Reset:
                self.set_video_folder(None)
                self.status_label.setText("Video folder cleared")
                return
        
        # Show folder selection dialog
        folder = QFileDialog.getExistingDirectory(
            self, "Select Video Folder",
            current_folder or str(Path(self.project.input_csv_path).parent)
        )
        
        if folder:
            self.set_video_folder(folder)
            videos = get_video_files(folder)
            self.status_label.setText(f"Video folder set: {len(videos)} video files found")
    
    def open_project_dialog(self):
        """Show open project dialog."""
        project_path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "Project Files (*.json)"
        )
        
        if project_path:
            self.load_project(project_path)
    
    def save_project_action(self):
        """Save current project."""
        if not self.project:
            return
        
        if not self.project_path:
            self.save_project_as_dialog()
            return
        
        try:
            save_project(self.project, self.project_path)
            self.last_save_time = time.time()
            self.status_label.setText(f"Saved: {Path(self.project_path).name}")
        except Exception as e:
            QMessageBox.critical(self, "Error Saving Project", str(e))
    
    def save_project_as_dialog(self):
        """Show save project as dialog."""
        if not self.project:
            return

        csv_p = Path(self.project.input_csv_path)
        session_name = standard_session_name(
            self.project.input_csv_path,
            self.project.session_config_snapshot,
        )
        project_name = f"project_{session_name}.json" if session_name else "project.json"
        default_path = str(csv_p.parent / project_name)

        project_path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", default_path, "Project Files (*.json)"
        )
        
        if project_path:
            self.project_path = project_path
            self.save_project_action()
    
    def export_events_dialog(self):
        """Show export events dialog."""
        if not self.project:
            return
        
        from uroflow.core.project_io import export_events_csv
        
        session_name = standard_session_name(
            self.project.input_csv_path,
            self.project.session_config_snapshot,
        )
        events_name = f"events_table_{session_name}.csv" if session_name else "events_table.csv"
        default_path = str(Path(self.project.input_csv_path).parent / events_name)
        csv_path, _ = QFileDialog.getSaveFileName(
            self, "Export Events", default_path, "CSV Files (*.csv)"
        )
        
        if csv_path:
            try:
                export_events_csv(
                    self.project.events,
                    csv_path,
                    spatial_calibration=self.project.spatial_calibration,
                )
                QMessageBox.information(self, "Export Complete", f"Exported {len(self.project.events)} events")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))
    
    def autosave(self):
        """Autosave project if needed."""
        if self.project and self.project_path:
            new_save_time = autosave_project(
                self.project, self.project_path,
                self.autosave_interval, self.last_save_time
            )
            if new_save_time:
                self.last_save_time = new_save_time
    
    def show_about_dialog(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Uroflow Analysis",
            "Uroflow Analysis GUI v0.1.0\n\n"
            "Tool for analyzing 24-hour uroflowmetry data with auto-detection, "
            "manual labeling, and event management.\n\n"
            "© 2026 Uroflow Project"
        )
    
    # --- Spatial calibration and annotation ---
    
    def _open_calibration_dialog(self):
        """Open spatial calibration dialog."""
        from uroflow.spatial.gui.calibration_dialog import CalibrationDialog

        if not self.project:
            QMessageBox.warning(self, "No Project", "Please load or create a project first.")
            return
        
        video_folder = ""
        config_path = ""
        
        video_folder = self.project.video_folder_path or ""
        config_path = self.project.session_config_path or ""
        
        dialog = CalibrationDialog(
            video_folder=video_folder,
            config_path=config_path,
            parent=self,
        )
        dialog.calibration_saved.connect(self._on_calibration_saved)
        dialog.exec()
    
    def _on_calibration_saved(self, cal_data):
        """Handle calibration saved from dialog.
        
        Args:
            cal_data: CalibrationData object from the dialog
        """
        if self.project:
            self.project.spatial_calibration = cal_data.to_dict()
            self.project.update_modified()
            
            # Check if any events have spatial coordinates that need recalculation
            events_with_coords = [
                e for e in self.project.events if e.spatial_coords is not None
            ]
            
            if events_with_coords:
                # Ask user if they want to recalculate
                reply = QMessageBox.question(
                    self, "Recalculate Event Locations",
                    f"{len(events_with_coords)} event(s) have spatial locations.\n\n"
                    "Do you want to recalculate their real-world coordinates\n"
                    "using the new calibration?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                
                if reply == QMessageBox.Yes:
                    n_updated = self._recalculate_event_spatial_coords(cal_data)
                    self.status_label.setText(
                        f"Calibration saved, {n_updated} event location(s) recalculated"
                    )
                else:
                    self.status_label.setText("Spatial calibration saved to project")
            else:
                self.status_label.setText("Spatial calibration saved to project")
        else:
            self.status_label.setText("Spatial calibration saved")
    
    def _recalculate_event_spatial_coords(self, cal_data):
        """Recalculate real-world coordinates for all events using new calibration.
        
        Args:
            cal_data: CalibrationData object with new calibration
            
        Returns:
            Number of events updated
        """
        from uroflow.spatial.transform import transform_point
        
        n_updated = 0
        for event in self.project.events:
            if event.spatial_coords is not None:
                # Get saved image coordinates
                img_x = event.spatial_coords.image_x
                img_y = event.spatial_coords.image_y
                
                # Transform using new calibration
                result = transform_point(img_x, img_y, cal_data)
                if result is not None:
                    real_x, real_y = result
                    event.spatial_coords.real_x_cm = real_x
                    event.spatial_coords.real_y_cm = real_y
                    event.update_modified()
                    n_updated += 1
        
        if n_updated > 0:
            self.project.update_modified()
        
        return n_updated
    
    def _load_calibration_from_project(self):
        """Load calibration from project, with fallback to session_config.
        
        Returns:
            CalibrationData object or None if no calibration found
        """
        from uroflow.spatial.calibration import CalibrationData, load_calibration
        
        if not self.project:
            return None
        
        # Try loading from project first (preferred)
        if self.project.spatial_calibration:
            try:
                return CalibrationData.from_dict(self.project.spatial_calibration)
            except (KeyError, TypeError, ValueError):
                pass
        
        # Fallback to session_config for backward compatibility
        config_path = self.project.session_config_path or ""
        return load_calibration(config_path) if config_path else None
    
    def _open_annotation_dialog(self, event_id: Optional[str] = None):
        """Open event location annotation dialog for an event."""
        from uroflow.spatial.gui.annotation_dialog import EventAnnotationDialog
        from uroflow.core.types import SpatialCoordinates
        from uroflow.core.video import find_matching_videos, get_video_files
        
        if not self.project:
            QMessageBox.warning(self, "No Project", "Please load a project first.")
            return
        
        # Use the explicitly requested row when available (e.g. context menu),
        # otherwise fall back to the current application selection.
        event_id = event_id or self.current_event_id
        if not event_id:
            QMessageBox.information(self, "No Selection", "Please select an event first.")
            return
        
        event = self.project.get_event_by_id(event_id)
        if event is None:
            return
        
        # Load calibration from project
        calibration = self._load_calibration_from_project()
        
        if calibration is None or not calibration.is_valid():
            QMessageBox.warning(
                self, "No Calibration",
                "No spatial calibration found.\n\n"
                "Please calibrate the camera first using the Calibrate Camera button."
            )
            return
        
        # Find matching video
        video_folder = self.project.video_folder_path
        if not video_folder:
            QMessageBox.warning(
                self, "No Video Folder",
                "No video folder configured.\nPlease set it via File -> Set Video Folder."
            )
            return
        
        video_files = get_video_files(video_folder)
        if not video_files or not event.wall_clock_time:
            QMessageBox.information(
                self, "No Video",
                "Cannot find matching video for this event."
            )
            return
        
        session_config = self.project.session_config_snapshot or {}
        matches = find_matching_videos(
            event, video_files,
            session_config.get('start_date', ''),
            session_config.get('start_time', ''),
            max_delay_after_event_s=60.0,
        )
        
        if not matches:
            QMessageBox.information(
                self, "No Video",
                f"No video found near event time: {event.wall_clock_time}"
            )
            return
        
        # Select video based on number of matches
        selected_video_path = None
        
        if len(matches) == 1:
            # Single match - use it directly
            selected_video_path = str(matches[0][0])
            
        elif len(matches) <= 3:
            # 2-3 matches - show popup menu to choose
            menu = QMenu(self)
            menu.setTitle("Select Video for Annotation")
            
            for video_path, video_dt, offset in matches:
                offset_str = f"+{offset:.0f}s" if offset >= 0 else f"{offset:.0f}s"
                action_text = f"{video_path.name} ({offset_str})"
                action = menu.addAction(action_text)
                action.setData(str(video_path))
            
            # Show menu at cursor position
            action = menu.exec_(self.cursor().pos())
            
            if action:
                selected_video_path = action.data()
            else:
                return  # User canceled
                
        else:
            # More than 3 matches - show dialog to confirm best match
            video_path, video_dt, offset = matches[0]
            reply = QMessageBox.question(
                self, "Multiple Videos Found",
                f"Found {len(matches)} potential videos for this event.\n\n"
                f"Use the closest match for annotation?\n{video_path.name}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                selected_video_path = str(video_path)
            else:
                return  # User declined
        
        if not selected_video_path:
            return
        
        dialog = EventAnnotationDialog(
            video_path=selected_video_path,
            calibration=calibration,
            event_label=event.label_user,
            parent=self,
        )
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.get_result()
            if result is not None:
                img_x, img_y, real_x, real_y = result
                event.spatial_coords = SpatialCoordinates(
                    image_x=img_x,
                    image_y=img_y,
                    real_x_cm=real_x,
                    real_y_cm=real_y,
                )
                event.update_modified()
                self.project.update_modified()
                self.status_label.setText(
                    f"Location marked for event {event_id[:8]}: "
                    f"({real_x:.1f}, {real_y:.1f}) cm"
                )
                self.event_widget.update_event(event_id)
    
    def _open_spatial_analysis(self):
        """Open spatial analysis panel/dialog."""
        from uroflow.spatial.gui.spatial_overlay import SpatialAnalysisDialog
        
        if not self.project:
            QMessageBox.warning(self, "No Project", "Please load a project first.")
            return
        
        calibration = self._load_calibration_from_project()
        
        events_with_coords = [
            e for e in self.project.events if e.spatial_coords is not None
        ]
        
        if not events_with_coords:
            QMessageBox.information(
                self, "No Spatial Data",
                "No events have spatial coordinates yet.\n\n"
                "Use Mark Event Location from the Events table to annotate events."
            )
            return
        
        dialog = SpatialAnalysisDialog(
            events=events_with_coords,
            calibration=calibration,
            parent=self,
        )
        dialog.exec()
    
    def _on_event_selected(self, event_id: str):
        """Handle event selection from table or plot.
        
        Args:
            event_id: Selected event ID
        """
        if not self.project:
            return
        
        # Prevent recursive calls
        if self._selecting_event:
            return
        
        # If already selected, skip
        if self.current_event_id == event_id:
            return
        
        try:
            self._selecting_event = True
            self.current_event_id = event_id
            event = self.project.get_event_by_id(event_id)
            
            if not event:
                print(f"Warning: Event {event_id[:8]} not found")
                return
            
            print(f"Selecting event {event_id[:8]}...")
            
            # Update detail plot
            try:
                self.detail_plot.show_event(event)
                print("  Detail plot updated")
            except Exception as e:
                print(f"  ERROR updating detail plot: {e}")
                import traceback
                traceback.print_exc()
            
            # Highlight in overview
            try:
                self.overview_plot.highlight_event(event_id)
                print("  Overview plot highlighted")
            except Exception as e:
                print(f"  ERROR highlighting overview: {e}")
                import traceback
                traceback.print_exc()
            
            # Sync table selection
            try:
                self.event_widget.select_event(event_id)
                print("  Table selection synced")
            except Exception as e:
                print(f"  WARNING: Could not sync table selection: {e}")
            
            # Sync gallery selection
            try:
                self.event_gallery.highlight_event(event_id)
            except Exception as e:
                print(f"  WARNING: Could not highlight gallery: {e}")
            
            # Update info panel
            try:
                self.info_widget.set_event(event)
                print("  Info panel updated")
            except Exception as e:
                print(f"  ERROR updating info panel: {e}")
            
            # Emit signal (temporarily disabled - may be causing crashes)
            # try:
            #     self.current_event_changed.emit(event_id)
            # except Exception as e:
            #     print(f"  ERROR emitting signal: {e}")
            #     import traceback
            #     traceback.print_exc()
            
            print("  Event selected successfully")
            
            # Return immediately to prevent any post-processing
            return
            
        except Exception as e:
            print(f"CRITICAL ERROR in _on_event_selected: {e}")
            import traceback
            traceback.print_exc()
            try:
                QMessageBox.critical(self, "Error Selecting Event", 
                    f"Error selecting event:\n\n{str(e)}\n\nSee terminal for details.")
            except:
                pass  # Don't crash if message box fails
        finally:
            # Always reset flag
            self._selecting_event = False
            # Don't process events here - let Qt handle it naturally
    
    def _on_center_plot_requested(self, event_id: str):
        """Center the overview plot on the requested event.
        
        Args:
            event_id: Event ID to center in the overview plot
        """
        if not self.project:
            return
        
        # Select the event (same as single click)
        self._on_event_selected(event_id)
        
        # Center the overview plot on this event
        event = self.project.get_event_by_id(event_id)
        if event:
            self.overview_plot.highlight_event(event_id, center_view=True)
    
    def _on_next_event(self):
        """Navigate to next event."""
        if not self.project or not self.current_event_id:
            return
        
        # Find current event index
        for i, event in enumerate(self.project.events):
            if event.event_id == self.current_event_id:
                # Get next event
                if i < len(self.project.events) - 1:
                    next_event = self.project.events[i + 1]
                    self._on_event_selected(next_event.event_id)
                break
    
    def _on_prev_event(self):
        """Navigate to previous event."""
        if not self.project or not self.current_event_id:
            return
        
        # Find current event index
        for i, event in enumerate(self.project.events):
            if event.event_id == self.current_event_id:
                # Get previous event
                if i > 0:
                    prev_event = self.project.events[i - 1]
                    self._on_event_selected(prev_event.event_id)
                break
    
    def _on_boundary_changed(self, event_id: str, new_start_time: float, new_end_time: float):
        """Handle boundary change from detail plot (debounced).
        
        Args:
            event_id: Event ID
            new_start_time: New start time in seconds
            new_end_time: New end time in seconds
        """
        # Store pending change and restart debounce timer
        # This prevents crashes from rapid signal firing during drag
        self._pending_boundary_change = (event_id, new_start_time, new_end_time)
        self._boundary_change_timer.start(100)  # 100ms debounce
    
    def _apply_boundary_change(self):
        """Apply the pending boundary change after debounce delay."""
        if self._pending_boundary_change is None:
            return
        
        event_id, new_start_time, new_end_time = self._pending_boundary_change
        self._pending_boundary_change = None
        
        print(f"Boundary changed for {event_id[:8]}: {new_start_time:.2f} -> {new_end_time:.2f}")
        
        try:
            if not self.project:
                return
            
            # Find and update event
            event = self.project.get_event_by_id(event_id)
            if not event:
                return
            
            # Update times AND indices (indices are needed for feature computation)
            event.start_time_s = new_start_time
            event.end_time_s = new_end_time
            event.start_idx = int(np.searchsorted(self.timestamp, new_start_time))
            event.end_idx = int(np.searchsorted(self.timestamp, new_end_time, side='right'))
            event.update_modified()
            
            baseline_window_s = self.project.detection_params.baseline_window_s
            compute_features_for_events(
                [event],
                self.timestamp,
                self.mass,
                self.segments,
                self.metadata,
                baseline_window_s=baseline_window_s,
            )
            
            # Update just this event in overview plot (faster, avoids crash)
            self.overview_plot.update_event_bounds(event_id, new_start_time, new_end_time)
            
            # Update just the changed row in table (safer than full refresh)
            self.event_widget.update_event(event_id)
            
            # Update info panel with new values
            self.info_widget.set_event(event)
            
            # Mark project as modified
            self.project.update_modified()
            
            # Notify gallery that thumbnails are stale
            self.event_gallery.update_events(self.project.events)
            
            # Update summary panel (mass may have changed)
            self.summary_widget.set_events(self.project.events)
            
            print(f"  Updated: duration={event.duration_s():.2f}s, delta_mass={event.features.delta_mass_g if event.features else 'N/A'}")
        except Exception as e:
            print(f"  ERROR in _apply_boundary_change: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_manual_event_requested(self, start_time: float, end_time: float):
        """Handle manual event creation request.
        
        Args:
            start_time: Event start time in seconds
            end_time: Event end time in seconds
        """
        print(f"Creating manual event: {start_time:.2f}s -> {end_time:.2f}s")
        
        if not self.project:
            return
        
        # Create new event
        import uuid
        from uroflow.core.types import Event
        from uroflow.core.features import compute_features_for_events
        
        # Compute indices from times
        start_idx = int(np.searchsorted(self.timestamp, start_time))
        end_idx = int(np.searchsorted(self.timestamp, end_time, side='right'))
        
        new_event = Event(
            event_id=str(uuid.uuid4()),
            start_idx=start_idx,
            end_idx=end_idx,
            start_time_s=start_time,
            end_time_s=end_time,
            source="manual",
            label_user="",
            locked=False,
            needs_manual=False,
            notes="Manually created event"
        )
        
        # Compute features (also populates wall_clock_time)
        compute_features_for_events(
            [new_event],
            self.timestamp,
            self.mass,
            self.segments,
            self.metadata,
            baseline_window_s=self.project.detection_params.baseline_window_s,
        )
        
        # Add to project
        self.project.events.append(new_event)
        self.project.update_modified()
        
        # Sort events by start time
        self.project.events.sort(key=lambda e: e.start_time_s)
        
        # Refresh all views
        self.event_widget.set_events(self.project.events, self.metadata)
        self.overview_plot.set_data(
            self.timestamp, self.mass,
            self.segments, self.gaps,
            self.project.events
        )
        self.event_gallery.set_data(self.timestamp, self.mass, self.project.events)
        self.summary_widget.set_events(self.project.events)
        
        # Select the new event
        self._on_event_selected(new_event.event_id)
        
        print(f"  Created event {new_event.event_id[:8]}, duration={new_event.duration_s():.2f}s")
        self.status_label.setText(f"Created event: {new_event.duration_s():.2f}s duration")
    
    def _show_detect_events_dialog(self):
        """Show dialog to configure and run event detection."""
        if not self.project or self.timestamp is None:
            QMessageBox.warning(self, "No Project", "Please load a project first.")
            return
        
        # Show configuration dialog
        dialog = DetectEventsDialog(
            current_params=self.project.detection_params,
            parent=self
        )
        
        if dialog.exec() == QDialog.Accepted:
            # Get parameters from dialog
            params = dialog.get_detection_params()
            clear_existing = dialog.should_clear_existing()
            use_acquisition = dialog.should_use_acquisition()
            auto_classify = dialog.should_auto_classify()
            classify_only = dialog.should_classify_only()
            classification_params = dialog.get_classification_params() if auto_classify else None
            
            # Run detection or classification
            if classify_only:
                # Only classify existing events, do not detect new ones
                self._run_classification_only(classification_params)
            else:
                # Full detection workflow
                self._run_event_detection(params, clear_existing, use_acquisition, auto_classify, classification_params)
    
    def _run_event_detection(self, params: DetectionParams, 
                             clear_existing: bool, use_acquisition: bool,
                             auto_classify: bool = True,
                             classification_params: dict = None):
        """Execute event detection with the given parameters.
        
        Args:
            params: Detection parameters
            clear_existing: Whether to clear existing auto events
            use_acquisition: Whether to also detect from acquisition flags
            auto_classify: Whether to auto-classify events as urine/feces
            classification_params: Dictionary with classification parameters
                                  (urine_min_mass_g, feces_min_mass_g, slope_ratio_threshold)
        """
        from uroflow.core.detect import detect_events_in_segments, detect_from_acquisition_flags
        from uroflow.core.features import compute_features_for_events, auto_classify_events
        from uroflow.core.overlap import resolve_overlaps, remove_duplicates
        from uroflow.io.load_csv import find_acquisition_event_windows
        
        try:
            # Show progress dialog
            progress = QProgressDialog("Detecting events...", None, 0, 5, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setCancelButton(None)
            progress.setValue(0)
            progress.show()
            QApplication.processEvents()
            
            # Store old params for undo
            old_params = self.project.detection_params
            
            # Segments are computed once at load time with default dt_factor
            progress.setLabelText("Computing segments...")
            QApplication.processEvents()
            # Segments already computed at load time, no need to recompute
            progress.setValue(1)
            QApplication.processEvents()
            
            # Identify events to remove (if clearing existing detected/acquisition events).
            # Locked and manual events are preserved.
            removed_event_ids = []
            if clear_existing:
                removed_event_ids = [
                    e.event_id for e in self.project.events 
                    if e.source in ("auto", "acquisition") and not e.locked
                ]
            
            # Preserve locked and manual events from existing project
            preserved_events = [
                e for e in self.project.events
                if e.locked or e.source == "manual" or e.event_id not in removed_event_ids
            ]
            print(f"Preserving {len(preserved_events)} events ({sum(1 for e in preserved_events if e.locked)} locked, "
                  f"{sum(1 for e in preserved_events if e.source == 'manual')} manual)")
            
            # Detect events
            progress.setLabelText("Running auto-detection...")
            QApplication.processEvents()
            new_events = []
            
            print(f"\n{'='*60}")
            print(f"DETECTION STARTED")
            print(f"Data: {len(self.timestamp)} samples, {len(self.segments)} segments")
            print(f"Mass range: {np.nanmin(self.mass):.2f}g to {np.nanmax(self.mass):.2f}g")
            print(f"{'='*60}")
            
            # Auto-detection
            auto_events = detect_events_in_segments(
                self.timestamp, self.mass, self.segments, params
            )
            print(f"Auto-detection found: {len(auto_events)} events")
            new_events.extend(auto_events)
            progress.setValue(2)
            QApplication.processEvents()
            
            # From acquisition flags (if requested)
            if use_acquisition:
                progress.setLabelText("Processing acquisition flags...")
                QApplication.processEvents()
                # Reload acquisition events from CSV
                try:
                    _, _, acquisition_events, _ = load_uroflow_csv(self.project.input_csv_path)
                    print(f"Acquisition flags: {np.sum(acquisition_events)} flagged samples")
                    if acquisition_events.any():
                        acq_windows = find_acquisition_event_windows(self.timestamp, acquisition_events)
                        print(f"Acquisition windows found: {len(acq_windows)}")
                        acq_events = detect_from_acquisition_flags(
                            self.timestamp, self.mass, acq_windows, self.segments
                        )
                        print(f"Acquisition events created: {len(acq_events)}")
                        acq_min_separation_s = max(
                            1.5,
                            params.expand_event_s + params.baseline_window_s
                        )
                        acq_events, skipped_acq_events = _filter_supplemental_acquisition_events(
                            acq_events,
                            reference_events=preserved_events + auto_events,
                            min_separation_s=acq_min_separation_s,
                        )
                        if skipped_acq_events:
                            print(
                                f"Skipped {skipped_acq_events} acquisition flag event(s) "
                                f"near refined events (within {acq_min_separation_s:.2f}s)"
                            )
                        print(f"Supplemental acquisition events kept: {len(acq_events)}")
                        new_events.extend(acq_events)
                except Exception as e:
                    print(f"Warning: Could not process acquisition flags: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Filter out new events that overlap with locked events
            # (to prevent duplicates when detection recreates the same event)
            locked_events = [e for e in preserved_events if e.locked]
            if locked_events:
                filtered_new_events = []
                for new_event in new_events:
                    overlaps_locked = False
                    for locked_event in locked_events:
                        # Check if new event significantly overlaps with locked event
                        # (overlap threshold: at least 50% of shorter event's duration)
                        if new_event.overlaps_with(locked_event):
                            # Calculate overlap fraction
                            overlap_start = max(new_event.start_idx, locked_event.start_idx)
                            overlap_end = min(new_event.end_idx, locked_event.end_idx)
                            overlap_duration = overlap_end - overlap_start
                            
                            new_duration = new_event.end_idx - new_event.start_idx
                            locked_duration = locked_event.end_idx - locked_event.start_idx
                            min_duration = min(new_duration, locked_duration)
                            
                            if min_duration > 0 and overlap_duration / min_duration >= 0.5:
                                overlaps_locked = True
                                print(f"  Filtering new event (overlaps with locked event {locked_event.event_id[:8]})")
                                break
                    
                    if not overlaps_locked:
                        filtered_new_events.append(new_event)
                
                n_filtered = len(new_events) - len(filtered_new_events)
                if n_filtered > 0:
                    print(f"Filtered out {n_filtered} new events that overlap with locked events")
                new_events = filtered_new_events
            
            # Merge preserved events (locked/manual) with new events
            all_events = preserved_events + new_events
            print(f"Total events before dedup: {len(all_events)} ({len(preserved_events)} preserved, {len(new_events)} new)")
            progress.setValue(3)
            QApplication.processEvents()
            
            # Resolve overlaps and compute features
            progress.setLabelText("Resolving overlaps...")
            QApplication.processEvents()
            all_events = remove_duplicates(all_events)
            print(f"After dedup: {len(all_events)} events")
            all_events = resolve_overlaps(all_events)
            print(f"After overlap resolution: {len(all_events)} events")
            all_events = compute_features_for_events(
                all_events,
                self.timestamp,
                self.mass,
                self.segments,
                self.metadata,
                baseline_window_s=self.project.detection_params.baseline_window_s,
            )
            print(f"Features computed for {len(all_events)} events")
            
            # Use all_events as new_events for the rest of the function
            new_events = all_events
            
            # Auto-classify events if requested
            if auto_classify:
                progress.setLabelText("Classifying events...")
                QApplication.processEvents()
                
                # Use provided classification params or defaults
                if classification_params is None:
                    classification_params = {
                        'urine_min_mass_g': 0.1,
                        'feces_min_mass_g': 0.05,
                        'slope_ratio_threshold': 2.5
                    }
                
                new_events = auto_classify_events(
                    new_events,
                    urine_min_mass_g=classification_params['urine_min_mass_g'],
                    feces_min_mass_g=classification_params['feces_min_mass_g'],
                    slope_ratio_threshold=classification_params['slope_ratio_threshold']
                )
            
            # Count by source
            n_auto = sum(1 for e in new_events if e.source == "auto")
            n_acq = sum(1 for e in new_events if e.source == "acquisition")
            n_labeled = sum(1 for e in new_events if e.label_user)
            print(f"Final events: {n_auto} auto, {n_acq} acquisition, {n_labeled} labeled")
            print(f"{'='*60}\n")
            
            progress.setValue(4)
            QApplication.processEvents()
            
            # Create and execute command (for undo support)
            command = DetectEventsCommand(
                project=self.project,
                new_events=new_events,
                removed_event_ids=removed_event_ids,
                old_params=old_params,
                new_params=params
            )
            self.undo_stack.push(command)
            
            # Update UI
            progress.setLabelText("Updating UI...")
            QApplication.processEvents()
            self._refresh_all_views()
            self._update_undo_redo_actions()
            self._update_counts()
            progress.setValue(5)
            
            # Close progress and show result
            progress.close()
            
            n_new = len(new_events)
            n_removed = len(removed_event_ids)
            
            if clear_existing:
                self.status_label.setText(
                    f"Detection complete: {n_new} events detected, {n_removed} old auto events removed"
                )
            else:
                self.status_label.setText(f"Detection complete: {n_new} events detected")
            
            print(f"Detection complete: {n_new} new events, {n_removed} removed")
            
        except Exception as e:
            import traceback
            error_msg = f"Error during detection:\n\n{str(e)}\n\n{traceback.format_exc()}"
            print(error_msg)
            QMessageBox.critical(self, "Detection Error", error_msg)
    
    def _run_classification_only(self, classification_params: dict = None):
        """Classify existing events without creating or removing any.
        
        Args:
            classification_params: Dictionary with classification parameters
        """
        from uroflow.core.features import auto_classify_events
        
        try:
            if not self.project or not self.project.events:
                QMessageBox.warning(self, "No Events", "No events to classify.")
                return
            
            # Show progress dialog
            progress = QProgressDialog("Classifying events...", None, 0, 2, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setCancelButton(None)
            progress.setValue(0)
            progress.show()
            QApplication.processEvents()
            
            # Use provided classification params or defaults
            if classification_params is None:
                classification_params = {
                    'urine_min_mass_g': 0.1,
                    'feces_min_mass_g': 0.05,
                    'slope_ratio_threshold': 2.5
                }
            
            print(f"\n{'='*60}")
            print(f"CLASSIFICATION ONLY MODE")
            print(f"Classifying {len(self.project.events)} existing events")
            print(f"{'='*60}")
            
            # Classify existing events (modifies events in-place)
            auto_classify_events(
                self.project.events,
                urine_min_mass_g=classification_params['urine_min_mass_g'],
                feces_min_mass_g=classification_params['feces_min_mass_g'],
                slope_ratio_threshold=classification_params['slope_ratio_threshold']
            )
            
            # Count classifications
            n_urine = sum(1 for e in self.project.events if e.label_user == "urine")
            n_feces = sum(1 for e in self.project.events if e.label_user == "feces")
            n_unlabeled = sum(1 for e in self.project.events if not e.label_user or e.label_user == "unlabeled")
            
            print(f"Classification results:")
            print(f"  Urine: {n_urine}")
            print(f"  Feces: {n_feces}")
            print(f"  Unlabeled: {n_unlabeled}")
            print(f"{'='*60}\n")
            
            progress.setValue(1)
            QApplication.processEvents()
            
            # Mark project as modified
            self.project.update_modified()
            
            # Update UI
            progress.setLabelText("Updating UI...")
            QApplication.processEvents()
            self._refresh_all_views()
            self._update_counts()
            progress.setValue(2)
            
            # Close progress and show result
            progress.close()
            
            self.status_label.setText(
                f"Classification complete: {n_urine} urine, {n_feces} feces, {n_unlabeled} unlabeled"
            )
            
            print(f"Classification complete")
            
        except Exception as e:
            import traceback
            error_msg = f"Error during classification:\n\n{str(e)}\n\n{traceback.format_exc()}"
            print(error_msg)
            QMessageBox.critical(self, "Classification Error", error_msg)
    
    def _refresh_all_views(self):
        """Refresh all UI views after event changes."""
        if not self.project:
            return
        
        print(f"_refresh_all_views: Refreshing with {len(self.project.events)} events")
        
        # Update plots
        self.overview_plot.set_data(
            self.timestamp, self.mass,
            self.segments, self.gaps,
            self.project.events
        )
        
        # Force UI update to ensure plot redraws
        QApplication.processEvents()
        
        # Update event table
        self.event_widget.set_events(self.project.events, self.metadata)
        self.event_widget.set_session_config(self.project.session_config_snapshot)
        
        # Update gallery
        try:
            self.event_gallery.set_export_base_name(self.project.input_csv_path)
            self.event_gallery.set_data(self.timestamp, self.mass, self.project.events)
        except Exception as e:
            print(f"Warning: Could not update gallery: {e}")
        
        # Update summary
        try:
            self.summary_widget.set_events(self.project.events)
        except Exception as e:
            print(f"Warning: Could not update summary: {e}")
        
        # Force another UI update
        QApplication.processEvents()
        
        # Select first event if available and none selected
        if self.project.events and not self.current_event_id:
            self.current_event_id = self.project.events[0].event_id
            self._on_event_selected(self.current_event_id)
        elif self.current_event_id:
            # Re-select current event if it still exists
            event = self.project.get_event_by_id(self.current_event_id)
            if event:
                self._on_event_selected(self.current_event_id)
            elif self.project.events:
                # Current event was deleted, select first
                self.current_event_id = self.project.events[0].event_id
                self._on_event_selected(self.current_event_id)
        
        print("_refresh_all_views: Complete")
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts.
        
        Args:
            event: Key event
        """
        if not self.project or not self.current_event_id:
            super().keyPressEvent(event)
            return
        
        key = event.key()
        modifiers = event.modifiers()
        
        # Navigation
        if key == Qt.Key_Right and not modifiers:
            self._on_next_event()
        elif key == Qt.Key_Left and not modifiers:
            self._on_prev_event()
        
        # Labeling (U/F/B)
        elif key == Qt.Key_U:
            self._label_current_event("urine")
        elif key == Qt.Key_F:
            self._label_current_event("feces")
        elif key == Qt.Key_B:
            self._label_current_event("bad")
        
        # Deletion
        elif key == Qt.Key_Delete or key == Qt.Key_Backspace:
            self._delete_current_event()
        
        else:
            super().keyPressEvent(event)
    
    def _label_current_event(self, label: str):
        """Label the currently selected event.
        
        Args:
            label: Label to set ("urine", "feces", "bad")
        """
        if not self.project or not self.current_event_id:
            return
        
        command = LabelEventCommand(self.project, self.current_event_id, label)
        self.undo_stack.push(command)

        current_event = self.project.get_event_by_id(self.current_event_id)
        if current_event:
            self.detail_plot.refresh_event_type(current_event)
        
        # Update UI
        self.event_widget.update_event(self.current_event_id)
        self.overview_plot.set_data(self.timestamp, self.mass, self.segments, self.gaps, self.project.events)
        self._update_undo_redo_actions()
        
        # Notify gallery that thumbnails are stale
        self.event_gallery.update_events(self.project.events)
        
        # Update summary panel
        self.summary_widget.set_events(self.project.events)
        
        # Update counts
        self._update_counts()
        
        self.status_label.setText(f"Labeled event as {label}")

    def _on_table_event_label_changed(self, event_id: str):
        """Refresh dependent views immediately after an inline table label edit."""
        if not self.project:
            return

        event = self.project.get_event_by_id(event_id)
        if not event:
            return

        self.project.update_modified()
        self.overview_plot.set_data(
            self.timestamp, self.mass, self.segments, self.gaps, self.project.events
        )
        self.event_gallery.update_events(self.project.events)
        self.summary_widget.set_events(self.project.events)
        self._update_counts()

        if self.current_event_id == event_id:
            self.detail_plot.refresh_event_type(event)
            self.info_widget.set_event(event)

        self.status_label.setText(f"Labeled event as {event.label_user or 'unlabeled'}")
    
    def _delete_current_event(self):
        """Delete the currently selected event."""
        self._delete_event(self.current_event_id)

    def _delete_event(self, event_id: str):
        """Delete a specific event requested by an event-table action."""
        if not self.project or not event_id:
            return
        
        # Confirm deletion
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Delete Event",
            "Delete this event? (Can be undone with Ctrl+Z)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        command = DeleteEventCommand(self.project, event_id)
        self.undo_stack.push(command)
        
        # Update UI
        self.event_widget.remove_event(event_id)
        self.overview_plot.set_data(self.timestamp, self.mass, self.segments, self.gaps, self.project.events)
        self.detail_plot.clear()
        self._update_undo_redo_actions()
        
        # Notify gallery that thumbnails are stale
        self.event_gallery.update_events(self.project.events)
        
        # Update summary panel
        self.summary_widget.set_events(self.project.events)
        
        # Select next event
        if self.project.events:
            self._on_event_selected(self.project.events[0].event_id)
        else:
            self.current_event_id = None
        
        # Update counts
        self._update_counts()
        
        self.status_label.setText("Event deleted")
    
    def _do_undo(self):
        """Execute undo command."""
        command = self.undo_stack.undo()
        if command:
            # Refresh UI
            self.event_widget.set_events(self.project.events, self.metadata)
            self.overview_plot.set_data(self.timestamp, self.mass, self.segments, self.gaps, self.project.events)
            current_event = self.project.get_event_by_id(self.current_event_id)
            if current_event:
                self.detail_plot.refresh_event_type(current_event)
            self.summary_widget.set_events(self.project.events)
            self._update_undo_redo_actions()
            self._update_counts()
            self.status_label.setText(f"Undone: {command.description()}")
    
    def _do_redo(self):
        """Execute redo command."""
        command = self.undo_stack.redo()
        if command:
            # Refresh UI
            self.event_widget.set_events(self.project.events, self.metadata)
            self.overview_plot.set_data(self.timestamp, self.mass, self.segments, self.gaps, self.project.events)
            current_event = self.project.get_event_by_id(self.current_event_id)
            if current_event:
                self.detail_plot.refresh_event_type(current_event)
            self.summary_widget.set_events(self.project.events)
            self._update_undo_redo_actions()
            self._update_counts()
            self.status_label.setText(f"Redone: {command.description()}")
    
    def _update_undo_redo_actions(self):
        """Update undo/redo action states."""
        self.undo_action.setEnabled(self.undo_stack.can_undo())
        self.redo_action.setEnabled(self.undo_stack.can_redo())
        
        if self.undo_stack.can_undo():
            self.undo_action.setText(f"Undo: {self.undo_stack.get_undo_text()}")
        else:
            self.undo_action.setText("Undo")
        
        if self.undo_stack.can_redo():
            self.redo_action.setText(f"Redo: {self.undo_stack.get_redo_text()}")
        else:
            self.redo_action.setText("Redo")
    
    def _update_counts(self):
        """Update event count labels."""
        if self.project:
            n_events = len(self.project.events)
            n_unlabeled = len(self.project.get_unlabeled_events())
            
            self.events_count_label.setText(f"{n_events} events")
            self.unlabeled_count_label.setText(f"{n_unlabeled} unlabeled")
    
    def closeEvent(self, event):
        """Handle window close event."""
        if self.project and self.project_path:
            # Autosave on exit
            try:
                save_project(self.project, self.project_path)
            except:
                pass
        
        event.accept()
