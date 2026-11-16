"""Controller kill switch: stop playback the moment the player takes over the controller.

Reads the physical controller through Windows XInput (xinput1_4.dll). Input that the app injects into
the emulator never shows up here, so the app's own notes cannot trip it.

Trips on: D-pad left or right. Tested by the user on 2026-11-15: D-pad left puts the Ocarina away and D-pad right
opens the song menu; both wreck playback. D-pad up/down do nothing during a song. Everything else is ignored on purpose: face buttons add notes, holding a
bumper/trigger shifts the whole song a half step (a feature), the physical left stick is overridden by the app, and
the right stick pans the camera.
Buttons already held when playback starts are ignored until they are released.
Controllers that are not XInput devices are not watched (watch() returns False).
"""
import ctypes
import sys
import threading
import time


class _State(ctypes.Structure):
    _fields_ = [('packet', ctypes.c_uint32), ('buttons', ctypes.c_uint16), ('lt', ctypes.c_uint8),
                ('rt', ctypes.c_uint8), ('lx', ctypes.c_int16), ('ly', ctypes.c_int16),
                ('rx', ctypes.c_int16), ('ry', ctypes.c_int16)]


_xi = None
if sys.platform == 'win32':
    for _name in ('xinput1_4', 'xinput1_3', 'xinput9_1_0'):
        try:
            _xi = getattr(ctypes.windll, _name).XInputGetState
            break
        except (OSError, AttributeError):
            continue

KILL_BUTTONS = 0x000C   # XInput D-pad left 0x0004 + right 0x0008 (up 0x0001 / down 0x0002 are harmless)
POLL_S = 0.008


def _read():
    """{slot: (buttons, lt, rt, lx, ly)} for every connected XInput controller."""
    out = {}
    if _xi is None:
        return out
    for slot in range(4):
        st = _State()
        if _xi(slot, ctypes.byref(st)) == 0:
            out[slot] = (st.buttons, st.lt, st.rt, st.lx, st.ly)
    return out


def available():
    return bool(_read())


def _active(v):
    return v[0] & KILL_BUTTONS


class Watch:
    def __init__(self, on_trip):
        self.on_trip, self.done, self.tripped = on_trip, threading.Event(), None
        base = {s: _active(v) for s, v in _read().items()}
        self.held = {s: [b] for s, b in base.items()}   # inputs held at start, ignored until released
        self.ok = bool(base)
        if self.ok:
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self.done.is_set():
            for slot, v in _read().items():
                buttons = _active(v)
                h = self.held.setdefault(slot, [0])
                h[0] &= buttons
                what = 'D-pad left/right' if buttons & ~h[0] else None
                if what:
                    self.tripped = what
                    self.done.set()
                    try:
                        self.on_trip(what)
                    finally:
                        return
            time.sleep(POLL_S)

    def stop(self):
        self.done.set()


class Shortcuts:
    """Reports D-pad presses: on_key('up' | 'down' | 'left' | 'right'), once per press.

    The app decides what they mean; it only acts on them while a song is playing or paused.
    """
    KEYS = (('up', 0x0001), ('down', 0x0002), ('left', 0x0004), ('right', 0x0008))

    def __init__(self, on_key):
        self.on_key, self.done = on_key, threading.Event()
        self.prev = {s: v[0] for s, v in _read().items()}
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self.done.is_set():
            for slot, v in _read().items():
                was, now = self.prev.get(slot, 0), v[0]
                self.prev[slot] = now
                for name, bit in self.KEYS:
                    if now & bit and not was & bit:
                        try:
                            self.on_key(name)
                        except Exception:  # noqa: BLE001 - never let a UI hiccup kill the poller
                            pass
            time.sleep(0.02)

    def stop(self):
        self.done.set()
