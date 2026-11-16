"""MIDI of Time - emulator connection layer.

The MIDI engine produces emulator-neutral steps:
    {'buttons': ['A', 'ZL'], 'left_stick': [0, -0.52], 'frames': 12}
(Nintendo button names, stick values -1..1, durations in displayed game frames).

A Backend delivers those steps to one kind of emulator. To support another emulator later, add a class
with the same methods and put it in BACKENDS. Nothing in the engine or the arranger has to change.

Only one configuration is VERIFIED: Fritchii v5.8.4 with the NX2 debug server (see COMPATIBILITY.md).
"""
import json, socket, time

OOT_PROGRAM_ID = '0400486024DEC000'
# (emulator name, version) pairs tested end to end with real playback. Everything else is "untested".
VERIFIED = {('Fritchii', '5.8.4')}


class Info:
    """Result of probing a backend. state: 'offline' | 'incompatible' | 'untested' | 'verified'."""
    def __init__(self, state, message, emulator='', version='', fps=None, program_id=None, build=''):
        self.state, self.message, self.emulator, self.version = state, message, emulator, version
        self.fps, self.program_id, self.build = fps, program_id, build

    @property
    def usable(self):
        return self.state in ('verified', 'untested')


class SequenceCall:
    """One running input sequence. wait() blocks until the game finished it; cancel() stops it (input is released)."""
    def __init__(self, sock, started):
        self.sock, self.started, self.cancelled = sock, started, False

    def wait(self, timeout):
        self.sock.settimeout(timeout)
        buf = b''
        try:
            while not buf.endswith(b'\n') and not self.cancelled:
                c = self.sock.recv(65536)
                if not c:
                    break
                buf += c
        finally:
            self.close()
        if self.cancelled:
            return None
        r = json.loads(buf or b'{}')
        if 'error' in r or 'result' not in r:
            raise BackendError(str(r.get('error', 'no reply from the emulator')))
        return r['result']

    def cancel(self):
        self.cancelled = True
        self.close()

    def close(self):
        s, self.sock = self.sock, None
        if s:
            for f in (lambda: s.shutdown(socket.SHUT_RDWR), s.close):
                try:
                    f()
                except OSError:
                    pass


class BackendError(RuntimeError):
    pass


class NX2DebugServer:
    """Fritchii's NX2 debug server: TCP JSON lines on 127.0.0.1:6545, enabled with EDEN_NX2_DEBUG_SERVER."""
    id = 'nx2-debug-server'
    display = 'NX2 debug server (Fritchii)'
    launch_env = ('EDEN_NX2_DEBUG_SERVER', '127.0.0.1:6545')
    max_steps = 1000

    def __init__(self, host='127.0.0.1', port=6545):
        self.host, self.port = host, port
        self._checked = None          # cached capability result for the current connection

    def _rpc(self, method, params, timeout):
        req = json.dumps({'id': int(time.time() * 1000) % 1000000, 'method': method, 'params': params}) + '\n'
        with socket.create_connection((self.host, self.port), timeout=timeout) as s:
            s.settimeout(timeout); s.sendall(req.encode())
            buf = b''
            while not buf.endswith(b'\n'):
                c = s.recv(65536)
                if not c:
                    break
                buf += c
        return json.loads(buf or b'{}')

    def probe(self):
        try:
            r = self._rpc('status', {}, 1.5)
        except (OSError, ValueError):
            self._checked = None
            return Info('offline', 'No emulator debug server is answering on this PC.')
        res = r.get('result') if isinstance(r, dict) else None
        if not isinstance(res, dict):
            self._checked = None
            return Info('incompatible', 'Something answered on the debug port, but not the expected debug server '
                                        '(no status). This emulator build is not supported.')
        build = str(res.get('build', '')).strip()
        emu, ver = parse_build(build)
        fps, pid = res.get('fps'), str(res.get('program_id') or '')
        if self._checked is None or self._checked[0] != build:
            self._checked = (build, self._has_input_sequence())
        if not self._checked[1]:
            return Info('incompatible', f'{build or "This emulator"} has a debug server but no input_sequence support, '
                                        'so Link cannot be played. Use the verified build (see COMPATIBILITY).',
                        emu, ver, fps, pid, build)
        if (emu, ver) in VERIFIED:
            state, msg = 'verified', f'{build}: verified.'
        else:
            state = 'untested'
            msg = (f'{build or "Unknown emulator build"}: not tested with MIDI of Time. It has the expected debug server, '
                   'so playback may work - please report results. Verified: Fritchii v5.8.4.')
        if pid and pid.upper() != OOT_PROGRAM_ID:
            msg += ' The running game does not look like the Ocarina of Time remake.'
        return Info(state, msg, emu, ver, fps, pid, build)

    def _has_input_sequence(self):
        """Ask for an empty sequence. A compatible server rejects it with its step-count message - no input is sent."""
        try:
            r = self._rpc('input_sequence', {'controller': 'player1', 'steps': []}, 1.5)
        except (OSError, ValueError):
            return False
        err = str(r.get('error', '')) if isinstance(r, dict) else ''
        return 'steps' in err and 'unknown method' not in err.lower()

    def start_sequence(self, steps, controller='player1'):
        if len(steps) > self.max_steps:
            raise BackendError(f'too many steps in one request ({len(steps)} > {self.max_steps})')
        req = json.dumps({'id': int(time.time() * 1000) % 1000000, 'method': 'input_sequence',
                          'params': {'controller': controller, 'steps': steps}}) + '\n'
        s = socket.create_connection((self.host, self.port), timeout=10)
        started = time.time()
        s.sendall(req.encode())
        return SequenceCall(s, started)

    def release(self):
        try:
            self._rpc('input_sequence', {'controller': 'player1',
                                         'steps': [{'buttons': [], 'left_stick': [0, 0], 'frames': 1}]}, 3)
        except (OSError, ValueError):
            pass


def parse_build(build):
    """'Fritchii v5.8.4 ' -> ('Fritchii', '5.8.4')."""
    parts = build.replace('-', ' ').split()
    name = parts[0] if parts else ''
    ver = next((p.lstrip('vV') for p in parts[1:] if p.lstrip('vV')[:1].isdigit()), '')
    return name, ver


BACKENDS = [NX2DebugServer()]


def detect():
    """First backend that answers, with its compatibility verdict; otherwise the default backend, offline."""
    first = None
    for b in BACKENDS:
        info = b.probe()
        if info.state != 'offline':
            return b, info
        first = first or (b, info)
    return first
