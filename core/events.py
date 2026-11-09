"""The same conservative killfeed parser is used live and for recorded matches."""
import re
import unicodedata

EVENT_LABELS = {
    "kill": "Zabójstwo", "assist": "Asysta", "death": "Śmierć", "knockdown": "Powalenie",
    "downed": "Powalono Cię", "goal": "Gol", "save": "Obrona", "win": "Zwycięstwo",
    "manual": "Powtórka", "mic": "Reakcja głosowa",
}

class ClipEventFilter:
    """Match assists on either side of a kill while footage is still buffered."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.last_kill = None
        self.assists = []

    def select(self, event, enabled, window):
        kind, _, _, stamp = event
        if not window:
            self.reset()
            return [event] if kind in enabled else []
        self.assists = [item for item in self.assists if abs(item[3] - stamp) <= window]
        if kind == "kill":
            self.last_kill = stamp
            matched, self.assists = self.assists, []
            return (matched if "assist" in enabled else []) + ([event] if kind in enabled else [])
        if kind not in enabled:
            return []
        if kind == "assist" and (self.last_kill is None or abs(stamp - self.last_kill) > window):
            self.assists.append(event)
            return []
        return [event]


def clip_event_label(metadata):
    if not isinstance(metadata, dict):
        return ""
    markers = metadata.get("events", [])
    kinds = [marker.get("type") for marker in markers if isinstance(marker, dict)] if isinstance(markers, list) else []
    labels = {}
    for kind in [*kinds, metadata.get("reason")]:
        if isinstance(kind, str) and kind not in ("manual", "mic"):
            label = EVENT_LABELS.get("kill" if kind == "visual" else kind)
            if label:
                labels[label] = None
    reason = metadata.get("reason")
    return " · ".join(labels) or (EVENT_LABELS.get(reason, "") if isinstance(reason, str) else "")


def normalize(text):
    text = text.lower().replace("ł", "l")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return "".join(c for c in text if c.isalnum())


def parse_killfeed(results, gamertag, width):
    def identity(value):
        return normalize(value).translate(str.maketrans({"1": "i", "l": "i", "0": "o"}))
    gt = identity(gamertag)
    if len(gt) < 3:
        return []
    lines = []
    for box, text, confidence in results or []:
        if confidence < .65 or not text.strip():
            continue
        cy = sum(p[1] for p in box) / len(box)
        cx = sum(p[0] for p in box) / len(box)
        height = max(p[1] for p in box) - min(p[1] for p in box)
        item = (cx, cy, text, height)
        line = next((line for line in lines if abs(line[0][1] - cy) < max(8, min(line[0][3], height) * .6)), None)
        if line is None:
            lines.append([item])
        else:
            line.append(item)
    events = []
    for line in lines:
        line.sort()
        raw = " ".join(it[2] for it in line)
        # Require an entire name token; "pat" must never match "patryk".
        names = [(it[0], re.sub(r"\[[^\]]*\]", "", it[2]).strip()) for it in line]
        names = [(x, text) for x, text in names if re.search(r"\w", text)]
        matching = [i for i, (_, text) in enumerate(names) if gt in [identity(t) for t in re.findall(r"[\w-]+", text)]]
        if not matching:
            continue
        index = matching[0]
        if len(names) == 1:
            tokens = [identity(t) for t in re.findall(r"[\w-]+", names[0][1])]
            if len(tokens) < 2:
                continue  # A lone name is not proof of an elimination.
            role = "kill" if tokens[0] == gt else "death" if tokens[-1] == gt else None
        else:
            role = "kill" if index == 0 else "death" if index == len(names)-1 else None
        if not role:
            continue
        middle = re.findall(r"[\w-]+", raw.casefold())[1:-1]
        down = any(re.fullmatch(r"powal\w*|downed|knock(?:ed|down)", word) for word in middle)
        if down:
            role = "knockdown" if role == "kill" else "downed"
        elif role == "kill" and any(s in raw.lower() for s in ("assist", "asyst", "+")):
            role = "assist"
        victim = gamertag if role in ("death", "downed") else line[-1][2]
        events.append({"event_type": role, "raw_text": raw, "victim": victim,
                       "signature": role + ":" + normalize(raw)})
    return events
