"""Downsampling utilities for efficient plotting of large time series."""

import numpy as np
from typing import Tuple


def downsample_minmax(t: np.ndarray, y: np.ndarray, n_target: int) -> Tuple[np.ndarray, np.ndarray]:
    """Downsample time series using min/max bucketing to preserve spikes.
    
    This method ensures that extreme values are preserved in the downsampled view,
    which is critical for identifying events in the overview plot.
    
    Args:
        t: Time array (1D)
        y: Value array (1D, can contain NaN)
        n_target: Target number of points in output
        
    Returns:
        Tuple of (t_downsampled, y_downsampled)
        
    Notes:
        - If len(t) <= n_target, returns original arrays
        - Preserves NaN values in appropriate buckets
        - Each bucket contributes 2 points (min and max)
    """
    n = len(t)
    
    if n <= n_target:
        return t.copy(), y.copy()
    
    # Calculate bucket size
    bucket_size = n // (n_target // 2)  # Divide by 2 since we output min+max per bucket
    
    if bucket_size < 2:
        return t.copy(), y.copy()
    
    # Number of complete buckets
    n_buckets = n // bucket_size
    
    t_down = np.zeros(n_buckets * 2)
    y_down = np.zeros(n_buckets * 2)
    
    for i in range(n_buckets):
        start_idx = i * bucket_size
        end_idx = min((i + 1) * bucket_size, n)
        
        bucket_t = t[start_idx:end_idx]
        bucket_y = y[start_idx:end_idx]
        
        # Find min and max indices (ignoring NaN)
        valid_mask = np.isfinite(bucket_y)
        
        if np.any(valid_mask):
            valid_y = bucket_y[valid_mask]
            valid_t = bucket_t[valid_mask]
            valid_indices = np.where(valid_mask)[0]
            
            min_idx = valid_indices[np.argmin(valid_y)]
            max_idx = valid_indices[np.argmax(valid_y)]
            
            # Store min first, then max (to preserve temporal ordering roughly)
            if min_idx < max_idx:
                t_down[i * 2] = bucket_t[min_idx]
                y_down[i * 2] = bucket_y[min_idx]
                t_down[i * 2 + 1] = bucket_t[max_idx]
                y_down[i * 2 + 1] = bucket_y[max_idx]
            else:
                t_down[i * 2] = bucket_t[max_idx]
                y_down[i * 2] = bucket_y[max_idx]
                t_down[i * 2 + 1] = bucket_t[min_idx]
                y_down[i * 2 + 1] = bucket_y[min_idx]
        else:
            # All NaN in bucket, use first point
            t_down[i * 2] = bucket_t[0]
            y_down[i * 2] = np.nan
            t_down[i * 2 + 1] = bucket_t[-1] if len(bucket_t) > 1 else bucket_t[0]
            y_down[i * 2 + 1] = np.nan
    
    return t_down, y_down


def downsample_lttb(t: np.ndarray, y: np.ndarray, n_target: int) -> Tuple[np.ndarray, np.ndarray]:
    """Downsample using Largest-Triangle-Three-Buckets algorithm.
    
    LTTB preserves visual shape better than simple decimation while being
    more sophisticated than min/max bucketing.
    
    Args:
        t: Time array (1D)
        y: Value array (1D, can contain NaN)
        n_target: Target number of points in output
        
    Returns:
        Tuple of (t_downsampled, y_downsampled)
        
    Notes:
        - Always includes first and last points
        - NaN values may be excluded from output
        - Good for smooth curves; min/max better for spiky data
    """
    n = len(t)
    
    if n <= n_target or n_target < 3:
        return t.copy(), y.copy()
    
    # Filter out NaN for algorithm (we'll handle them separately)
    valid_mask = np.isfinite(y)
    t_valid = t[valid_mask]
    y_valid = y[valid_mask]
    
    if len(t_valid) < n_target:
        return t_valid.copy(), y_valid.copy()
    
    # LTTB algorithm
    bucket_size = (len(t_valid) - 2) / (n_target - 2)
    
    sampled_idx = [0]  # Always include first point
    
    a = 0  # Current point
    
    for i in range(n_target - 2):
        # Calculate bucket range
        avg_range_start = int(np.floor((i + 1) * bucket_size) + 1)
        avg_range_end = int(np.floor((i + 2) * bucket_size) + 1)
        avg_range_end = min(avg_range_end, len(t_valid))
        
        # Calculate average point in next bucket
        avg_t = np.mean(t_valid[avg_range_start:avg_range_end])
        avg_y = np.mean(y_valid[avg_range_start:avg_range_end])
        
        # Find point in current bucket that forms largest triangle
        range_start = int(np.floor(i * bucket_size) + 1)
        range_end = int(np.floor((i + 1) * bucket_size) + 1)
        
        point_a_t = t_valid[a]
        point_a_y = y_valid[a]
        
        max_area = -1
        next_a = range_start
        
        for idx in range(range_start, range_end):
            # Calculate triangle area
            area = abs(
                (point_a_t - avg_t) * (y_valid[idx] - point_a_y) -
                (point_a_t - t_valid[idx]) * (avg_y - point_a_y)
            )
            
            if area > max_area:
                max_area = area
                next_a = idx
        
        sampled_idx.append(next_a)
        a = next_a
    
    sampled_idx.append(len(t_valid) - 1)  # Always include last point
    
    return t_valid[sampled_idx], y_valid[sampled_idx]


def decimate_to_target(t: np.ndarray, y: np.ndarray, n_target: int) -> Tuple[np.ndarray, np.ndarray]:
    """Simple decimation by uniform sampling.
    
    Fastest method but can miss spikes. Use only when speed is critical.
    
    Args:
        t: Time array (1D)
        y: Value array (1D, can contain NaN)
        n_target: Target number of points in output
        
    Returns:
        Tuple of (t_downsampled, y_downsampled)
    """
    n = len(t)
    
    if n <= n_target:
        return t.copy(), y.copy()
    
    step = n // n_target
    indices = np.arange(0, n, step)[:n_target]
    
    return t[indices], y[indices]
