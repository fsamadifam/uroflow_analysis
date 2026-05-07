"""Video file matching and management for uroflow analysis."""

import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from uroflow.core.types import Event


def parse_video_filename(filename: str) -> Optional[datetime]:
    """Parse video filename to extract datetime.
    
    Expected format: "Replay YYYY-MM-DD HH-MM-SS.ext"
    
    Args:
        filename: Video filename (with or without path)
        
    Returns:
        datetime object or None if parsing fails
    """
    # Extract just the filename without path
    name = Path(filename).stem
    
    # Pattern: Replay YYYY-MM-DD HH-MM-SS
    pattern = r'Replay\s+(\d{4})-(\d{2})-(\d{2})\s+(\d{2})-(\d{2})-(\d{2})'
    match = re.match(pattern, name)
    
    if match:
        year, month, day, hour, minute, second = map(int, match.groups())
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None
    
    return None


def get_video_files(folder_path: str) -> List[Tuple[Path, datetime]]:
    """Get all video files in folder with their parsed datetimes.
    
    Args:
        folder_path: Path to video folder
        
    Returns:
        List of (filepath, datetime) tuples, sorted by datetime
    """
    folder = Path(folder_path)
    if not folder.exists():
        return []
    
    video_extensions = {'.mkv', '.mp4', '.avi', '.mov', '.webm'}
    videos = []
    
    for f in folder.iterdir():
        if f.is_file() and f.suffix.lower() in video_extensions:
            dt = parse_video_filename(f.name)
            if dt:
                videos.append((f, dt))
    
    # Sort by datetime
    videos.sort(key=lambda x: x[1])
    return videos


def parse_event_wall_clock(
    wall_clock_str: str, 
    session_start_date: str,
    session_start_time: str
) -> Optional[datetime]:
    """Parse event wall clock time to full datetime.
    
    Handles midnight rollover by checking if event time is earlier than
    session start time.
    
    Args:
        wall_clock_str: Wall clock time string from CSV (e.g., "12:10:50.123")
        session_start_date: Session start date (e.g., "2025-11-19")
        session_start_time: Session start time (e.g., "10:52:09")
        
    Returns:
        datetime object or None if parsing fails
    """
    if not wall_clock_str or wall_clock_str == "-":
        return None
    
    try:
        # Parse session start
        start_date = datetime.strptime(session_start_date, "%Y-%m-%d").date()
        start_time = datetime.strptime(session_start_time, "%H:%M:%S").time()
        
        # Parse event time (handle microseconds)
        # Remove microseconds if present for simpler comparison
        event_time_str = wall_clock_str.split('.')[0]
        event_time = datetime.strptime(event_time_str, "%H:%M:%S").time()
        
        # Combine with date
        event_datetime = datetime.combine(start_date, event_time)
        
        # Handle midnight rollover: if event time is earlier than session start,
        # the event occurred after midnight on the next day
        if event_time < start_time:
            event_datetime += timedelta(days=1)
        
        return event_datetime
        
    except (ValueError, AttributeError):
        return None


def find_matching_videos(
    event: Event,
    video_files: List[Tuple[Path, datetime]],
    session_start_date: str,
    session_start_time: str,
    max_delay_after_event_s: float = 30.0,
    max_time_before_event_s: float = 5.0
) -> List[Tuple[Path, datetime, float]]:
    """Find videos that could contain an event.
    
    Video naming convention: Videos are saved AFTER the event occurs, so the
    video filename timestamp is typically a few seconds after the event time.
    
    Example: Event at 07:16:02 -> Video saved as "Replay 2025-11-20 07-16-14"
    
    Matching logic:
    - Parse event wall-clock time to full datetime
    - Find videos whose save time is shortly AFTER the event time
    - A video is considered a match if:
      - Video was saved within max_delay_after_event_s after the event
      - OR video was saved slightly before (max_time_before_event_s) - edge case
    
    Args:
        event: Event to match
        video_files: List of (filepath, datetime) tuples from get_video_files()
        session_start_date: Session start date from config
        session_start_time: Session start time from config
        max_delay_after_event_s: Max seconds after event that video can be saved
        max_time_before_event_s: Max seconds before event (edge case)
        
    Returns:
        List of (filepath, video_datetime, time_offset_s) tuples
        time_offset_s is (video_save_time - event_time), positive means video saved after event
        Sorted by relevance (nearest video after event first)
    """
    if not video_files or not event.wall_clock_time:
        return []
    
    # Parse event time
    event_dt = parse_event_wall_clock(
        event.wall_clock_time,
        session_start_date,
        session_start_time
    )
    
    if not event_dt:
        return []
    
    matches = []
    
    for video_path, video_dt in video_files:
        # Time offset: how many seconds after event was video saved
        # Positive = video saved after event (expected case)
        # Negative = video saved before event (edge case)
        offset = (video_dt - event_dt).total_seconds()
        
        # Match if:
        # - Video saved after event (offset > 0) within max_delay_after_event_s
        # - OR video saved slightly before event (offset < 0) within max_time_before_event_s
        if -max_time_before_event_s <= offset <= max_delay_after_event_s:
            matches.append((video_path, video_dt, offset))
    
    # Sort by relevance:
    # 1. Prefer videos saved shortly after the event (small positive offset)
    # 2. Videos saved before event are less likely matches
    matches.sort(key=lambda x: (0 if x[2] >= 0 else 1, abs(x[2])))
    
    return matches


def open_video_file(video_path: str) -> Tuple[bool, str]:
    """Open a video file with the system's default player or VLC.
    
    Args:
        video_path: Path to video file
        
    Returns:
        Tuple of (success, message)
    """
    video_path = Path(video_path)
    
    if not video_path.exists():
        return False, f"Video file not found: {video_path}"
    
    try:
        if sys.platform == 'win32':
            # Try VLC first on Windows
            vlc_paths = [
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
            ]
            
            vlc_path = None
            for p in vlc_paths:
                if Path(p).exists():
                    vlc_path = p
                    break
            
            if vlc_path:
                subprocess.Popen([vlc_path, str(video_path)])
                return True, f"Opened with VLC: {video_path.name}"
            else:
                # Fall back to default program
                os.startfile(str(video_path))
                return True, f"Opened: {video_path.name}"
        
        elif sys.platform == 'darwin':
            # macOS
            subprocess.Popen(['open', str(video_path)])
            return True, f"Opened: {video_path.name}"
        
        else:
            # Linux
            # Try VLC first, then xdg-open
            try:
                subprocess.Popen(['vlc', str(video_path)])
                return True, f"Opened with VLC: {video_path.name}"
            except FileNotFoundError:
                subprocess.Popen(['xdg-open', str(video_path)])
                return True, f"Opened: {video_path.name}"
    
    except Exception as e:
        return False, f"Failed to open video: {e}"


def find_sibling_videos_folder(csv_path: str) -> Optional[str]:
    """Find a 'videos' folder that is a sibling to the CSV file.
    
    Args:
        csv_path: Path to the CSV file
        
    Returns:
        Path to videos folder if found, None otherwise
    """
    csv_path = Path(csv_path)
    parent = csv_path.parent
    
    # Check for 'videos' folder in same directory
    videos_folder = parent / "videos"
    if videos_folder.exists() and videos_folder.is_dir():
        return str(videos_folder)
    
    # Also check parent's parent (in case CSV is in a subfolder)
    grandparent = parent.parent
    videos_folder = grandparent / "videos"
    if videos_folder.exists() and videos_folder.is_dir():
        return str(videos_folder)
    
    return None
