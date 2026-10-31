from .editor import VideoEditor


class ClipRenderer:
    @staticmethod
    def render_single_clip(video_path, timestamp, out_path, before_sec=15, after_sec=5,
                           is_vertical=False, codec="h264_nvenc", bitrate="25M"):
        start = max(0, timestamp-before_sec)
        duration = timestamp+after_sec-start
        return VideoEditor.trim_clip(video_path, start, duration, out_path, codec, is_vertical)

    @staticmethod
    def render_supercut_montage(clip_paths, out_path):
        return VideoEditor.create_montage(clip_paths, out_path)
