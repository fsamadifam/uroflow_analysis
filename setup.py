"""Setup script for uroflow package (backup to pyproject.toml)."""

from setuptools import setup, find_packages

setup(
    name="uroflow",
    version="0.1.0",
    description="GUI tool for analyzing 24-hour uroflowmetry data",
    author="Farshad",
    python_requires=">=3.10",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "PySide6>=6.6.0",
        "pyqtgraph>=0.13.0",
        "numpy>=1.24.0",
        "pandas>=2.0.0",
        "opencv-python>=4.8.0",
        "matplotlib>=3.7.0",
    ],
    entry_points={
        "console_scripts": [
            "uroflow-detect=uroflow.cli.detect_events:main",
            "uroflow-gui=uroflow.gui.app:main",
        ],
    },
)
