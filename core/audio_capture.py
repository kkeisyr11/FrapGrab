"""Clocked WASAPI sources, delivered locally to FFmpeg without occupying control stdin."""
import queue
import ctypes
from contextlib import contextmanager
import socket
import threading
import time
import numpy as np


def output_devices():
    """Stable names for additional WASAPI outputs; never persist session indices."""
    import pyaudiowpatch as pa
    with audio_thread():
        manager=pa.PyAudio()
        try:return sorted({device['name'] for device in manager.get_loopback_device_info_generator()})
        finally:manager.terminate()


def conversation_device(manager,selected="",exclude_default=True):
    primary=manager.get_default_wasapi_loopback()
    devices=list(manager.get_loopback_device_info_generator())
    if selected:
        device=next((d for d in devices if d['name']==selected),None)
        if device is None:raise ValueError("Wybrane źródło rozmów jest niedostępne. Wybierz je ponownie w ustawieniach.")
    elif 'sonar' in primary['name'].lower():
        device=next((d for d in devices if 'sonar' in d['name'].lower() and 'chat' in d['name'].lower()),None)
        if device is None:raise LookupError("Nie znaleziono Sonar Chat.")
    else:raise LookupError("Brak automatycznego dodatkowego źródła rozmów.")
    if exclude_default and device['index']==primary['index']:
        raise LookupError("Źródło rozmów jest już nagrywane z dźwiękiem systemowym.")
    return device


@contextmanager
def audio_thread():
    """Balance COM on the calling thread, including concurrent WASAPI clients.

    https://learn.microsoft.com/en-us/windows/win32/learnwin32/initializing-the-com-library
    """
    ole32=ctypes.windll.ole32
    result=ole32.CoInitializeEx(None,0)
    if result not in (0,1,-2147417850):  # RPC_E_CHANGED_MODE: already initialized STA
        raise OSError(f"Audio COM initialization failed: {result:#x}")
    try:yield
    finally:
        if result in (0,1):ole32.CoUninitialize()


class MicrophoneMonitor:
    """Own the microphone and its COM lifetime on one persistent worker."""
    def __init__(self,on_level):
        self.on_level=on_level
        self.stopped=threading.Event()
        self.ready=threading.Event()
        self.error=None

    def start(self):
        self.thread=threading.Thread(target=self._run,daemon=True)
        self.thread.start()
        if not self.ready.wait(10):
            self.close()
            raise TimeoutError("Mikrofon nie odpowiada.")
        if self.error:raise self.error

    def _run(self):
        try:
            with audio_thread():
                source=DesktopAudio("microphone",self.on_level,monitor_only=True)
                try:
                    source.start()
                    self.ready.set()
                    self.stopped.wait()
                finally:source.close()
        except Exception as exc:self.error=exc
        finally:self.ready.set()

    def close(self):
        self.stopped.set()
        thread=getattr(self,"thread",None)
        if thread and thread is not threading.current_thread():thread.join(timeout=4)


class DesktopAudio:
    def __init__(self,role="system",on_level=None,*,monitor_only=False,device_name="",exclude_default=True):
        import pyaudiowpatch as pa
        self.pa,self.role,self.on_level=pa,role,on_level
        self.monitor_only=monitor_only
        self.manager=pa.PyAudio()
        self.server=self.connection=self.stream=None
        self.stopped=threading.Event()
        self.last_meter=0
        try:
            if role=="system":
                self.device=self.manager.get_default_wasapi_loopback()
            elif role=="microphone":
                self.device=self.manager.get_default_wasapi_device(d_in=True)
            elif role=="chat":
                self.device=conversation_device(self.manager,device_name,exclude_default)
            else:raise ValueError("Nieznane źródło audio.")
            self.rate=int(self.device["defaultSampleRate"])
            self.channels=int(self.device["maxInputChannels"])
            self.chunk=1024
            self.queue=None if monitor_only else queue.Queue(maxsize=512)
            self.stream=self.manager.open(format=pa.paInt16,channels=self.channels,rate=self.rate,
                input=True,input_device_index=self.device["index"],frames_per_buffer=self.chunk,
                stream_callback=self._callback,start=False)
            if not monitor_only:
                self.server=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
                self.server.bind(("127.0.0.1",0))
                self.server.listen(1)
                self.server.settimeout(.2)
                self.input_url=f"tcp://127.0.0.1:{self.server.getsockname()[1]}"
        except Exception:
            if self.stream:self.stream.close()
            if self.server:self.server.close()
            self.manager.terminate()
            raise

    def _callback(self,data,frame_count,time_info,status):
        if self.queue is not None:
            try:self.queue.put_nowait(data)
            except queue.Full:pass
        now=time.monotonic()
        if self.on_level and now-self.last_meter>.16:
            self.last_meter=now
            samples=np.frombuffer(data,dtype=np.int16).astype(np.float32)/32768
            level=min(100,float(np.sqrt(np.mean(samples*samples)))*350)
            self.on_level(level,self.role)
        return None,self.pa.paContinue

    def start(self):
        self.started=time.monotonic()
        self.stream.start_stream()
        if self.monitor_only:return
        self.thread=threading.Thread(target=self._write,daemon=True)
        self.thread.start()

    def _write(self):
        try:
            while not self.stopped.is_set():
                try:self.connection,_=self.server.accept();break
                except socket.timeout:continue
            if not self.connection:return
            self.connection.settimeout(1)
            period=self.chunk/self.rate
            deadline=self.started
            silence=bytes(self.chunk*self.channels*2)
            while not self.stopped.is_set():
                try:data=self.queue.get(timeout=period)
                except queue.Empty:data=silence
                self.connection.sendall(data)
                deadline+=len(data)/(self.rate*self.channels*2)
                self.stopped.wait(max(0,deadline-time.monotonic()))
        except (OSError,ValueError):pass
        finally:
            if self.connection:
                try:self.connection.close()
                except OSError:pass

    def close(self):
        self.stopped.set()
        if self.server:
            try:self.server.close()
            except OSError:pass
        if self.connection:
            try:self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        if self.stream:
            try:self.stream.stop_stream();self.stream.close()
            except OSError:pass
            self.stream=None
        self.manager.terminate()
