"""Offline tests for MIDI of Time (no emulator needed). Run: python tests/test_offline.py"""
import json, os, socket, struct, sys, tempfile, threading, time, types, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from midi_of_time import engine as P, smart as S, remote as R

ok = fail = 0
def check(name, cond, info=''):
    global ok, fail
    if cond: ok += 1; print(f'PASS  {name}')
    else: fail += 1; print(f'FAIL  {name}  {info}')

# 1. demo MIDI parses and arranges at 30 and 60 FPS
div, tempos, tracks = P.parse_midi(P.make_demo(), 'demo')
check('demo parses', len(tracks) == 1 and len(tracks[0]['notes']) == 54)
def arrange(fps):
    a = types.SimpleNamespace(tune='tuned', legato='auto', vibrato=0, vib_rate=5, bend_range=2, speed=1)
    t2s = P.tick_to_sec(div, tempos); tr = tracks[0]
    mel = [(t2s(s), t2s(c), t2s(e), p, ch) for s, c, e, p, ch in P.skyline(tr['notes'])]
    first = mel[0][0]; pitches, _ = S.phrase_fit(mel, 72, 88)
    notes = [(round((s - first) * fps), round((c - first) * fps), k + 1 < len(mel) and e >= mel[k + 1][0] - .02, q, ch)
             for k, ((s, c, e, _, ch), q) in enumerate(zip(mel, pitches))]
    bend = P.Curve([(t2s(t), c, v) for t, c, v in tr['bends']], 0); mod = P.Curve([(t2s(t), c, v) for t, c, v in tr['mods']], 0)
    return P.build_steps(notes, fps, a, bend, mod, lambda f: first + f / fps)
s30, st30, t30 = arrange(30); s60, st60, t60 = arrange(60)
check('30 FPS steps valid', all(1 <= x['frames'] <= 300 for x in s30) and t30 > 500)
check('60 FPS is twice the frames', abs(t60 / t30 - 2) < 0.02, f'{t30} vs {t60}')
valid = {'A', 'B', 'X', 'Y', 'L', 'R', 'ZL'}
check('only Ocarina buttons used', all(set(x['buttons']) <= valid for x in s30))
check('sticks in range', all(-1 <= x['left_stick'][1] <= 1 and x['left_stick'][0] == 0 for x in s30))
# breath: no held run longer than the breath limit
run = longest = 0
for x in s30:
    run = run + x['frames'] if x['buttons'] else 0; longest = max(longest, run)
check('no continuous hold beyond 6.3 s', longest <= 189, longest)

# 2. every MIDI pitch C5-E6 maps to a reachable fingering within 25 cents (tuned mode)
worst = 0
for m in range(72, 89):
    fb, fm, fc = P.choose_fingering(m * 100 + 24, m * 100 + 24, m * 100 + 24, None, False, True)
    y = P.cents_to_y(m * 100 + 24 - fc)
    i = min(range(len(P.CAL_Y) - 1), key=lambda k: abs(P.CAL_Y[k] - y))
    worst = max(worst, abs((m * 100 + 24 - fc) - (P.CAL_C[0] if y <= -1 else P.CAL_C[-1] if y >= 1 else (m * 100 + 24 - fc))))
check('all notes C5-E6 reachable', worst <= 25, worst)

# 3. smart follow on a two-part MIDI where the tune moves from part 1 to part 2
def vl(v):
    o = [v & 0x7f]; v >>= 7
    while v: o.insert(0, (v & 0x7f) | 0x80); v >>= 7
    return bytes(o)
def trk(name, evs):
    b = vl(0) + b'\xff\x03' + vl(len(name)) + name.encode(); last = 0
    for t, m in sorted(evs): b += vl(t - last) + m; last = t
    b += vl(0) + b'\xff\x2f\x00'; return b'MTrk' + struct.pack('>I', len(b)) + b
def notes(ch, ps, t0, step=240):
    ev = []; t = t0
    for p in ps: ev += [(t, bytes([0x90 | ch, p, 90])), (t + step - 10, bytes([0x80 | ch, p, 0]))]; t += step
    return ev
lead = notes(0, [74, 76, 77, 79, 81, 79, 77, 76] * 8, 0)                 # 0-16 s
lead2 = notes(1, [81, 83, 84, 86, 84, 83, 81, 79] * 8, 15360)            # 16-32 s, other part
pad = notes(2, [50] * 32, 0, 960)
mid = b'MThd' + struct.pack('>IHHh', 6, 1, 3, 480) + trk('Flute', lead) + trk('Violin', lead2) + trk('Bass pad', pad)
div2, tem2, tr2 = P.parse_midi(mid, 't'); t2s = P.tick_to_sec(div2, tem2)
line, segs = S.follow_melody(tr2, t2s, P.skyline, 0)
ks = [k for _, k in segs]
check('smart follows tune to the second part', ks[0] == 0 and 1 in ks and 2 not in ks, segs)

# 4. remote: PIN required, lockout after 5 wrong tries
class Fake:
    remote_q = __import__('queue').Queue()
    def remote_state(self): return {'status': 'ok'}
    def remote_songs(self): return {'rev': '1', 'all': [], 'fav': [], 'recent': []}
    def remote_search(self, q): return []
    def remote_call(self, n, d): return {'ok': True}
f = Fake(); port = 18999; R.serve(f, port, '123456')
def drain():
    while True:
        try: f.remote_q.get(timeout=0.1)()
        except Exception: pass
threading.Thread(target=drain, daemon=True).start()
def get(p):
    try: return urllib.request.urlopen(f'http://127.0.0.1:{port}{p}', timeout=3).status
    except urllib.error.HTTPError as e: return e.code
check('page served without PIN', get('/') == 200)
check('API refuses wrong PIN', get('/api/state?k=000000') == 403)
check('API accepts right PIN', get('/api/state?k=123456') == 200)
for _ in range(5): get('/api/state?k=999999')
check('locked out after repeated wrong PINs', get('/api/state?k=123456') == 403)

# 5. engine send() fails cleanly when no emulator is listening
try:
    P.HOST, P.PORT = '127.0.0.1', 1   # nothing listens here
    P.send([{'buttons': [], 'left_stick': [0, 0], 'frames': 1}], 2)
    check('no-emulator connection error raised', False)
except OSError:
    check('no-emulator connection error raised', True)


# 6. connection layer: compatibility verdicts against fake debug servers
from midi_of_time import backends as B
def fake_server(port, handler):
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(('127.0.0.1', port)); srv.listen(8)
    def loop():
        while True:
            c, _ = srv.accept(); line = b''
            while not line.endswith(b'\n'):
                d = c.recv(65536)
                if not d: break
                line += d
            try: c.sendall((json.dumps(handler(json.loads(line))) + '\n').encode())
            except Exception: pass
            c.close()
    threading.Thread(target=loop, daemon=True).start()
def fritchii(build):
    def h(req):
        if req['method'] == 'status':
            return {'id': req['id'], 'result': {'build': build, 'fps': 29.9, 'program_id': '0400486024DEC000'}}
        if req['method'] == 'input_sequence':
            n = len(req['params']['steps'])
            if not 1 <= n <= 1000: return {'id': req['id'], 'error': 'steps must be an array of 1 to 1000'}
            return {'id': req['id'], 'result': {'frames': sum(s['frames'] for s in req['params']['steps']), 'first_present': 1, 'elapsed_s': 0.1}}
        return {'id': req['id'], 'error': 'unknown method'}
    return h
cases = [(19101, fritchii('Fritchii v5.8.4 '), 'verified'), (19102, fritchii('Fritchii v6.0 '), 'untested'), (19106, fritchii('Fritchii v6.1 '), 'verified'),
         (19103, fritchii('Lichii build-177'), 'untested'),
         (19104, lambda r: {'id': r['id'], 'error': 'unknown method'}, 'incompatible'),
         (19105, lambda r: ({'id': r['id'], 'result': {'build': 'X 1.0'}} if r['method'] == 'status' else {'id': r['id'], 'error': 'unknown method'}), 'incompatible')]
for port, h, want in cases:
    fake_server(port, h)
for port, h, want in cases:
    info = B.NX2DebugServer(port=port).probe()
    check(f'backend verdict {want} (port {port})', info.state == want, f'{info.state}: {info.message}')
check('backend verdict offline', B.NX2DebugServer(port=19199).probe().state == 'offline')
call = B.NX2DebugServer(port=19101).start_sequence([{'buttons': ['A'], 'left_stick': [0, 0], 'frames': 5}])
check('sequence round trip', call.wait(5)['frames'] == 5)
try:
    B.NX2DebugServer(port=19101).start_sequence([{'buttons': [], 'left_stick': [0, 0], 'frames': 1}] * 1001); check('step limit enforced', False)
except B.BackendError:
    check('step limit enforced', True)

# 9. controller kill switch and D-pad shortcuts (fake XInput)
from midi_of_time import padwatch as W
pad = {'v': (0x0004, 0, 0, 0, 0)}                 # D-pad left already held when the song starts
W._read = lambda: {0: pad['v']}
hits = []; w = W.Watch(hits.append); time.sleep(.05)
check('kill switch ignores a D-pad press held at start', w.ok and not hits)
pad['v'] = (0x0001 | 0x0002 | 0x1000 | 0x2000 | 0x0100 | 0x0200 | 0x0010, 255, 255, 30000, -30000); time.sleep(.06)
check('kill switch ignores up/down, face buttons, bumpers, triggers, sticks', not hits, hits)
pad['v'] = (0, 0, 0, 0, 0); time.sleep(.03); pad['v'] = (0x0008, 0, 0, 0, 0); time.sleep(.06)
check('kill switch trips on D-pad right', hits == ['D-pad left/right'], hits)
pad['v'] = (0, 0, 0, 0, 0); hits.clear(); w = W.Watch(hits.append); time.sleep(.03); pad['v'] = (0x0004, 0, 0, 0, 0); time.sleep(.06)
check('kill switch trips on D-pad left', hits == ['D-pad left/right'], hits)
keys = []; pad['v'] = (0, 0, 0, 0, 0); sc = W.Shortcuts(keys.append); time.sleep(.05)
for v in (0x0001, 0x0001, 0, 0x0002, 0, 0x0004): pad['v'] = (v, 0, 0, 0, 0); time.sleep(.05)
sc.stop(); check('D-pad shortcuts fire once per press', keys == ['up', 'down', 'left'], keys)
W._read = lambda: {}
check('no XInput controller: kill switch reports off', not W.Watch(lambda x: 0).ok)

# 10. resume continues from the paused note, not the start of the piece
import importlib.util as _iu, re as _re
_src = (ROOT / 'src' / 'midi_of_time' / 'app.py').read_text(encoding='utf-8')
_ns = {'CHUNK_MIN_FRAMES': 240}
for _fn in ('resume_chunks', 'split_chunks'):
    exec(_re.search(r'^def %s\(.*?(?=^\S)' % _fn, _src, _re.S | _re.M).group(0), _ns)
_steps = [{'buttons': ['A'] if i % 2 == 0 else [], 'frames': 30} for i in range(40)]
_c = _ns['resume_chunks'](_steps, 605)
check('resume starts at the note playing when paused', _c[0][0] == 600 and _c[0][1][0] is _steps[20], _c[0][0])
check('resume keeps the rest of the song', sum(x['frames'] for _, part in _c for x in part) == 600)

# 11. smart breathing: never more than BREATH frames without a real (>= 4-frame) breath; timing unchanged
_a = types.SimpleNamespace(tune='tuned', legato='auto', vibrato=0, vib_rate=5, bend_range=2, speed=1)
_z = lambda ch, t: 0
for _name, _notes in (('staccato', [(i * 6, i * 6 + 5, False, 74 + (i % 5) * 2, 0) for i in range(150)]),
                      ('slur chain', [(i * 10, i * 10 + 10, True, 74 + (i % 4) * 3, 0) for i in range(90)]),
                      ('20 s note', [(0, 600, False, 81, 0)])):
    _steps, _st, _total = P.build_steps(_notes, 30, _a, _z, _z, lambda f: f / 30)
    _worst = _r = 0
    for _s in _steps:
        if not _s['buttons'] and _s['frames'] >= 4: _r = 0
        else: _r += _s['frames']; _worst = max(_worst, _r)
    check(f'breathing: {_name} never runs out of breath', _worst <= P.BREATH, _worst)
    check(f'breathing: {_name} keeps song timing', sum(_s['frames'] for _s in _steps) == _total and all(_s['frames'] > 0 for _s in _steps))

# 12. fast slurred runs (2026-11-18, Bloody Tears): every note is too short to lend a whole breath, so breaths must be
#     borrowed from several notes. Checked at 30 and 60 FPS (breath limits scale with the game's frame rate).
for _fps in (30, 60):
    _k = _fps // 30
    _fast = [(i * 4 * _k, i * 4 * _k + 4 * _k, True, 74 + (i % 5) * 2, 0) for i in range(600)]   # ~80 s of 0.13 s notes, no gaps
    _steps, _st, _total = P.build_steps(_fast, _fps, _a, _z, _z, lambda f: f / _fps)
    _br, _lim = max(4, round(4 * _fps / 30)), int(P.BREATH * _fps / 30)
    _worst = _r = 0
    for _s in _steps:
        if not _s['buttons'] and _s['frames'] >= _br: _r = 0
        else: _r += _s['frames']; _worst = max(_worst, _r)
    check(f'breathing: fast slur run at {_fps} FPS never runs out of breath', _worst <= _lim, f'{_worst} > {_lim} frames')
    check(f'breathing: fast slur run at {_fps} FPS keeps song timing', sum(_s['frames'] for _s in _steps) == _total and all(_s['frames'] > 0 for _s in _steps))

print(f'\n{ok} passed, {fail} failed')
sys.exit(1 if fail else 0)
