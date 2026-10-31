"""One time value drives both the replay counter and its progress ring."""
import math


def buffer_display(available, capacity):
    try:capacity = max(1, int(capacity))
    except (ValueError, TypeError, OverflowError):capacity = 60
    try:available = float(available)
    except (ValueError, TypeError):available = 0
    if not math.isfinite(available):available = 0
    seconds = min(capacity, max(0, math.floor(available + 1e-6)))
    text = f'{seconds} s' if seconds < 60 else f'{seconds // 60}:{seconds % 60:02d}'
    return text, seconds / capacity, seconds == capacity
