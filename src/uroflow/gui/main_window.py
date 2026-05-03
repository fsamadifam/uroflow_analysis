"""Main window for uroflow analysis GUI."""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QLabel, QFileDialog, QMessageBox, QStatusBar,
    QMenuBar, QPushButton, QProgressDialog, QApplication,
    QDialog, QFormLayout, QDoubleSpinBox, QDialogButtonBox
)
from PySide6.QtCore import Qt, Signal, QTimer, QObject
from PySide6.QtGui import QAction, QKeySequence
from pathlib import Path
import time
import numpy as np

from uroflow.core.types import Project, DetectionParams
from uroflow.core.project_io import load_project, save_project, autosave_project
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
from uroflow.gui.actions import UndoStack, LabelEventCommand, DeleteEventCommand, DetectEventsCommand
from uroflow.gui.detect_events_dialog import DetectEventsDialog


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
        self.event_widget.next_event_requested.connect(self._on_next_event)
        self.event_widget.prev_event_requested.connect(self._on_prev_event)
        right_panel.addTab(self.event_widget, "Events")
        
        # Event gallery tab
        self.event_gallery = EventGallery()
        self.event_gallery.event_selected.connect(self._on_event_selected)
        right_panel.addTab(self.event_gallery, "Gallery")
        
        # Info tab
        self.info_widget = InfoPanel()
        right_panel.addTab(self.info_widget, "Info")
        
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
        
        edit_menu.addSeparator()
        
        detect_action = QAction("&Detect Events...", self)
        detect_action.setShortcut(QKeySequence("Ctrl+D"))
        detect_action.triggered.connect(self._show_detect_events_dialog)
        edit_menu.addAction(detect_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
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
            # Show progress dialog
            progress = QProgressDialog("Loading project...", None, 0, 4, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setValue(0)
            
            # Load project
            self.project = load_project(project_path)
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
            
            # Update UI
            progress.setLabelText("Updating UI...")
            self.last_save_time = time.time()
            self._update_ui_after_load()
            progress.setValue(4)
            
            self.status_label.setText(f"Loaded: {Path(project_path).name}")
            self.project_loaded.emit()
            
        except Exception as e:
            QMessageBox.critical(self, "Error Loading Project", str(e))
    
    def create_new_project(self, csv_path: str, config_path: str):
        """Create new project from CSV and config."""
        print(f"\n{'='*60}")
        print(f"create_new_project called")
        print(f"  CSV: {csv_path}")
        print(f"  Config: {config_path}")
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
                events = compute_features_for_events(events, timestamp, mass, segments)
                print(f"Computed features for {len(events)} events")
            
            progress.setValue(5)
            QApplication.processEvents()
            
            # Create project
            self.project = Project(
                input_csv_path=str(Path(csv_path).absolute()),
                session_config_path=str(Path(config_path).absolute()),
                session_config_snapshot=config,
                detection_params=detection_params,
                events=events
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
            
            # Update event gallery
            print("  Updating event gallery...")
            try:
                self.event_gallery.set_data(self.timestamp, self.mass, self.project.events)
            except Exception as e:
                print(f"  ERROR updating gallery: {e}")
                import traceback
                traceback.print_exc()
            
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
                self.create_new_project(csv_path, config_path)
    
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
        
        project_path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", "project.json", "Project Files (*.json)"
        )
        
        if project_path:
            self.project_path = project_path
            self.save_project_action()
    
    def export_events_dialog(self):
        """Show export events dialog."""
        if not self.project:
            return
        
        from uroflow.core.project_io import export_events_csv
        
        csv_path, _ = QFileDialog.getSaveFileName(
            self, "Export Events", "events_labeled.csv", "CSV Files (*.csv)"
        )
        
        if csv_path:
            try:
                export_events_csv(self.project.events, csv_path)
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
            
            # Sync gallery selection (temporarily disabled to isolate crash)
            print("  Gallery highlight (temporarily disabled)")
            
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
            event.end_idx = int(np.searchsorted(self.timestamp, new_end_time))
            event.update_modified()
            
            # Recompute features for this event (now uses updated indices)
            from uroflow.core.features import compute_features_for_events
            compute_features_for_events([event], self.timestamp, self.mass, self.segments)
            
            # Update just this event in overview plot (faster, avoids crash)
            self.overview_plot.update_event_bounds(event_id, new_start_time, new_end_time)
            
            # Update just the changed row in table (safer than full refresh)
            self.event_widget.update_event(event_id)
            
            # Update info panel with new values
            self.info_widget.set_event(event)
            
            # Mark project as modified
            self.project.update_modified()
            
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
        end_idx = int(np.searchsorted(self.timestamp, end_time))
        
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
        
        # Compute features
        compute_features_for_events([new_event], self.timestamp, self.mass, self.segments)
        
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
            
            # Identify events to remove (if clearing existing detected events)
            # Clear both auto and acquisition events when re-detecting
            # BUT preserve locked events and manual events
            removed_event_ids = []
            if clear_existing:
                # Clear auto events (but preserve locked ones)
                removed_event_ids = [
                    e.event_id for e in self.project.events 
                    if e.source == "auto" and not e.locked
                ]
                # Also clear acquisition events if we're re-detecting from acquisition
                # (but preserve locked ones)
                if use_acquisition:
                    removed_event_ids.extend([
                        e.event_id for e in self.project.events 
                        if e.source == "acquisition" and not e.locked
                    ])
            
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
                all_events, self.timestamp, self.mass, self.segments
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
        
        # Update gallery
        try:
            self.event_gallery.set_data(self.timestamp, self.mass, self.project.events)
        except Exception as e:
            print(f"Warning: Could not update gallery: {e}")
        
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
        
        # Update UI
        self.event_widget.update_event(self.current_event_id)
        self.overview_plot.set_data(self.timestamp, self.mass, self.segments, self.gaps, self.project.events)
        self._update_undo_redo_actions()
        
        # Update counts
        self._update_counts()
        
        self.status_label.setText(f"Labeled event as {label}")
    
    def _delete_current_event(self):
        """Delete the currently selected event."""
        if not self.project or not self.current_event_id:
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
        
        command = DeleteEventCommand(self.project, self.current_event_id)
        self.undo_stack.push(command)
        
        # Update UI
        self.event_widget.remove_event(self.current_event_id)
        self.overview_plot.set_data(self.timestamp, self.mass, self.segments, self.gaps, self.project.events)
        self.detail_plot.clear()
        self._update_undo_redo_actions()
        
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
