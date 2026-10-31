"""DPI-aware controls with supersampled graphics and native text."""
import math
import customtkinter as ctk
from PIL import Image,ImageDraw,ImageTk
from .images import AppImage


def chevron_image(size,color):
    scale=6
    image=Image.new('RGBA',(size*scale,size*scale))
    draw=ImageDraw.Draw(image)
    points=[(size*.24,size*.38),(size*.5,size*.64),(size*.76,size*.38)]
    points=[(round(x*scale),round(y*scale)) for x,y in points]
    width=max(1,round(size*.115*scale));radius=width/2
    draw.line(points,fill=color,width=width,joint='curve')
    for x,y in points:draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=color)
    return image.resize((size,size),Image.Resampling.LANCZOS)


def controller_image(size):
    scale=6;s=size*scale
    image=Image.new('RGBA',(s,s));draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((0,0,s-1,s-1),radius=s*.28,fill='#2B3831')
    draw.rounded_rectangle((s*.19,s*.29,s*.81,s*.73),radius=s*.14,outline='#D4F78A',width=round(s*.045))
    draw.line((s*.3,s*.51,s*.46,s*.51),fill='#D4F78A',width=round(s*.045))
    draw.line((s*.38,s*.43,s*.38,s*.59),fill='#D4F78A',width=round(s*.045))
    for x,y in ((.65,.45),(.72,.55)):
        draw.ellipse((s*(x-.027),s*(y-.027),s*(x+.027),s*(y+.027)),fill='#D4F78A')
    return image.resize((size,size),Image.Resampling.LANCZOS)


class SmoothOptionMenu(ctk.CTkOptionMenu):
    def _draw(self,*args,**kwargs):
        super()._draw(*args,**kwargs)
        self._canvas.itemconfigure('dropdown_arrow',state='hidden')
        size=max(10,round(self._apply_widget_scaling(14)))
        color=self._apply_appearance_mode(self._text_color_disabled if self._state=='disabled' else self._text_color)
        key=(size,color)
        if key!=getattr(self,'_chevron_key',None):
            rgb=tuple(channel//257 for channel in self.winfo_rgb(color))
            self._chevron_photo=ImageTk.PhotoImage(chevron_image(size,rgb),master=self._canvas)
            self._chevron_key=key
        if not self._canvas.find_withtag('smooth_arrow'):
            self._canvas.create_image(0,0,tags='smooth_arrow')
        self._canvas.itemconfigure('smooth_arrow',image=self._chevron_photo)
        self._canvas.coords('smooth_arrow',self._apply_widget_scaling(self._current_width-self._current_height/2),
            self._apply_widget_scaling(self._current_height/2))
        self._canvas.tag_raise('smooth_arrow')


class GameSelector(SmoothOptionMenu):
    def __init__(self,master,**kwargs):
        super().__init__(master,width=264,height=54,corner_radius=12,
            fg_color='#20272C',button_color='#20272C',button_hover_color='#2C373E',
            text_color='#F1F2ED',font=ctk.CTkFont('Segoe UI',15,weight='bold'),**kwargs)

    def _create_grid(self):
        super()._create_grid()
        self._text_label.grid_configure(padx=(self._apply_widget_scaling(60),self._apply_widget_scaling(self._current_height+3)))

    def _draw(self,*args,**kwargs):
        super()._draw(*args,**kwargs)
        size=max(20,round(self._apply_widget_scaling(34)))
        if size!=getattr(self,'_controller_size',None):
            self._controller_photo=ImageTk.PhotoImage(controller_image(size),master=self._canvas)
            self._controller_size=size
        if not self._canvas.find_withtag('game_icon'):
            self._canvas.create_image(0,0,tags='game_icon')
        self._canvas.itemconfigure('game_icon',image=self._controller_photo)
        self._canvas.coords('game_icon',self._apply_widget_scaling(29),self._apply_widget_scaling(self._current_height/2))


def gauge_image(fraction,size=720):
    image=Image.new('RGBA',(size,size));draw=ImageDraw.Draw(image)
    width=round(size*.028);margin=round(size*.075)
    bounds=(margin,margin,size-margin-1,size-margin-1)
    draw.ellipse(bounds,outline='#303A40',width=width)
    if fraction>=1:draw.ellipse(bounds,outline='#D4F78A',width=width)
    elif fraction>0:
        draw.arc(bounds,-90,-90+360*fraction,fill='#D4F78A',width=width)
        radius=(size-2*margin-width)/2
        for angle in (-90,-90+360*fraction):
            x=(size-1)/2+radius*math.cos(math.radians(angle))
            y=(size-1)/2+radius*math.sin(math.radians(angle))
            r=width/2;draw.ellipse((x-r,y-r,x+r,y+r),fill='#D4F78A')
    return image


class ReplayGauge(ctk.CTkFrame):
    def __init__(self,master,caption,**kwargs):
        super().__init__(master,width=184,height=184,fg_color='transparent',**kwargs)
        self.pack_propagate(False)
        self.fraction=0
        self._gauge_image=AppImage(self,light_image=gauge_image(0),size=(184,184))
        self._graphic=ctk.CTkLabel(self,text='',image=self._gauge_image)
        self._graphic.place(relx=.5,rely=.5,anchor='center')
        self.number=ctk.CTkLabel(self,text='0 s',text_color='#F1F2ED',
            font=ctk.CTkFont('Segoe UI',32,weight='bold'))
        self.number.place(relx=.5,rely=.44,anchor='center')
        self.caption=ctk.CTkLabel(self,text=caption,text_color='#9CA7AE',font=ctk.CTkFont('Segoe UI',10))
        self.caption.place(relx=.5,rely=.63,anchor='center')

    def set_value(self,text,fraction):
        self.number.configure(text=text)
        if fraction!=self.fraction:
            self.fraction=fraction
            self._gauge_image.configure(light_image=gauge_image(fraction))

    def set_caption(self,text):self.caption.configure(text=text)
