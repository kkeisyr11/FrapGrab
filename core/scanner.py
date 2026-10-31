import time
import cv2
from .config import load_config
from .events import parse_killfeed


class MatchScanner:
    def __init__(self, video_path, gamertag, on_progress_callback=None):
        self.video_path, self.gamertag = video_path, gamertag
        self.on_progress_callback = on_progress_callback
        self.stop_requested = False

    def cancel(self):
        self.stop_requested = True

    def scan(self):
        if len(self.gamertag.strip()) < 3:
            raise ValueError("Podaj nick gracza (minimum 3 znaki).")
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        cap = cv2.VideoCapture(self.video_path)
        try:
            if not cap.isOpened():
                raise ValueError("Nie można odczytać tego nagrania.")
            fps = cap.get(cv2.CAP_PROP_FPS)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if fps <= 0 or total <= 0:
                raise ValueError("Nagranie nie ma poprawnych informacji o czasie.")
            x, y, w, h = load_config()["killfeed_region"]
            events, seen = [], {}
            for frame_index in range(0, total, max(1, int(fps * .8))):
                if self.stop_requested:
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = cap.read()
                if not ok:
                    break
                stamp = frame_index / fps
                H, W = frame.shape[:2]
                patch = frame[int(y*H):int((y+h)*H), int(x*W):int((x+w)*W)]
                results, _ = ocr(patch)
                seen = {k: t for k, t in seen.items() if stamp-t < 12}
                for event in parse_killfeed(results, self.gamertag, patch.shape[1]):
                    fresh = event["signature"] not in seen
                    seen[event["signature"]] = stamp
                    if fresh and event["event_type"] in ("kill", "assist"):
                        events.append({**event, "timestamp": round(stamp, 2),
                            "time_str": time.strftime("%H:%M:%S", time.gmtime(stamp)),
                            "type": "Eliminacja" if event["event_type"] == "kill" else "Asysta", "info": event["raw_text"]})
                if self.on_progress_callback:
                    self.on_progress_callback(min(1, (frame_index + fps*.8) / total), len(events))
            return events
        finally:
            cap.release()
