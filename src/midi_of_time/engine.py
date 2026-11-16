#!/usr/bin/env python3
"""MIDI of Time - engine: turns a MIDI melody into Ocarina input for Link, sent to a compatible emulator's debug server.

Requirements: an emulator build with the NX2 debug server (tested: Fritchii v5.8.4), started with
EDEN_NX2_DEBUG_SERVER=127.0.0.1:6545; player 1 controller connected; Link holding the Ocarina
(in-game Ocarina controls: Classic). The desktop app (app.py) is the normal way to use this.

Command line (optional):
  python -m midi_of_time.engine song.mid --list       show the tracks
  python -m midi_of_time.engine song.mid --dry-run    show what would be played, send nothing
  python -m midi_of_time.engine song.mid              play it
  python -m midi_of_time.engine demo                  built-in demo
  Options: --track N --start SEC --length SEC --speed X --transpose N --legato auto|all|off --tune tuned|raw
           --vibrato CENTS --fps 30|60

Instrument model (measured by mic/OBS analysis on Fritchii v5.8.4, 30 FPS mode):
  - Left stick y bends pitch continuously; changing stick, modifier (L +100c, ZL -100c) or base button
    while held slurs without a new attack.
  - One breath lasts ~7 s of continuous sound; a release starts a new breath.
"""
import argparse, bisect, json, math, socket, struct, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIDI_DIR = HERE.parent / 'Songs'
HOST, PORT = '127.0.0.1', 6545
NAMES = 'C C# D Eb E F F# G Ab A Bb B'.split()

# Stick y -> pitch change in cents (mean of A5 and F5 sweeps, 2026-11-14).
CAL_Y = [-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0]
CAL_C = [-202, -154, -100, -50, 0, 46, 88, 143, 192]
# Base buttons (Nintendo debug names): nominal MIDI note, measured offset in cents.
BASES = [('R', 74, 23), ('B', 77, 9), ('A', 81, 28), ('Y', 83, 24), ('X', 86, 24)]
MODS = [((), 0), (('L',), 100), (('ZL',), -100)]
TUNE_REF = 24                # tuned mode: every note aims at equal temperament + 24 cents (instrument median)
GAP_DIFF, GAP_SAME = 1, 2    # release frames before a different / repeated note (verified)
BREATH = 189                 # max frames (~6.3 s at 30 FPS) without a real breath; the sound dies at ~6.8 s (measured)
BREATH_REST = 4              # a release must be >= 4 frames to count as a breath (1-2 frames don't; measured 2026-11-15)
BREATH_LOOK = 75             # look back up to 2.5 s for a musical place to breathe
MIN_SLUR = 2                 # min frames per slurred note
MAX_STEP_FRAMES = 300        # long steps are split; per-step maximum is not known
CHUNK_STEPS = 1000           # steps per request; server maximum is 1000 (verified)


def nn(m):
    return f'{NAMES[m % 12]}{m // 12 - 1}'


def cents_to_y(c):
    c = max(CAL_C[0], min(CAL_C[-1], c))
    k = max(1, bisect.bisect_left(CAL_C, c))
    c0, c1, y0, y1 = CAL_C[k - 1], CAL_C[k], CAL_Y[k - 1], CAL_Y[k]
    return round(y0 + (y1 - y0) * (c - c0) / (c1 - c0), 3)


# ---------------------------------------------------------------- MIDI reading
def vlq(d, i):
    v = 0
    while True:
        b = d[i]; i += 1
        v = (v << 7) | (b & 0x7F)
        if b < 0x80:
            return v, i


def parse_midi(d, label='MIDI'):
    if d[:4] != b'MThd':
        sys.exit(f'Not a standard MIDI file: {label}')
    hlen = struct.unpack('>I', d[4:8])[0]
    _fmt, ntrk, div = struct.unpack('>HHh', d[8:14])
    if div < 0:
        sys.exit('SMPTE-timed MIDI files are not supported.')
    i, tracks, tempos = 8 + hlen, [], []
    while len(tracks) < ntrk and i + 8 <= len(d):
        cid, clen = d[i:i + 4], struct.unpack('>I', d[i + 4:i + 8])[0]
        j, end = i + 8, min(i + 8 + clen, len(d))
        i = i + 8 + clen
        if cid != b'MTrk':
            continue
        t, rs, name, notes, on, bends, mods = 0, None, '', [], {}, [], []
        try:
            while j < end:
                dt, j = vlq(d, j); t += dt
                st = d[j]
                if st == 0xFF:
                    typ = d[j + 1]; ln, j = vlq(d, j + 2); data = d[j:j + ln]; j += ln
                    if typ == 0x51 and ln == 3:
                        tempos.append((t, int.from_bytes(data, 'big')))
                    elif typ == 0x03 and not name:
                        name = data.decode('latin-1', 'replace').strip()
                    elif typ == 0x2F:
                        break
                    continue
                if st in (0xF0, 0xF7):
                    ln, j = vlq(d, j + 1); j += ln; continue
                if st & 0x80:
                    rs = st; j += 1
                elif rs is None:
                    break
                typ, ch = rs & 0xF0, rs & 0x0F
                a = d[j]; b = d[j + 1] if typ not in (0xC0, 0xD0) else 0
                j += 1 if typ in (0xC0, 0xD0) else 2
                if typ == 0x90 and b > 0:
                    if (ch, a) in on:
                        notes.append((on.pop((ch, a)), t, a, ch))
                    on[(ch, a)] = t
                elif typ == 0x80 or (typ == 0x90 and b == 0):
                    s = on.pop((ch, a), None)
                    if s is not None:
                        notes.append((s, t, a, ch))
                elif typ == 0xE0:
                    bends.append((t, ch, ((b << 7) | a) - 8192))
                elif typ == 0xB0 and a == 1:
                    mods.append((t, ch, b))
        except IndexError:
            pass  # truncated track: keep what was read
        notes += [(s, t, a, ch) for (ch, a), s in on.items()]
        tracks.append({'name': name, 'notes': sorted(notes), 'bends': sorted(bends), 'mods': sorted(mods)})
    return div, tempos, tracks


def tick_to_sec(div, tempos):
    tempos = sorted(tempos)
    if not tempos or tempos[0][0] != 0:
        tempos.insert(0, (0, 500000))
    seg, sec = [], 0.0
    for k, (tk, us) in enumerate(tempos):
        if k:
            sec += (tk - tempos[k - 1][0]) * tempos[k - 1][1] / 1e6 / div
        seg.append((tk, sec, us))
    keys = [s[0] for s in seg]

    def f(tick):
        tk, s, us = seg[bisect.bisect_right(keys, tick) - 1]
        return s + (tick - tk) * us / 1e6 / div
    return f


class Curve:
    """Step function per channel: value at time t = last event at or before t."""
    def __init__(self, events, default):
        self.by_ch, self.default = {}, default
        for t, ch, v in events:
            self.by_ch.setdefault(ch, ([], []))
            self.by_ch[ch][0].append(t); self.by_ch[ch][1].append(v)

    def __call__(self, ch, t):
        ts, vs = self.by_ch.get(ch, ((), ()))
        k = bisect.bisect_right(ts, t) - 1
        return vs[k] if k >= 0 else self.default

    def active(self):
        return any(any(v != self.default for v in vs) for _, vs in self.by_ch.values())


def make_demo():
    """Built-in test MIDI: legato run, whole-step bend, mod-wheel vibrato, repeats, breath-forcing chain."""
    ev = []  # (tick, bytes)
    q = 480
    def note(t, p, dur): ev.append((t, bytes([0x90, p, 100]))); ev.append((t + dur, bytes([0x80, p, 0])))
    t = 0
    for p in [74, 76, 77, 79, 81, 82, 84, 86, 84, 82, 81, 79, 77, 76, 74]:      # legato run
        note(t, p, 250); t += 240
    t += 480
    note(t, 81, 470); t += 480                                                 # A5, then G5 bent to A5
    note(t, 79, 1400)
    for k in range(9):
        v = 8192 + int(8191 * k / 8); ev.append((t + 240 + k * 20, bytes([0xE0, v & 0x7F, v >> 7])))
    for k in range(9):
        v = 16383 - int(8191 * k / 8); ev.append((t + 960 + k * 20, bytes([0xE0, v & 0x7F, v >> 7])))
    t += 1440 + 480
    note(t, 86, 1900)                                                          # D6 with mod-wheel ramp
    for k in range(13):
        ev.append((t + k * 120, bytes([0xB0, 1, min(127, k * 11)])))
    ev.append((t + 1900, bytes([0xB0, 1, 0])))
    t += 1920 + 480
    for p in [81, 81, 81, 81, 77, 74]:                                         # repeated notes, detached
        note(t, p, 100); t += 120
    t += 480
    for p in [74, 77, 81, 86, 81, 77] * 5:                                     # 7.5 s legato chain
        note(t, p, 250); t += 240
    ev.sort(key=lambda e: (e[0], e[1][0] == 0x90))
    body, last = b'', 0
    def vl(v):
        out = [v & 0x7F]; v >>= 7
        while v: out.insert(0, (v & 0x7F) | 0x80); v >>= 7
        return bytes(out)
    body += vl(0) + b'\xff\x51\x03' + (500000).to_bytes(3, 'big')
    for tk, b in ev:
        body += vl(tk - last) + b; last = tk
    body += vl(0) + b'\xff\x2f\x00'
    return b'MThd' + struct.pack('>IHHh', 6, 0, 1, q) + b'MTrk' + struct.pack('>I', len(body)) + body


# ---------------------------------------------------------------- arranging
def describe(tracks):
    rows = []
    for k, tr in enumerate(tracks):
        ns = tr['notes']
        if not ns:
            continue
        chans = sorted({n[3] + 1 for n in ns})
        ps = [n[2] for n in ns]
        rows.append((k, tr['name'] or '-', len(ns), min(ps), max(ps), sum(ps) / len(ps), chans, chans == [10]))
    return rows


def auto_track(rows):
    cand = [r for r in rows if not r[7]]
    if not cand:
        sys.exit('No non-drum tracks with notes.')
    most = max(r[2] for r in cand)
    cand = [r for r in cand if r[2] >= 0.15 * most]
    return max(cand, key=lambda r: r[5])[0]   # highest average pitch among substantial tracks


def skyline(notes):
    """One voice: highest note at each onset; cut at the next onset. Keeps the original end for legato."""
    by_start = {}
    for s, e, p, ch in notes:
        if p > by_start.get(s, (0, -1, 0))[1]:
            by_start[s] = (e, p, ch)
    seq = sorted((s, e, p, ch) for s, (e, p, ch) in by_start.items())
    out = []
    for k, (s, e, p, ch) in enumerate(seq):
        cut = min(e, seq[k + 1][0]) if k + 1 < len(seq) else e
        if cut > s:
            out.append((s, cut, e, p, ch))
    return out


def fit_range(pitches, lo, hi, forced):
    if forced is not None:
        shift = forced
    else:
        med = sorted(pitches)[len(pitches) // 2]
        shift = max(range(-60, 61, 12), key=lambda sh: (sum(lo <= p + sh <= hi for p in pitches),
                                                         -abs(med + sh - (lo + hi) / 2)))
    out, folded = [], 0
    for p in pitches:
        q = p + shift
        while q < lo: q += 12
        while q > hi: q -= 12
        folded += q != p + shift
        out.append(q)
    return shift, folded, out


def choose_fingering(lo_c, hi_c, mid_c, prev, slur, tuned):
    """Pick (base, mod, base_cents) so every target in [lo_c, hi_c] is reachable with the stick."""
    best = None
    for bname, bmidi, off in BASES:
        for mbtn, mc in MODS:
            fc = bmidi * 100 + (off if tuned else 0) + mc
            r_lo, r_hi, r_mid = lo_c - fc, hi_c - fc, mid_c - fc
            over = max(0, CAL_C[0] - 10 - r_lo) + max(0, r_hi - CAL_C[-1] - 10)
            cost = over * 100 + abs(r_mid) + (15 if mbtn else 0)
            if prev and slur:
                cost += (25 if bname != prev[0] else 0) + (10 if mbtn != prev[1] else 0)
            if best is None or cost < best[0]:
                best = (cost, bname, mbtn, fc)
    return best[1], best[2], best[3]


def apply_breaths(steps, limit, br, look, st):
    """Smart breathing (2026-11-15, measured on Fritchii v5.8.4 with OBS):
    the Ocarina sound dies ~6.8 s after the last breath, and the game only counts a release of about 4 frames
    (br) or more as a breath - 1- and 2-frame gaps between notes do NOT refill it. So whenever more than
    `limit` frames would pass without a real breath, a br-frame breath is placed at the most musical spot in
    the last `look` frames: an existing short gap (widened), else the end of the longest recent note. The
    frames come out of the end of the note before it, so the song's timing does not change."""
    out = [dict(s) for s in steps]
    i, run, start = 0, 0, 0
    while i < len(out):
        s = out[i]
        if not s['buttons'] and s['frames'] >= br:
            run, start, i = 0, i + 1, i + 1
            continue
        if run + s['frames'] <= limit:
            run += s['frames']; i += 1
            continue
        # look for the best boundary j (between out[j-1], a sounding step, and out[j]) in the window
        best, t, note_len = None, 0, 0
        for j in range(start + 1, i + 1):
            prev = out[j - 1]
            t += prev['frames']
            if not prev['buttons']:
                note_len = 0
                continue
            note_len = note_len + prev['frames'] if j - 2 >= start and out[j - 2]['buttons'] == prev['buttons'] else prev['frames']
            if j >= len(out) or t > limit or t < limit - look:
                continue
            nxt = out[j]
            gap = nxt['frames'] if not nxt['buttons'] else 0
            changes = gap > 0 or nxt['buttons'] != prev['buttons']
            need = br - gap
            if not changes or prev['frames'] <= need:
                continue
            score = min(note_len, 60) + (30 if gap else 0) + 10 * t / limit
            if best is None or score > best[0]:
                best = (score, j, gap, need)
        if best:
            _, j, gap, need = best
            out[j - 1]['frames'] -= need
            if gap:
                out[j]['frames'] = br
            else:
                out.insert(j, {'buttons': [], 'left_stick': [0, 0], 'frames': br})
            st['breaths'] += 1
        else:
            # one long held note: cut a breath into it right at the limit
            c = limit - run
            if s['buttons'] and c > br and s['frames'] - c > 0:
                head = dict(s, frames=c - br); tail = dict(s, frames=s['frames'] - c)
                out[i:i + 1] = [head, {'buttons': [], 'left_stick': [0, 0], 'frames': br}, tail]
            elif i > start and out[i - 1]['buttons'] and out[i - 1]['frames'] > br:
                out[i - 1]['frames'] -= br
                out.insert(i, {'buttons': [], 'left_stick': [0, 0], 'frames': br})
            else:
                run += s['frames']; i += 1          # cannot place one here; move on
                continue
            st['split'] += 1
        i, run = start, 0                           # re-scan from the last breath
    return out


def build_steps(notes, fps, a, bend, mod, t_of_frame):
    """notes: (on_f, off_f, legato_bool, midi, ch). Returns steps and stats."""
    steps, cur, breath, prev = [], 0, 0, None
    st = {'dropped': 0, 'slurs': 0, 'breaths': 0, 'split': 0}
    k30 = fps / 30.0                     # timing constants were measured at 30 FPS; scale them to the game's rate
    GAP_DIFF, GAP_SAME = max(1, round(1 * k30)), max(2, round(2 * k30))
    BREATH, MIN_SLUR = int(189 * k30), max(2, round(2 * k30))
    tuned = a.tune == 'tuned'
    ref = TUNE_REF if tuned else 0

    def rest(n):
        nonlocal breath
        if n > 0:
            breath = 0
        while n > 0:
            k = min(n, MAX_STEP_FRAMES)
            steps.append({'buttons': [], 'left_stick': [0, 0], 'frames': k}); n -= k

    def force_release(n=1):
        # turn the last n held frames into a release (a new breath)
        s = steps[-1] if steps else None
        if s and s['buttons'] and s['frames'] > n:
            s['frames'] -= n; steps.append({'buttons': [], 'left_stick': [0, 0], 'frames': n})
            return True
        return False

    def target(f, p, ch, t_on):
        c = p * 100 + ref
        t = t_of_frame(f)
        c += bend(ch, t) / 8192 * a.bend_range * 100
        depth = mod(ch, t) / 127 * 45
        if a.vibrato and t - t_on > 0.25:
            depth = max(depth, a.vibrato)
        if depth:
            c += depth * math.sin(2 * math.pi * a.vib_rate * (t - t_on))
        return c

    k = 0
    while k < len(notes):
        on, off, leg, p, ch = notes[k]
        if on < cur:
            st['dropped'] += 1; k += 1; continue
        nxt = next((n for n in notes[k + 1:] if n[0] >= on + MIN_SLUR), None)
        slur = bool(nxt) and a.legato != 'off' and nxt[3] != p and (
            leg if a.legato == 'auto' else nxt[0] <= off + 1)
        if slur:
            end = nxt[0]
        else:
            end = off
            if nxt:
                end = min(end, nxt[0] - (GAP_SAME if nxt[3] == p else GAP_DIFF))
            end = max(end, on + 1)
        rest(on - cur)
        t_on = t_of_frame(on)
        tg = [target(f, p, ch, t_on) for f in range(on, end)]
        fb, fm, fc = choose_fingering(min(tg), max(tg), tg[0], prev, on == cur and breath > 0, tuned)
        btns = [fb, *fm]
        f = on
        for c in tg:
            y = cents_to_y(c - fc)
            last = steps[-1] if steps else None
            if last and last['buttons'] == btns and last['left_stick'][1] == y and last['frames'] < MAX_STEP_FRAMES:
                last['frames'] += 1
            else:
                steps.append({'buttons': btns, 'left_stick': [0, y], 'frames': 1})
            breath += 1; f += 1
        if slur:
            st['slurs'] += 1
        prev = (fb, fm)
        cur = end
        k += 1
    rest(10)
    steps = apply_breaths(steps, BREATH, max(4, round(4 * k30)), int(75 * k30), st)
    return steps, st, cur + 10


# ---------------------------------------------------------------- playback
def send(steps, timeout):
    req = json.dumps({'id': int(time.time()), 'method': 'input_sequence',
                      'params': {'controller': 'player1', 'steps': steps}}) + '\n'
    with socket.create_connection((HOST, PORT), timeout=10) as s:
        s.settimeout(timeout)
        s.sendall(req.encode())
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf or b'{}')


def resolve(arg):
    p = Path(arg)
    if p.is_file():
        return p
    hits = sorted(f for f in MIDI_DIR.glob('*') if f.suffix.lower() in ('.mid', '.midi', '.kar')
                  and arg.lower() in f.name.lower())
    if not hits:
        sys.exit(f'No MIDI matching "{arg}" in {MIDI_DIR}')
    if len(hits) > 1:
        print('Several matches, using the first:', *[f'  {h.name}' for h in hits], sep='\n')
    return hits[0]


def main():
    ap = argparse.ArgumentParser(description="Play a MIDI melody on Link's Ocarina.")
    ap.add_argument('midi', nargs='?')
    ap.add_argument('--list', action='store_true', help='show tracks and exit')
    ap.add_argument('--track', type=int, help='track number from --list (default: auto)')
    ap.add_argument('--start', type=float, default=0.0, help='start this many seconds into the MIDI')
    ap.add_argument('--length', type=float, help='play only this many seconds')
    ap.add_argument('--speed', type=float, default=1.0, help='tempo multiplier (2 = twice as fast)')
    ap.add_argument('--transpose', type=int, help='semitones (default: best octave shift)')
    ap.add_argument('--wide', action='store_true', help='also use predicted B4/F6 edges')
    ap.add_argument('--legato', choices=['auto', 'all', 'off'], default='auto',
                    help='auto: slur notes the MIDI connects; all: slur any touching notes; off: always re-attack')
    ap.add_argument('--tune', choices=['tuned', 'raw'], default='tuned',
                    help='tuned: correct each note with the stick; raw: the instrument\'s own tuning')
    ap.add_argument('--vibrato', type=float, default=0.0, help='add vibrato of this many cents to held notes')
    ap.add_argument('--vib-rate', type=float, default=5.0, help='vibrato rate in Hz (30 FPS input limits this)')
    ap.add_argument('--bend-range', type=float, default=2.0, help='MIDI pitch-wheel range in semitones')
    ap.add_argument('--fps', type=float, default=30.0)
    ap.add_argument('--delay', type=float, default=5.0, help='countdown seconds before playing')
    ap.add_argument('--dry-run', action='store_true', help='send nothing')
    a = ap.parse_args()

    if not a.midi:
        files = sorted(f.name for f in MIDI_DIR.glob('*') if f.suffix.lower() in ('.mid', '.midi', '.kar'))
        print(f'{MIDI_DIR}\n' + ('\n'.join(f'  {f}' for f in files) or '  (no MIDI files yet)') + '\n  demo (built in)')
        return

    if a.midi.lower() == 'demo':
        label, data = 'demo', make_demo()
    else:
        path = resolve(a.midi); label, data = path.name, path.read_bytes()
        side = path.with_name(path.stem + '.ocarina.json')       # per-song defaults written by the scout
        if side.is_file():
            for key, val in json.loads(side.read_text()).items():
                if getattr(a, key, None) is None:
                    setattr(a, key, val)
    div, tempos, tracks = parse_midi(data, label)
    rows = describe(tracks)
    print(f'{label}: {len(tracks)} tracks, {len(tempos)} tempo events, '
          f'first tempo {60e6 / (sorted(tempos)[0][1] if tempos else 500000):.1f} BPM')
    for k, name, cnt, lo, hi, avg, chans, drum in rows:
        tr = tracks[k]
        print(f'  [{k}] {name[:30]:30} {cnt:6} notes  {nn(lo)}-{nn(hi)}  ch {",".join(map(str, chans))}'
              + ('  (drums)' if drum else '') + ('  bends' if tr['bends'] else '') + ('  modwheel' if tr['mods'] else ''))
    if a.list:
        return

    tn = a.track if a.track is not None else auto_track(rows)
    if tn < 0 or tn >= len(tracks) or not tracks[tn]['notes']:
        sys.exit(f'Track {tn} has no notes.')
    tr = tracks[tn]
    t2s = tick_to_sec(div, tempos)
    bend = Curve([(t2s(t), ch, v) for t, ch, v in tr['bends']], 0)
    mod = Curve([(t2s(t), ch, v) for t, ch, v in tr['mods']], 0)
    tol = 0.02  # seconds: notes this close count as connected
    mel = [(t2s(s), t2s(cut), t2s(e), p, ch) for s, cut, e, p, ch in skyline(tr['notes'])]
    t0, t1 = a.start, a.start + a.length if a.length else float('inf')
    mel = [n for n in mel if t0 <= n[0] < t1]
    if not mel:
        sys.exit('No notes in that time window.')
    first = mel[0][0]
    lo, hi = (71, 89) if a.wide else (72, 88)
    shift, folded, pitches = fit_range([n[3] for n in mel], lo, hi, a.transpose)
    notes = []
    for k, ((s, cut, e, _, ch), q) in enumerate(zip(mel, pitches)):
        nxt_s = mel[k + 1][0] if k + 1 < len(mel) else None
        leg = nxt_s is not None and e >= nxt_s - tol
        cut = min(cut, t1)
        notes.append((round((s - first) / a.speed * a.fps), round((cut - first) / a.speed * a.fps), leg, q, ch))
    t_of_frame = lambda f: first + f / a.fps * a.speed
    steps, st, total = build_steps(notes, a.fps, a, bend, mod, t_of_frame)

    print(f'Track [{tn}] {tr["name"] or "-"}: {len(notes)} melody notes, transpose {shift:+d}, {folded} octave-folded, '
          f'{st["dropped"]} dropped, {st["slurs"]} slurred, {st["breaths"]} breaths added, {st["split"]} long-note splits, '
          f'tune {a.tune}, {"bends " if bend.active() else ""}{"modwheel " if mod.active() else ""}'
          f'{len(steps)} steps, {total} frames = {total / a.fps:.1f} s at {a.fps:g} FPS')
    if a.dry_run:
        print('First notes:', ' '.join(nn(n[3]) for n in notes[:32]))
        return

    for n in range(int(a.delay), 0, -1):
        print(f'  {n}...', end='\r', flush=True); time.sleep(1)
    print('Playing.   ')
    t = time.time()
    for k in range(0, len(steps), CHUNK_STEPS):
        part = steps[k:k + CHUNK_STEPS]
        r = send(part, timeout=sum(s['frames'] for s in part) / a.fps * 3 + 30)
        if 'error' in r or 'result' not in r:
            sys.exit(f'Server: {r}')
    print(f'Done in {time.time() - t:.1f} s.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped. Connection closed; the server releases input.')
    except ConnectionRefusedError:
        sys.exit('The game is not connected: start the emulator with EDEN_NX2_DEBUG_SERVER=127.0.0.1:6545 (see README).')
