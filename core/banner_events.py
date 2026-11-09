"""Experimental screen-only match result detectors."""

import time

from .events import normalize


# Fractional monitor regions. Only the English results HUD is covered.
BANNER_PROFILES = {
    "fortnite": ((.19, .02, .62, .38), ("victory royale", "1 victory royale")),
    "pubg": ((.02, .02, .96, .47), ("winner winner chicken dinner",)),
    "apex": ((.08, .25, .84, .48), ("you are the champion",)),
    "warzone": ((.08, .23, .84, .50), ("warzone victory",)),
}


def matches_banner(results, phrases, image_height):
    expected = {normalize(phrase) for phrase in phrases}
    fragments = []
    for box, text, confidence in results or ():
        if confidence < .82 or len(box) != 4:
            continue
        ys = [point[1] for point in box]
        height = max(ys) - min(ys)
        if height < max(12, image_height * .05):
            continue
        word = normalize(text)
        if word in expected:
            return True
        xs = [point[0] for point in box]
        fragments.append((min(xs), min(ys), max(xs), max(ys), word, height))
    # OCR may split a banner into separate words or two stacked lines.
    for left, top, right, bottom, word, height in fragments:
        text = word
        previous_right = right
        nearby = sorted((part for part in fragments
                         if part[0] >= right and abs(top - part[1]) <= height * .45), key=lambda part: part[0])
        for other_left, _, other_right, _, other, _ in nearby:
            if other_left - previous_right > height * 1.6:
                break
            text += other
            if text in expected:
                return True
            if not any(phrase.startswith(text) for phrase in expected):
                break
            previous_right = other_right
        for other_left, other_top, other_right, _, other, _ in fragments:
            if 0 <= other_top - bottom <= height and min(right, other_right) > max(left, other_left):
                if word + other in expected:
                    return True
    return False


class BannerLatch:
    """Emit a result once, retaining the time of the first positive frame."""

    def __init__(self):
        self.first = None
        self.active = False
        self.clear_frames = 0

    def observe(self, present, stamp):
        if present:
            self.clear_frames = 0
            if self.active:
                return None
            if self.first is None or stamp - self.first > 2.5:
                self.first = stamp
                return None
            self.active = True
            return self.first
        self.first = None
        self.clear_frames += 1
        if self.clear_frames >= 3:
            self.active = False
        return None


class BannerEvents:
    def __init__(self, game_id, monitor, ocr):
        from .pixel_detector import VisualPatch
        x, y, w, h = BANNER_PROFILES[game_id][0]
        self.phrases = BANNER_PROFILES[game_id][1]
        self.left = monitor["left"] + int(x * monitor["width"])
        self.top = monitor["top"] + int(y * monitor["height"])
        width = max(2, int(w * monitor["width"]))
        height = max(2, int(h * monitor["height"]))
        self.size = (min(width, 960), max(2, round(height * min(1, 960 / width))))
        self.capture = VisualPatch(width, height, monitor)
        self.ocr = ocr
        self.latch = BannerLatch()

    def poll(self):
        import cv2
        frame = self.capture.grab(self.left, self.top)
        if frame is None:
            return None
        stamp = time.monotonic()
        if tuple(frame.shape[1::-1]) != self.size:
            frame = cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA)
        results, _ = self.ocr(frame)
        return self.latch.observe(matches_banner(results, self.phrases, frame.shape[0]), stamp)

    def close(self):
        self.capture.close()
