"""Resolve DXGI output indices to desktop coordinates for both capture and OCR.

MSS monitor order is not DXGI output order, especially on multi-monitor systems.
"""
import ctypes as c
from ctypes import wintypes as w
import uuid


def outputs():
    factory, adapter = c.c_void_p(), c.c_void_p()
    records = []
    def method(ptr, index, result, *arguments):
        table = c.cast(ptr, c.POINTER(c.POINTER(c.c_void_p))).contents
        return c.WINFUNCTYPE(result, c.c_void_p, *arguments)(table[index])
    class GUID(c.Structure):
        _fields_ = [("data", c.c_ubyte * 16)]
    class Description(c.Structure):
        _fields_ = [("name", w.WCHAR * 32), ("rect", w.RECT), ("attached", w.BOOL),
                    ("rotation", c.c_int), ("monitor", c.c_void_p)]
    try:
        guid = GUID((c.c_ubyte * 16).from_buffer_copy(uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le))
        # IDXGIFactory1, EnumAdapters1, IDXGIAdapter::EnumOutputs, IDXGIOutput::GetDesc.
        create = c.windll.dxgi.CreateDXGIFactory1
        create.argtypes = [c.POINTER(GUID), c.POINTER(c.c_void_p)]
        create.restype = c.c_long
        if create(c.byref(guid), c.byref(factory)) < 0:
            raise OSError("DXGI factory unavailable")
        if method(factory, 12, c.c_long, c.c_uint, c.POINTER(c.c_void_p))(factory, 0, c.byref(adapter)) < 0:
            raise OSError("DXGI adapter unavailable")
        for index in range(16):
            output = c.c_void_p()
            if method(adapter, 7, c.c_long, c.c_uint, c.POINTER(c.c_void_p))(adapter, index, c.byref(output)) < 0:
                break
            try:
                desc = Description()
                if method(output, 7, c.c_long, c.POINTER(Description))(output, c.byref(desc)) >= 0 and desc.attached:
                    records.append({"index": index, "left": desc.rect.left, "top": desc.rect.top,
                        "width": desc.rect.right-desc.rect.left, "height": desc.rect.bottom-desc.rect.top, "name": desc.name})
            finally:
                method(output, 2, c.c_ulong)(output)
    except Exception:
        pass
    finally:
        if adapter:
            method(adapter, 2, c.c_ulong)(adapter)
        if factory:
            method(factory, 2, c.c_ulong)(factory)
    if not records:
        import mss
        with mss.mss() as screen:
            monitors = sorted(screen.monitors[1:], key=lambda m: (not m.get("is_primary", False), m["left"], m["top"]))
            records = [{**m, "index": i} for i, m in enumerate(monitors)]
    return records


def output_geometry(index):
    for record in outputs():
        if record["index"] == index:
            return record
    raise ValueError(f"Ekran DXGI {index} nie jest dostępny.")
