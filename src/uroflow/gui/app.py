"""GUI application entry point."""

import sys
import argparse
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt

from uroflow.gui.main_window import MainWindow

# Set up exception hook to catch unhandled exceptions
def exception_hook(exctype, value, tb):
    """Catch unhandled exceptions and display them."""
    import traceback
    error_msg = ''.join(traceback.format_exception(exctype, value, tb))
    print(f"\n{'='*60}")
    print("UNHANDLED EXCEPTION:")
    print(error_msg)
    print(f"{'='*60}\n")
    try:
        QMessageBox.critical(None, "Unhandled Exception", error_msg)
    except:
        pass
    sys.__excepthook__(exctype, value, tb)

sys.excepthook = exception_hook

from PySide6.QtGui import QPalette, QColor

def apply_dark_theme(app):
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.Base, QColor(45, 45, 45))
    palette.setColor(QPalette.AlternateBase, QColor(55, 55, 55))
    palette.setColor(QPalette.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.Highlight, QColor(85, 85, 70))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))

    app.setPalette(palette)

def main():
    """Main GUI entry point."""
    parser = argparse.ArgumentParser(
        description='Uroflow Analysis GUI',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        'project',
        nargs='?',
        help='Project JSON file to load'
    )
    parser.add_argument(
        '--csv',
        help='Create new project from CSV file'
    )
    parser.add_argument(
        '--config',
        help='Session config JSON (required with --csv)'
    )
    
    args = parser.parse_args()
    
    # Create Qt application
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    app.setApplicationName("Uroflow Analysis")
    app.setOrganizationName("Uroflow")
    
    # Enable high DPI scaling (deprecated in newer Qt, but harmless)
    # app.setAttribute(Qt.AA_UseHighDpiPixmaps)  # Removed - deprecated
    
    # Create main window
    try:
        window = MainWindow()
    except Exception as e:
        import traceback
        print(f"Error creating MainWindow: {e}")
        traceback.print_exc()
        QMessageBox.critical(None, "Error", f"Failed to create main window:\n{e}")
        return 1
    
    # Load project or CSV if specified
    if args.project:
        project_path = Path(args.project)
        if project_path.exists():
            window.load_project(str(project_path))
        else:
            print(f"Warning: Project file not found: {project_path}")
    
    elif args.csv:
        if not args.config:
            print("Error: --config required when using --csv")
            return 1
        
        csv_path = Path(args.csv)
        config_path = Path(args.config)
        
        if not csv_path.exists():
            print(f"Error: CSV file not found: {csv_path}")
            return 1
        
        if not config_path.exists():
            print(f"Error: Config file not found: {config_path}")
            return 1
        
        window.create_new_project(str(csv_path), str(config_path))
    
    # Show window and run event loop
    try:
        print("Showing window...")
        window.show()
        window.raise_()  # Bring window to front
        window.activateWindow()  # Activate window
        
        # Force window to stay on top initially
        window.setWindowFlags(window.windowFlags() | Qt.WindowStaysOnTopHint)
        window.show()
        window.setWindowFlags(window.windowFlags() & ~Qt.WindowStaysOnTopHint)
        window.show()
        
        print("Window shown. Starting event loop...")
        print("NOTE: Window will stay open until you close it manually.")
        result = app.exec()
        print(f"Event loop exited with code: {result}")
        return result
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 0
    except Exception as e:
        import traceback
        error_msg = f"Error running GUI:\n\n{str(e)}\n\n{traceback.format_exc()}"
        print(error_msg)
        try:
            QMessageBox.critical(None, "Error", error_msg)
        except:
            pass
        return 1


if __name__ == '__main__':
    sys.exit(main())
