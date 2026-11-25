# ruff: noqa
"""Decodificador PDF417 real (zxing-cpp del sistema, por el complemento de GStreamer) vía ctypes: decode(png_path) -> bytes | None."""
import ctypes, sys
G=ctypes.CDLL('libgstreamer-1.0.so.0'); 
G.gst_parse_launch.restype=ctypes.c_void_p; G.gst_parse_launch.argtypes=[ctypes.c_char_p,ctypes.c_void_p]
G.gst_element_get_bus.restype=ctypes.c_void_p; G.gst_element_get_bus.argtypes=[ctypes.c_void_p]
G.gst_element_set_state.argtypes=[ctypes.c_void_p,ctypes.c_int]
G.gst_bus_timed_pop_filtered.restype=ctypes.c_void_p; G.gst_bus_timed_pop_filtered.argtypes=[ctypes.c_void_p,ctypes.c_uint64,ctypes.c_int]
G.gst_message_get_structure.restype=ctypes.c_void_p; G.gst_message_get_structure.argtypes=[ctypes.c_void_p]
G.gst_structure_get_string.restype=ctypes.c_char_p; G.gst_structure_get_string.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
G.gst_structure_get_name.restype=ctypes.c_char_p; G.gst_structure_get_name.argtypes=[ctypes.c_void_p]
G.gst_structure_to_string.restype=ctypes.c_char_p; G.gst_structure_to_string.argtypes=[ctypes.c_void_p]
G.gst_object_unref.argtypes=[ctypes.c_void_p]; G.gst_mini_object_unref.argtypes=[ctypes.c_void_p]
G.gst_init(None,None)
class GstMessage(ctypes.Structure): _fields_=[('mini',ctypes.c_byte*64),('type',ctypes.c_int)]
def decode(path, extra='format=pdf_417 try-rotate=true try-faster=false'):
    p=G.gst_parse_launch(f'filesrc location={path} ! pngdec ! videoconvert ! zxing {extra} ! fakesink'.encode(),None)
    if not p: return None
    bus=G.gst_element_get_bus(p); G.gst_element_set_state(p,4); out=None
    while True:
        m=G.gst_bus_timed_pop_filtered(bus,5_000_000_000,(1<<15)|1|2)   # ELEMENT | EOS | ERROR
        if not m: break
        t=ctypes.cast(m,ctypes.POINTER(GstMessage)).contents.type
        if t==(1<<15):
            s=G.gst_message_get_structure(m)
            if s and G.gst_structure_get_name(s)==b'barcode': out=G.gst_structure_get_string(s,b'symbol') or b''; G.gst_mini_object_unref(m); break
        G.gst_mini_object_unref(m)
        if t in (1,2): break
    G.gst_element_set_state(p,1); G.gst_object_unref(bus); G.gst_object_unref(p)
    return out
CTRL='NUL SOH STX ETX EOT ENQ ACK BEL BS HT LF VT FF CR SO SI DLE DC1 DC2 DC3 DC4 NAK SYN ETB CAN EM SUB ESC FS GS RS US'.split()
def to_bytes(sym):
    """El complemento entrega texto con los caracteres de control escritos como <NUL>, <SOH>…: se devuelven a bytes (lo que espera parseCedula)."""
    import re
    t=sym.decode('utf8','replace'); t=re.sub(r'<([A-Z0-9]{2,3})>',lambda m: chr(CTRL.index(m.group(1))) if m.group(1) in CTRL else (chr(127) if m.group(1)=='DEL' else m.group(0)),t)
    return [ord(c)&0xFF for c in t]
LOCK=__import__('threading').Lock()
if __name__=='__main__':
    for f in sys.argv[1:]:
        r=decode(f); print(f, None if r is None else ('LEIDO', len(r)))
