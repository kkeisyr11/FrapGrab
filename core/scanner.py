import time
import logging
from pathlib import Path
import numpy as np
from .config import load_config
from .events import parse_killfeed,normalize
from .media import probe,find_binary,run_command,MediaCancelled
from .hardware import decode_backends,decoder_args


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
        info=probe(self.video_path)
        video=next((s for s in info['streams'] if s['codec_type']=='video'),None)
        total=float(info['format'].get('duration',0))
        if not video or total<=0:raise ValueError("Nagranie nie ma poprawnych informacji o czasie.")
        config=load_config()
        if Path(config.get('pixel_profile') or '__missing_profile__').is_file() and normalize(config.get('gamertag',''))==normalize(self.gamertag):
            from .highlights import discover_events
            try:
                detected=discover_events(self.video_path,info,
                    (lambda value,message:self.on_progress_callback(value,0)) if self.on_progress_callback else None,
                    cancelled=lambda:self.stop_requested)
            except MediaCancelled:return []
            events=[]
            for event in detected:
                if event.get('confidence')!='player_hud' or event['type'] not in ('kill','assist'):continue
                stamp=event['time'];kind=event['type']
                events.append({'event_type':kind,'timestamp':round(stamp,2),
                    'time_str':time.strftime('%H:%M:%S',time.gmtime(stamp)),
                    'type':'Eliminacja' if kind=='kill' else 'Asysta','raw_text':'Dopasowanie graficzne',
                    'info':'Dopasowanie graficzne','confidence':'player_hud'})
            if self.on_progress_callback:self.on_progress_callback(1,len(events))
            return events
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        x,y,w,h=config['killfeed_region']
        W,H=video['width'],video['height']
        left,top=int(x*W),int(y*H)
        width,height=max(2,int((x+w)*W)-left),max(2,int((y+h)*H)-top)
        frame_bytes=width*height*3
        for backend in decode_backends():
            events,seen,pending=[],{},bytearray()
            frame_index=0
            def consume(chunk):
                nonlocal frame_index,seen
                pending.extend(chunk)
                while len(pending)>=frame_bytes:
                    if self.stop_requested:raise MediaCancelled('Anulowano analizę.')
                    patch=np.frombuffer(bytes(pending[:frame_bytes]),np.uint8).reshape(height,width,3)
                    del pending[:frame_bytes]
                    stamp=min(total,frame_index*.8);frame_index+=1
                    results,_=ocr(patch)
                    seen={key:t for key,t in seen.items() if stamp-t<12}
                    for event in parse_killfeed(results,self.gamertag,width):
                        fresh=event['signature'] not in seen
                        seen[event['signature']]=stamp
                        if fresh and event['event_type'] in ('kill','assist'):
                            events.append({**event,'timestamp':round(stamp,2),
                                'time_str':time.strftime('%H:%M:%S',time.gmtime(stamp)),
                                'type':'Eliminacja' if event['event_type']=='kill' else 'Asysta','info':event['raw_text']})
                    if self.on_progress_callback:self.on_progress_callback(min(1,(stamp+.8)/total),len(events))
            vf='fps=1.25,'+('hwdownload,format=nv12,' if backend=='cuda' else '')+f'crop={width}:{height}:{left}:{top}:exact=1,format=bgr24'
            cmd=[find_binary('ffmpeg'),'-v','error',*decoder_args(backend,hardware_frames=True),
                 '-i',str(self.video_path),'-an','-sn','-dn','-vf',vf,'-f','rawvideo','pipe:1']
            try:
                run_command(cmd,max(120,total*3),cancelled=lambda:self.stop_requested,on_data=consume)
                if self.on_progress_callback:self.on_progress_callback(1,len(events))
                return events
            except MediaCancelled:return events
            except RuntimeError:
                if backend=='cpu':raise
                logging.exception('GPU match scanning failed; retrying sequential CPU decode')
