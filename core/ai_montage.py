"""Prepare a path-free editing brief and validate a provider's proposed cuts."""
import json
import math
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from .highlights import _metadata_events
from .media import probe


@dataclass(frozen=True)
class Cut:
    path: Path
    start: float
    end: float


def prepare_brief(paths, goal, seconds, vertical, language):
    if not 1 <= len(paths) <= 80:
        raise ValueError("Wybierz od 1 do 80 klipów.")
    if not 10 <= seconds <= 600:
        raise ValueError("Podaj długość od 10 do 600 sekund.")
    request_id = secrets.token_hex(6)
    sources, details = {}, []
    for index, path in enumerate(paths, 1):
        info = probe(path)
        duration = float(info["format"]["duration"])
        if not math.isfinite(duration) or duration < .3 or not any(
                stream["codec_type"] == "video" for stream in info["streams"]):
            raise ValueError("Jeden z wybranych klipów nie zawiera poprawnego wideo.")
        clip_id = f"C{index:02}"
        sources[clip_id] = (path, duration)
        events = [{"time": round(event["time"], 3), "type": event["type"]}
                  for event in _metadata_events(path, duration)[:100]
                  if isinstance(event["type"], str) and event["type"] in {"kill", "assist", "visual", "death", "knockdown", "downed",
                                       "goal", "save", "win", "mic", "manual"}]
        details.append({"clip": clip_id, "duration": round(duration, 3), "events": events})
    payload = {"request_id": request_id, "target_seconds": seconds, "format": "9:16" if vertical else "16:9",
               "title_language": language, "editing_request": goal[:1200], "clips": details}
    prompt = (
        "You are planning an edit of gameplay highlights. Return only JSON with keys request_id, title and cuts. "
        'Each cut has keys clip, start and end, with times in seconds from the start of that clip. '
        "Use the given request_id exactly. Order cuts for the final movie, avoid overlaps from the same clip, "
        "respect the clip durations and target length, and keep context around chosen events. "
        "You only have the listed metadata. Do not invent dialogue or events. "
        "Use no more than 80 cuts, each at least 0.3 seconds.\n\n" + json.dumps(payload, ensure_ascii=False)
    )
    return prompt, request_id, sources


def validate_plan(text, request_id, sources):
    error = "Plan jest nieprawidłowy lub dotyczy innego zestawu klipów."
    if not isinstance(text, str) or len(text) > 64_000:
        raise ValueError(error)
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", text, re.DOTALL | re.IGNORECASE)
    try:
        data = json.loads(fenced[1] if fenced else text)
    except ValueError:
        raise ValueError(error) from None
    if not isinstance(data, dict) or data.get("request_id") != request_id:
        raise ValueError(error)
    rows, title = data.get("cuts"), data.get("title")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 80 or not isinstance(title, str):
        raise ValueError(error)
    cuts, ranges = [], {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("clip"), str) or row["clip"] not in sources:
            raise ValueError(error)
        path, duration = sources[row["clip"]]
        start, end = row.get("start"), row.get("end")
        if type(start) not in (int, float) or type(end) not in (int, float):
            raise ValueError(error)
        if not 0 <= start < end <= duration + .0005:
            raise ValueError(error)
        end = min(end, duration)
        if end - start < .3:
            raise ValueError(error)
        intervals = ranges.setdefault(path, [])
        if any(start < previous_end and end > previous_start for previous_start, previous_end in intervals):
            raise ValueError("Plan zawiera nakładające się wycinki tego samego klipu.")
        intervals.append((start, end))
        cuts.append(Cut(path, float(start), float(end)))
    if sum(cut.end - cut.start for cut in cuts) > 660:
        raise ValueError("Plan przekracza 11 minut.")
    return " ".join(title.split())[:120], tuple(cuts)
