import math
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from core.audio_capture import DesktopAudio


class AudioClockTests(unittest.TestCase):
    def test_silent_inputs_keep_wall_clock_speed_with_coarse_windows_timers(self):
        for rate,channels in ((96000,8),(48000,2)):
            with self.subTest(rate=rate):
                clock=SimpleNamespace(now=0,stopped=False,bytes_sent=0)
                def wait(delay):
                    if delay>0:clock.now+=math.ceil(delay/.015625)*.015625
                    return False
                def empty(timeout=None):
                    if timeout:wait(timeout)
                    raise queue.Empty
                def send(data):
                    clock.bytes_sent+=len(data)
                    if clock.now>=2:clock.stopped=True
                connection=SimpleNamespace(settimeout=Mock(),sendall=send,close=Mock())
                audio=DesktopAudio.__new__(DesktopAudio)
                audio.stopped=SimpleNamespace(is_set=lambda:clock.stopped,wait=wait)
                audio.server=SimpleNamespace(accept=lambda:(connection,None))
                audio.queue=SimpleNamespace(get=empty,get_nowait=empty)
                audio.chunk=1024;audio.rate=rate;audio.channels=channels;audio.started=0;audio.connection=None
                with patch('core.audio_capture.time.monotonic',side_effect=lambda:clock.now):audio._write()
                media_seconds=clock.bytes_sent/(rate*channels*2)
                self.assertAlmostEqual(media_seconds,clock.now,delta=.04)


if __name__=='__main__':unittest.main()
