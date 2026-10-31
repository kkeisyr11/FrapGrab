"""Runtime PL/EN UI strings. Choice values remain stable for application logic."""
import json
import re
import weakref
from pathlib import Path
import customtkinter as ctk
from tkinter import filedialog as _filedialog,messagebox as _messagebox

_language="pl"
_catalog={}
_pattern=None
_widgets=weakref.WeakSet()


def set_language(language):
    global _language,_catalog,_pattern
    _language="en" if language=="en" else "pl"
    if not _catalog:
        path=Path(__file__).resolve().parents[1]/"assets/languages/en.json"
        _catalog=json.loads(path.read_text(encoding="utf-8"))
        keys=[key for key in _catalog if len(key)>=4 or key=="do "]
        _pattern=re.compile("|".join((r"(?<!\w)" if key[0].isalnum() else "")+re.escape(key)+
            (r"(?!\w)" if key[-1].isalnum() else "") for key in sorted(keys,key=len,reverse=True)))
    for widget in list(_widgets):
        try:widget.retranslate()
        except Exception:pass


def t(text):
    if _language!="en" or not isinstance(text,str):return text
    if text in _catalog:return _catalog[text]
    return _pattern.sub(lambda match:_catalog[match.group()],text) if _pattern else text


class TextMixin:
    def __init__(self,*args,**kwargs):
        self._source_text=kwargs.get("text")
        self._source_placeholder=kwargs.get("placeholder_text")
        for key in ("text","placeholder_text"):
            if key in kwargs:kwargs[key]=t(kwargs[key])
        super().__init__(*args,**kwargs);_widgets.add(self)
    def configure(self,**kwargs):
        for key,attr in (("text","_source_text"),("placeholder_text","_source_placeholder")):
            if key in kwargs:setattr(self,attr,kwargs[key]);kwargs[key]=t(kwargs[key])
        return super().configure(**kwargs)
    config=configure
    def retranslate(self):
        values={}
        if self._source_text is not None:values["text"]=t(self._source_text)
        if self._source_placeholder is not None:values["placeholder_text"]=t(self._source_placeholder)
        if values:super().configure(**values)


class LLabel(TextMixin,ctk.CTkLabel):
    def _update_image(self):
        # CTk 6 leaves the native Tk image unchanged for image=None. After the
        # PhotoImage is collected, even setting label text raises TclError.
        if getattr(self,"_image",None) is None and hasattr(self,"_label"):
            self._label.configure(image="")
        else:super()._update_image()
class LButton(TextMixin,ctk.CTkButton):pass
class LSwitch(TextMixin,ctk.CTkSwitch):pass
class LEntry(TextMixin,ctk.CTkEntry):pass
class LCheckBox(TextMixin,ctk.CTkCheckBox):pass
class LTextbox(ctk.CTkTextbox):
    def insert(self,index,text,*args):return super().insert(index,t(text),*args)


class LOptionMenu(ctk.CTkOptionMenu):
    def __init__(self,*args,**kwargs):
        self._canonical_values=list(kwargs.get("values",[]))
        self._canonical_current=self._canonical_values[0] if self._canonical_values else ""
        self._user_command=kwargs.pop("command",None)
        kwargs["values"]=[t(value) for value in self._canonical_values]
        kwargs["command"]=self._changed
        super().__init__(*args,**kwargs);_widgets.add(self)
    def _changed(self,value):
        self._canonical_current=next((item for item in self._canonical_values if t(item)==value),value)
        if self._user_command:self._user_command(self._canonical_current)
    def get(self):return self._canonical_current
    def set(self,value):
        self._canonical_current=value
        super().set(t(value))
    def configure(self,**kwargs):
        if "values" in kwargs:
            self._canonical_values=list(kwargs["values"]);kwargs["values"]=[t(v) for v in self._canonical_values]
        if "command" in kwargs:self._user_command=kwargs["command"];kwargs["command"]=self._changed
        return super().configure(**kwargs)
    config=configure
    def retranslate(self):
        super().configure(values=[t(v) for v in self._canonical_values])
        super().set(t(self._canonical_current))


class Dialogs:
    def __init__(self,module):self.module=module
    def __getattr__(self,name):
        def call(*args,**kwargs):
            args=tuple(t(arg) for arg in args)
            for key in ("title","message","detail"):
                if key in kwargs:kwargs[key]=t(kwargs[key])
            if "filetypes" in kwargs:kwargs["filetypes"]=[(t(label),pattern) for label,pattern in kwargs["filetypes"]]
            return getattr(self.module,name)(*args,**kwargs)
        return call


filedialog=Dialogs(_filedialog)
messagebox=Dialogs(_messagebox)
