"""Clocked WASAPI sources, delivered locally to FFmpeg without occupying control stdin."""
import queue
import socket
import threading
import time
import numpy as np


class DesktopAudio:
    def __init__(self,role="system",on_level=None):
        import pyaudiowpatch as pa
        self.pa,self.role,self.on_level=pa,role,on_level
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
                primary=self.manager.get_default_wasapi_loopback()
                if "sonar" not in primary["name"].lower() or "chat" in primary["name"].lower():
                    raise LookupError("Rozmowy nie wymagają osobnego wejścia Sonar Chat.")
                self.device=next((d for d in self.manager.get_loopback_device_info_generator()
                    if "sonar" in d["name"].lower() and "chat" in d["name"].lower()),None)
                if self.device is None:raise LookupError("Nie znaleziono Sonar Chat.")
            else:raise ValueError("Nieznane źródło audio.")
            self.rate=int(self.device["defaultSampleRate"])
            self.channels=int(self.device["maxInputChannels"])
            self.chunk=1024
            self.queue=queue.Queue(maxsize=512)
            self.stream=self.manager.open(format=pa.paInt16,channels=self.channels,rate=self.rate,
                input=True,input_device_index=self.device["index"],frames_per_buffer=self.chunk,
                stream_callback=self._callback,start=False)
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
