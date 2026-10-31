"""The same conservative killfeed parser is used live and for recorded matches."""
import re
import unicodedata


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
        if role == "kill" and any(s in raw.lower() for s in ("assist", "asyst", "+")):
            role = "assist"
        victim = line[-1][2] if role != "death" else gamertag
        events.append({"event_type": role, "raw_text": raw, "victim": victim,
                       "signature": role + ":" + normalize(raw)})
    return events
