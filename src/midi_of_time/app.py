#!/usr/bin/env python3
"""MIDI of Time - pick a MIDI, press PLAY, and Link plays it on his own Ocarina in the Ocarina of Time remake.

Talks to a compatible emulator's debug server (see README: COMPATIBILITY). Portable: settings, logs and
your Songs folder live next to the program; nothing is installed. Your MIDI files are only read.
"""
import bisect, json, os, queue, secrets, shutil, socket, subprocess, sys, threading, time, traceback, types
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from . import engine as P, smart as S, remote as R, backends as B, padwatch as PW
    from . import __version__
except ImportError:                       # run as a plain script
    import engine as P, smart as S, remote as R, backends as B, padwatch as PW
    from __init__ import __version__

APP_NAME = 'MIDI of Time'
FROZEN = getattr(sys, 'frozen', False)
BASE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[2]
ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets' if FROZEN else Path(__file__).resolve().parent / 'assets'


def _writable(d):
    try:
        d.mkdir(parents=True, exist_ok=True)
        t = d / '.write-test'; t.write_text('x'); t.unlink()
        return True
    except OSError:
        return False


# Portable layout next to the program; falls back to %LOCALAPPDATA% if that folder is read-only (e.g. Program Files).
_root = BASE if _writable(BASE / 'data') else Path(os.environ.get('LOCALAPPDATA', Path.home())) / APP_NAME
MIDI_DIR = _root / 'Songs'
APP_DIR = _root / 'data'
STATE_FILE = APP_DIR / 'settings.json'
LOG_FILE = APP_DIR / 'midi-of-time.log'
FPS = 30.0                      # updated from the game's reported frame rate (30 or 60 mode)
CHUNK_MIN_FRAMES = 240          # send in pieces of at least ~8 s, always cut at a rest
NOWIN = 0x08000000 if os.name == 'nt' else 0   # CREATE_NO_WINDOW
BACKEND = B.BACKENDS[0]          # the connection layer; see backends.py
APP_DIR.mkdir(parents=True, exist_ok=True); MIDI_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except OSError:
        pass


def first_run_files():
    """Songs folder with a readme and an original demo song (generated, no copyrighted music)."""
    readme = MIDI_DIR / 'Put your MIDI files here.txt'
    if not readme.exists():
        try:
            readme.write_text('Copy .mid files into this folder and they appear under "My songs".\n'
                              'You can also play any MIDI with "Open a MIDI file..." or search a MIDI folder.\n', encoding='utf-8')
        except OSError:
            pass
    demo = MIDI_DIR / 'MIDI of Time - Demo.mid'
    if not demo.exists():
        try:
            demo.write_bytes(P.make_demo())
        except OSError:
            pass


def find_everything():
    """Everything's command-line tool (es.exe), if installed - makes library search instant. Optional."""
    for c in (shutil.which('es'), shutil.which('es.exe')):
        if c:
            return c
    for d in (os.environ.get('ProgramFiles', r'C:\Program Files'), os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')):
        p = Path(d) / 'Everything' / 'es.exe'
        if p.is_file():
            return str(p)
    return None


# ------------------------------------------------------------------ state
DEFAULT_STATE = {'favorites': [], 'recent': [], 'library': '', 'emulator': '', 'game': '', 'remote': False,
                 'remote_port': 8765, 'sort': 'name', 'auto_next': False}


def load_state():
    try:
        s = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return {**DEFAULT_STATE, **s}
    except (OSError, ValueError):
        return dict(DEFAULT_STATE)


def save_state(s):
    try:
        STATE_FILE.write_text(json.dumps(s, indent=1), encoding='utf-8')
    except OSError as e:
        log(f'state save failed: {e}')


# ------------------------------------------------------------------ engine glue (no engine changes)
def analyze(path):
    data = Path(path).read_bytes()
    try:
        div, tempos, tracks = P.parse_midi(data, Path(path).name)
    except SystemExit as e:
        raise ValueError(str(e))
    rows = P.describe(tracks)
    if not rows:
        raise ValueError('This MIDI file has no notes.')
    side, defaults = Path(path).with_name(Path(path).stem + '.ocarina.json'), {}
    if side.is_file():
        try:
            defaults = json.loads(side.read_text())
        except ValueError:
            pass
    tagged = next((k for k, tr in enumerate(tracks) if tr['name'].strip().lower() == '[link]' and tr['notes']), None)
    try:
        auto = tagged if tagged is not None else defaults.get('track', P.auto_track(rows))
    except SystemExit:
        raise ValueError('This MIDI only has drums - nothing for Link to play.')
    return {'path': Path(path), 'div': div, 'tempos': tempos, 'tracks': tracks, 'rows': rows,
            'auto': auto, 'defaults': defaults, 'tagged': tagged}


def arrange(song, o):
    """Same pipeline as the player's main(); returns steps, stats, warnings."""
    tracks, t2s = song['tracks'], P.tick_to_sec(song['div'], song['tempos'])
    tn = o['track']
    tr = tracks[tn]
    a = types.SimpleNamespace(tune=o['tune'], legato=o['legato'], vibrato=o['vibrato'], vib_rate=5.0,
                              bend_range=2.0, speed=o['speed'])
    smart = o.get('mode') == 'smart'
    src = tracks if smart else [tr]
    bend = P.Curve([(t2s(t), ch, v) for x in src for t, ch, v in x['bends']], 0)
    mod = P.Curve([(t2s(t), ch, v) for x in src for t, ch, v in x['mods']], 0)
    segs = [(0.0, tn)]
    if smart:
        line, segs = S.follow_melody(tracks, t2s, P.skyline, tn)
        sky = P.skyline(line) if line else P.skyline(tr['notes'])
    else:
        sky = P.skyline(tr['notes'])
    fill = o.get('fill')
    if fill is not None and fill != tn and 0 <= fill < len(tracks):
        # add the second part's notes only where the main part is silent
        starts, ends, run = [n[0] for n in sky], [], 0
        for n in sky:
            run = max(run, n[2]); ends.append(run)
        extra = []
        for s, cut, e, p, ch in P.skyline(tracks[fill]['notes']):
            i = bisect.bisect_right(starts, s) - 1
            if i < 0 or ends[i] <= s:
                extra.append((s, e, p, ch))
        if extra:
            sky = P.skyline(sorted([(s, e, p, ch) for s, cut, e, p, ch in sky] + extra))
    mel = [(t2s(s), t2s(cut), t2s(e), p, ch) for s, cut, e, p, ch in sky]
    mel = [n for n in mel if n[0] >= o['start']]
    if not mel:
        raise ValueError('No notes after that start point.')
    first = mel[0][0]
    if o['transpose'] is None:
        pitches, folded = S.phrase_fit(mel, 72, 88)          # whole phrases move by octaves
    else:
        shift, folded, pitches = P.fit_range([n[3] for n in mel], 72, 88, o['transpose'])
    notes = []
    for k, ((s, cut, e, _, ch), q) in enumerate(zip(mel, pitches)):
        nxt = mel[k + 1][0] if k + 1 < len(mel) else None
        notes.append((round((s - first) / a.speed * FPS), round((cut - first) / a.speed * FPS),
                      nxt is not None and e >= nxt - 0.02, q, ch))
    steps, st, total = P.build_steps(notes, FPS, a, bend, mod, lambda f: first + f / FPS * a.speed)
    n, warn = len(notes), []
    poly = 0 if smart else 1 - len(sky) / max(1, len(tr['notes']))
    if poly > 0.3:
        warn.append('This part has chords - Link plays the top note of each.')
    if folded / n > 0.15:
        warn.append(f'{folded / n:.0%} of the notes are outside Link\'s range and move by an octave, so some runs may jump.')
    if st['dropped']:
        warn.append(f'{st["dropped"]} notes are too fast for the game and are skipped.')
    if total / FPS > 480:
        warn.append(f'Long song ({total / FPS / 60:.0f} min).')
    seg_frames = [(max(0, round((t - first) / a.speed * FPS)), k) for t, k in segs]
    return steps, total, warn, seg_frames


def resume_chunks(steps, frame):
    """Chunks for resuming at `frame`: restart from the beginning of the note (or rest) playing at that moment."""
    t = 0
    for k, st in enumerate(steps):
        if t + st['frames'] > frame:
            return [(start + t, part) for start, part in split_chunks(steps[k:])]
        t += st['frames']
    return split_chunks(steps)


def split_chunks(steps):
    """Pieces of <=1000 steps (server limit), cut at rests so a seam never interrupts a held note."""
    out, cur, frames, start = [], [], 0, 0
    for s in steps:
        cur.append(s); frames += s['frames']
        if (not s['buttons'] and frames >= CHUNK_MIN_FRAMES) or len(cur) >= 1000:
            out.append((start, cur)); start += frames; cur, frames = [], 0
    if cur:
        out.append((start, cur))
    return out


def release_all():
    BACKEND.release()


# Emulator program names. Fritchii v6+ runs as fritchii.exe and keeps a small lichii.exe forwarder next to it;
# Fritchii v5.x and other Lichii builds run as lichii.exe.
KNOWN_EMULATOR_EXES = ('fritchii.exe', 'lichii.exe')


def game_running(exe_name=''):
    names = {n.lower() for n in (exe_name, *KNOWN_EMULATOR_EXES) if n}
    try:
        out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True,
                             text=True, creationflags=NOWIN, timeout=5).stdout.lower()
        return any(f'"{n}"' in out for n in names)
    except (OSError, subprocess.SubprocessError):
        return False


def friendly(err):
    e = str(err)
    if 'not connected' in e or 'player 1' in e.lower():
        return 'The game didn\'t accept the input. Make sure your controller is connected as Player 1.'
    if (isinstance(err, (ConnectionError, TimeoutError)) or 'refused' in e.lower() or 'no reply' in e.lower()
            or 'forcibly closed' in e.lower() or 'expecting value' in e.lower()):
        return 'Lost the connection to the game (was the emulator closed?).'
    if 'steps must be' in e or 'unknown' in e.lower():
        return 'This emulator build answered but did not accept the input. It may not be a compatible version (see README).'
    return 'Something went wrong while playing. Details are in the log (Advanced).'


# ------------------------------------------------------------------ playback thread
class Playback(threading.Thread):
    def __init__(self, chunks, first_chunk, ui):
        super().__init__(daemon=True)
        self.chunks, self.i, self.ui = chunks, first_chunk, ui
        self.halt, self.call, self.chunk_t0, self.error = False, None, None, None
        self.watch = None
        self.trace = []   # (chunk index, planned start frame, frames, first_present, elapsed_s, wall_send)

    def position(self):
        if self.chunk_t0 is None or self.i >= len(self.chunks):
            return None
        start, part = self.chunks[self.i]
        span = sum(s['frames'] for s in part)
        return start + min(span, (time.time() - self.chunk_t0) * FPS)

    def run(self):
        try:
            if self.ui.state.get('pad_stop', True):
                self.watch = PW.Watch(self._pad_trip)
                log('controller kill switch: ' + ('on' if self.watch.ok else 'no XInput controller found, off'))
            while self.i < len(self.chunks) and not self.halt:
                start, part = self.chunks[self.i]
                span = sum(s['frames'] for s in part)
                self.call = BACKEND.start_sequence(part)
                self.chunk_t0 = self.call.started
                res = self.call.wait(span / FPS * 3 + 30)
                self.call = None
                if self.halt or res is None:
                    break
                self.trace.append((self.i, start, span, res.get('first_present'), res.get('elapsed_s'), self.chunk_t0))
                self.i += 1
        except Exception as e:  # noqa: BLE001 - reported to the user in plain words
            if not self.halt:
                self.error = e; log('playback error: ' + ''.join(traceback.format_exception(e)))
        finally:
            if self.watch:
                self.watch.stop()
            release_all()
            self.ui.after(0, self.ui.on_playback_end, self)

    def _pad_trip(self, what):
        log(f'controller kill switch: stopped because {what} was used')
        self.stop()

    def stop(self):
        self.halt = True
        c = self.call
        if c:
            c.cancel()


# ------------------------------------------------------------------ UI
BG, PANEL, INK, GOLD, DIM, GREEN, RED, AMBER = '#17140f', '#231e16', '#efe3c2', '#d4a72c', '#9c8f73', '#5fa35a', '#c4553f', '#e0a43a'


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'{APP_NAME} {__version__}'); self.configure(bg=BG); self.geometry('1000x660'); self.minsize(900, 620)
        try:
            self.iconbitmap(default=str(ASSETS / 'ocarina-midi.ico'))
        except tk.TclError:
            pass
        self.state = load_state()
        self.song, self.opts, self.play, self.paused_at, self.prepared = None, None, None, None, None
        self.segs, self.items, self.want_play = [], [], None
        self.connected, self.view, self.sticky_until, self.compat, self.compat_said = False, 'all', 0, None, None
        self.library_hits = []
        self.remote_q, self.total, self.pending = queue.Queue(), 0, None
        if not self.state.get('remote_pin'):
            self.state['remote_pin'] = f'{secrets.randbelow(1000000):06d}'; save_state(self.state)
        first_run_files()
        self._style(); self._build(); self.refresh_list(); self.start_remote()
        self.pad = PW.Shortcuts(lambda k: self.after(0, self.pad_key, k))
        self.after(300, self.poll_status); self.after(100, self.tick); self.after(100, self.drain_remote)
        self.protocol('WM_DELETE_WINDOW', self.on_close)

    # ---------- look
    def _style(self):
        st = ttk.Style(self); st.theme_use('clam')
        st.configure('TProgressbar', troughcolor=PANEL, background=GOLD, bordercolor=PANEL, lightcolor=GOLD, darkcolor=GOLD)
        st.configure('TCombobox', fieldbackground=PANEL, background=PANEL, foreground=INK, arrowcolor=GOLD)
        self.option_add('*TCombobox*Listbox.background', PANEL); self.option_add('*TCombobox*Listbox.foreground', INK)

    def btn(self, parent, text, cmd, big=False, color=None):
        b = tk.Button(parent, text=text, command=cmd, bg=color or PANEL, fg=BG if color else INK, activebackground=GOLD,
                      activeforeground=BG, relief='flat', bd=0, cursor='hand2',
                      font=('Segoe UI', 22 if big else 11, 'bold' if big else 'normal'), padx=18, pady=10 if big else 5)
        return b

    def _build(self):
        top = tk.Frame(self, bg=BG); top.pack(fill='x', padx=18, pady=(14, 6))
        tk.Label(top, text=APP_NAME, bg=BG, fg=GOLD, font=('Georgia', 24, 'bold')).pack(side='left')
        self.status_dot = tk.Label(top, text='●', bg=BG, fg=DIM, font=('Segoe UI', 16)); self.status_dot.pack(side='right')
        self.status_lbl = tk.Label(top, text='Checking for the game…', bg=BG, fg=INK, font=('Segoe UI', 12))
        self.status_lbl.pack(side='right', padx=6)
        self.start_btn = self.btn(top, 'Start game', self.start_game); self.start_btn.pack(side='right', padx=10)

        body = tk.Frame(self, bg=BG); body.pack(fill='both', expand=True, padx=18, pady=6)
        body.columnconfigure(0, weight=3); body.columnconfigure(1, weight=2, minsize=370); body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=BG); left.grid(row=0, column=0, sticky='nsew')
        right = tk.Frame(body, bg=PANEL); right.grid(row=0, column=1, sticky='nsew', padx=(14, 0))
        right.bind('<Configure>', self.on_resize_right)

        # library side
        srow = tk.Frame(left, bg=BG); srow.pack(fill='x')
        self.search = tk.StringVar(); self.search.trace_add('write', lambda *_: self.refresh_list())
        e = tk.Entry(srow, textvariable=self.search, bg=PANEL, fg=INK, insertbackground=INK, relief='flat',
                     font=('Segoe UI', 13)); e.pack(side='left', fill='x', expand=True, ipady=6)
        e.bind('<Return>', lambda _: self.search_library())
        self.btn(srow, 'Search MIDI folder', self.search_library).pack(side='left', padx=(8, 0))
        tabs = tk.Frame(left, bg=BG); tabs.pack(fill='x', pady=(8, 4))
        self.tab_btns = {}
        for key, label in (('all', 'My songs'), ('fav', '★ Favorites'), ('recent', 'Recent'), ('lib', 'Library results')):
            b = tk.Button(tabs, text=label, command=lambda k=key: self.set_view(k), relief='flat', bd=0, cursor='hand2',
                          font=('Segoe UI', 10), padx=10, pady=3)
            b.pack(side='left', padx=(0, 6)); self.tab_btns[key] = b
        lf = tk.Frame(left, bg=PANEL); lf.pack(fill='both', expand=True)
        self.listbox = tk.Listbox(lf, bg=PANEL, fg=INK, selectbackground=GOLD, selectforeground=BG, relief='flat',
                                  highlightthickness=0, font=('Segoe UI', 13), activestyle='none')
        sb = tk.Scrollbar(lf, command=self.listbox.yview); self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side='left', fill='both', expand=True, padx=6, pady=6); sb.pack(side='right', fill='y')
        self.listbox.bind('<<ListboxSelect>>', lambda _: self.on_select())
        self.listbox.bind('<Double-Button-1>', lambda _: self.on_play())
        brow = tk.Frame(left, bg=BG); brow.pack(fill='x', pady=(6, 0))
        self.fav_btn = self.btn(brow, '☆ Favorite', self.toggle_fav); self.fav_btn.pack(side='left')
        self.btn(brow, 'Open a MIDI file…', self.open_file).pack(side='left', padx=8)
        self.sort_btn = self.btn(brow, 'Sort: Name', self.toggle_sort); self.sort_btn.pack(side='right')
        self.add_btn = self.btn(brow, 'Add to My songs', self.add_to_songs)

        # now-playing side
        self.title_lbl = tk.Label(right, text='Pick a song', bg=PANEL, fg=INK, font=('Georgia', 17, 'bold'),
                                  wraplength=380, justify='left'); self.title_lbl.pack(anchor='w', padx=18, pady=(18, 4))
        self.info_lbl = tk.Label(right, text='', bg=PANEL, fg=DIM, font=('Segoe UI', 10), wraplength=380, justify='left')
        self.info_lbl.pack(anchor='w', padx=18)
        self.warn_lbl = tk.Label(right, text='', bg=PANEL, fg=AMBER, font=('Segoe UI', 10), wraplength=380, justify='left')
        self.warn_lbl.pack(anchor='w', padx=18, pady=(6, 0))
        mrow = tk.Frame(right, bg=PANEL); mrow.pack(fill='x', padx=18, pady=(14, 0))
        self.mode_var = tk.StringVar(value='smart')
        for val, label in (('smart', 'Smart: follows the tune'), ('part', 'One part')):
            tk.Radiobutton(mrow, text=label, value=val, variable=self.mode_var, command=self.on_mode, bg=PANEL, fg=INK,
                           selectcolor=BG, activebackground=PANEL, activeforeground=GOLD, font=('Segoe UI', 10)
                           ).pack(side='left', padx=(0, 10))
        self.play_btn = self.btn(right, '▶  PLAY', self.on_play, big=True, color=GOLD)
        self.play_btn.pack(fill='x', padx=18, pady=(10, 8))
        row = tk.Frame(right, bg=PANEL); row.pack(fill='x', padx=18)
        self.pause_btn = self.btn(row, '❚❚  Pause', self.on_pause); self.pause_btn.pack(side='left', expand=True, fill='x')
        self.stop_btn = self.btn(row, '■  Stop', self.on_stop); self.stop_btn.pack(side='left', expand=True, fill='x', padx=(8, 0))
        self.progress = ttk.Progressbar(right, maximum=1000); self.progress.pack(fill='x', padx=18, pady=(14, 2))
        trow = tk.Frame(right, bg=PANEL); trow.pack(fill='x', padx=18)
        self.follow_lbl = tk.Label(trow, text='', bg=PANEL, fg=GOLD, font=('Segoe UI', 10)); self.follow_lbl.pack(side='left')
        self.time_lbl = tk.Label(trow, text='0:00 / 0:00', bg=PANEL, fg=DIM, font=('Segoe UI', 10))
        self.time_lbl.pack(side='right')
        self.auto_next = tk.BooleanVar(value=self.state.get('auto_next', False))
        tk.Checkbutton(right, text='Auto-play the next song', variable=self.auto_next,
                       command=lambda: (self.state.update(auto_next=self.auto_next.get()), save_state(self.state)),
                       bg=PANEL, fg=INK, selectcolor=BG, activebackground=PANEL, activeforeground=GOLD,
                       font=('Segoe UI', 10)).pack(anchor='w', padx=18, pady=(8, 0))
        self.msg_lbl = tk.Label(right, text='Before you press Play: take the Ocarina out.\nWhile a song plays: D-pad up = pause/resume, down = stop.',
                                bg=PANEL, fg=INK, font=('Segoe UI', 10), justify='left', wraplength=380)
        self.msg_lbl.pack(anchor='w', padx=18, pady=(14, 0))
        brow2 = tk.Frame(right, bg=PANEL); brow2.pack(side='bottom', fill='x', padx=18, pady=(4, 14))
        self.btn(brow2, 'Advanced…', self.open_advanced).pack(side='right')
        self.remote_lbl = tk.Label(right, text='', bg=PANEL, fg=DIM, font=('Segoe UI', 9), justify='left', anchor='w')
        self.remote_lbl.pack(side='bottom', fill='x', padx=18)
        self.update_buttons()

    # ---------- song list
    def my_songs(self):
        try:
            return sorted((f for f in MIDI_DIR.iterdir() if f.suffix.lower() in ('.mid', '.midi', '.kar')),
                          key=lambda f: f.stem.lower())
        except OSError:
            return []

    def set_view(self, key):
        self.view = key; self.refresh_list()

    def toggle_sort(self):
        self.state['sort'] = 'name' if self.state.get('sort') == 'size' else 'size'
        save_state(self.state); self.refresh_list()

    def refresh_list(self):
        for k, b in self.tab_btns.items():
            b.configure(bg=GOLD if k == self.view else PANEL, fg=BG if k == self.view else INK)
        q = self.search.get().lower().strip()
        if self.view == 'all':
            files = self.my_songs()
        elif self.view == 'fav':
            files = [Path(p) for p in self.state['favorites'] if Path(p).is_file()]
        elif self.view == 'recent':
            files = [Path(p) for p in self.state['recent'] if Path(p).is_file()]
        else:
            files = self.library_hits
        if q and self.view != 'lib':
            files = [f for f in files if all(w in f.stem.lower() for w in q.split())]
        by_size = self.state.get('sort') == 'size'
        if by_size:
            files = sorted(files, key=lambda f: -fsize(f))
        self.sort_btn.config(text='Sort: Size' if by_size else 'Sort: Name')
        self.items = files
        self.listbox.delete(0, 'end')
        for f in files:
            star = '★ ' if str(f) in self.state['favorites'] else '   '
            extra = (f'   ·  {kb(fsize(f))}' if by_size else '') + (f'   ·  {f.parent.name}' if self.view == 'lib' else '')
            self.listbox.insert('end', star + f.stem + extra)
        if self.view == 'lib':
            self.add_btn.pack(side='left')
        else:
            self.add_btn.pack_forget()

    def search_library(self):
        q = self.search.get().strip()
        if not self.state.get('library') or not Path(self.state['library']).is_dir():
            d = filedialog.askdirectory(title='Choose the folder that holds your MIDI files')
            if not d:
                return
            self.state['library'] = d; save_state(self.state); self.lib_index = None
        if not q:
            self.say('Type part of a song name, then press Search MIDI folder.'); return
        self.say('Searching your MIDI folder…')
        threading.Thread(target=lambda: self.after(0, self.show_hits, *self.library_search(q)), daemon=True).start()

    def library_search(self, q, limit=300):
        """Returns (paths, error). Uses Everything if installed (instant), otherwise scans the folder once and caches it."""
        lib, words = self.state.get('library') or '', [w.lower() for w in q.split()]
        try:
            es = find_everything()
            if es:
                out = subprocess.run([es, '-path', lib, '-n', str(limit), 'ext:mid;midi', *q.split()], capture_output=True,
                                     text=True, encoding='utf-8', errors='replace', creationflags=NOWIN, timeout=20).stdout
                files = [Path(l.strip()) for l in out.splitlines() if l.strip()]
                if files or not out.strip():
                    return self._dedupe(files, limit), None
            if getattr(self, 'lib_index', None) is None or self.lib_index[0] != lib:
                idx = []
                for dp, _, fn in os.walk(lib):
                    idx += [os.path.join(dp, f) for f in fn if f.lower().endswith(('.mid', '.midi', '.kar'))]
                self.lib_index = (lib, idx)
            hits = [Path(p) for p in self.lib_index[1] if all(w in Path(p).name.lower() for w in words)]
            return self._dedupe(hits, limit), None
        except Exception as e:  # noqa: BLE001
            log('library search failed: ' + repr(e))
            return [], 'Couldn\'t search that folder.'

    @staticmethod
    def _dedupe(files, limit):
        seen, out = set(), []
        for p in files:
            try:
                key = (p.name.lower(), p.stat().st_size)
            except OSError:
                continue
            if key not in seen:
                seen.add(key); out.append(p)
            if len(out) >= limit:
                break
        return out

    def show_hits(self, hits, err):
        self.library_hits = hits; self.view = 'lib'
        self.refresh_list()
        self.say(err or (f'{len(hits)} matching MIDI files in your library. Pick one to play it straight from there.'
                         if hits else 'Nothing in your library matched that.'))

    def selected_path(self):
        sel = self.listbox.curselection()
        return self.items[sel[0]] if sel and sel[0] < len(self.items) else None

    def on_select(self):
        p = self.selected_path()
        if p:
            self.load_song(p)

    def load_song(self, p, autoplay=False):
        if self.play:
            self.say('Stop the current song first, then pick the next one.'); return
        self.pending = p
        if autoplay:
            self.want_play = p
        if p in self.items:
            i = self.items.index(p); self.listbox.selection_clear(0, 'end'); self.listbox.selection_set(i); self.listbox.see(i)
        self.title_lbl.config(text=p.stem); self.info_lbl.config(text='Reading the song…'); self.warn_lbl.config(text='')
        self.song, self.prepared = None, None
        self.fav_btn.config(text='★ Favorite' if str(p) in self.state['favorites'] else '☆ Favorite')

        def work():
            try:
                song = analyze(p)
                opts = {'track': song['auto'], 'tune': 'tuned', 'legato': 'auto', 'vibrato': 0.0, 'speed': 1.0,
                        'transpose': song['defaults'].get('transpose'), 'start': float(song['defaults'].get('start', 0.0)),
                        'fill': song['defaults'].get('fill'),
                        'mode': song['defaults'].get('mode', 'part' if song['tagged'] is not None else 'smart')}
                steps, total, warn, segs = arrange(song, opts)
                self.after(0, self.song_ready, p, song, opts, (steps, segs), total, warn, None)
            except Exception as e:  # noqa: BLE001
                log(f'analyze {p}: ' + ''.join(traceback.format_exception(e)))
                self.after(0, self.song_ready, p, None, None, None, 0, [], e)
        threading.Thread(target=work, daemon=True).start()

    def song_ready(self, p, song, opts, steps, total, warn, err):
        if self.pending != p:
            return
        if err:
            self.info_lbl.config(text=''); self.warn_lbl.config(text=f'This file can\'t be played: {err}' if isinstance(err, ValueError)
                                                                else 'This file can\'t be played (it may be damaged).')
            self.update_buttons(); return
        steps, self.segs = steps
        self.song, self.opts, self.prepared, self.paused_at, self.total = song, opts, (steps, total), None, total
        row = next((r for r in song['rows'] if r[0] == opts['track']), None)
        if opts.get('mode') == 'smart':
            n = len({k for _, k in self.segs})
            part = f'follows the tune across {n} part{"s" if n != 1 else ""}'
        else:
            part = f'melody from track {opts["track"]}' + (f' "{row[1]}"' if row and row[1] != '-' else '')
        self.mode_var.set(opts.get('mode', 'smart'))
        nr = len(song["rows"])
        self.info_lbl.config(text=f'{fmt(total / FPS)}  ·  {part}  ·  {nr} part{"s" if nr != 1 else ""} in this MIDI')
        self.warn_lbl.config(text='\n'.join(warn))
        self.progress['value'] = 0; self.time_lbl.config(text=f'0:00 / {fmt(total / FPS)}'); self.follow_lbl.config(text='')
        self.update_buttons()
        if getattr(self, 'want_play', None) == p:
            self.want_play = None; self.after(800, self.on_play)

    def reprepare(self):
        if not self.song:
            return
        try:
            steps, total, warn, segs = arrange(self.song, self.opts)
            self.song_ready(self.song['path'], self.song, self.opts, (steps, segs), total, warn, None)
        except Exception as e:  # noqa: BLE001
            self.warn_lbl.config(text=f'Those settings don\'t work for this song: {e}')

    # ---------- favorites / files
    def toggle_fav(self):
        p = self.selected_path() or (self.song and self.song['path'])
        if not p:
            return
        favs, k = self.state['favorites'], str(p)
        favs.remove(k) if k in favs else favs.append(k)
        save_state(self.state); self.refresh_list()
        self.fav_btn.config(text='★ Favorite' if k in favs else '☆ Favorite')

    def open_file(self):
        f = filedialog.askopenfilename(title='Open a MIDI file', initialdir=self.state['library'],
                                       filetypes=[('MIDI files', '*.mid *.midi *.kar')])
        if f:
            self.library_hits = [Path(f)]; self.view = 'lib'; self.refresh_list()
            self.listbox.selection_set(0); self.on_select()

    def add_to_songs(self):
        p = self.selected_path()
        if not p:
            return
        dest = MIDI_DIR / p.name
        if dest.exists():
            self.say('That song is already in My songs.'); return
        try:
            import shutil
            shutil.copy2(p, dest)
            if self.song and self.song['path'] == p:
                (MIDI_DIR / (p.stem + '.ocarina.json')).write_text(json.dumps({'track': self.opts['track'],
                                                                                'mode': self.opts.get('mode', 'smart')}))
            self.say(f'Added "{p.stem}" to My songs (copied - your library is unchanged).')
        except OSError as e:
            log(f'add failed: {e}'); self.say('Couldn\'t copy that file.')

    # ---------- playback
    def on_play(self):
        if self.play or not self.prepared:
            return
        if not self.connected:
            if self.compat is not None and self.compat.state == 'incompatible':
                self.say(self.compat.message); return
            self.say('The game isn\'t connected yet. Press Start game, or wait for the status to turn green.'); return
        steps, total = self.prepared
        pf = getattr(self, 'pause_frame', None) if self.paused_at is not None else None
        self.paused_at, self.pause_frame = None, None
        self.chunks = resume_chunks(steps, pf) if pf else split_chunks(steps)
        self.total = total
        self.play = Playback(self.chunks, 0, self); self.play.start()
        p = str(self.song['path'])
        rec = [x for x in self.state['recent'] if x != p]; self.state['recent'] = [p] + rec[:19]; save_state(self.state)
        self.set_status('Playing', GOLD); self.say('Playing. D-pad up = pause, D-pad down = stop.'); self.update_buttons()

    def pad_key(self, key):
        """Controller shortcuts, only while a song is playing or paused (the Ocarina is out then).
        D-pad up = pause / resume, D-pad down = stop. They never START a song: tested 2026-11-15, D-pad up
        with the Ocarina put away sent the song into normal gameplay. D-pad left/right while paused means
        the player left the Ocarina, so the paused song is dropped and D-pad up can't resume it into gameplay."""
        if self.play:
            if key == 'up':
                self.on_pause()
            elif key == 'down':
                self.on_stop()
        elif self.paused_at is not None:
            if key == 'up':
                self.on_pause()
            elif key == 'down':
                self.on_stop()
            elif key in ('left', 'right'):
                self.paused_at = None; self.progress['value'] = 0; self.update_buttons()
                self.set_status('Game connected' if self.connected else 'Game not running', GREEN if self.connected else DIM)
                self.say('You left the Ocarina, so the paused song was dropped. Take it out and press Play.')

    def on_pause(self):
        if self.play:
            self.pause_frame = self.play.position()
            self.play.pause_req = True
            self.play.stop()
        elif self.paused_at is not None:
            self.on_play()

    def on_stop(self):
        if self.play:
            self.play.stop()
        self.paused_at = None
        if not self.play:
            release_all(); self.progress['value'] = 0
            self.set_status('Game connected' if self.connected else 'Game not running', GREEN if self.connected else DIM)
            self.update_buttons()
        self.say('Stopped. All buttons released.')

    def on_playback_end(self, pb):
        if pb is not self.play:
            return
        self.play = None
        try:
            self.write_playback_log(pb)
        except Exception as e:  # noqa: BLE001
            log(f'playback log failed: {e}')
        if getattr(pb, 'pause_req', False) and not pb.error:
            self.paused_at = pb.i
            self.set_status('Paused', AMBER); self.say('Paused. Press Resume or D-pad up to continue from the last phrase.')
        elif pb.error:
            self.set_status('Error', RED); self.say(friendly(pb.error))
        elif pb.watch and pb.watch.tripped:
            self.set_status('Stopped', AMBER)
            self.say(f'Stopped: you used {pb.watch.tripped}. Take the Ocarina out again, then press Play.')
        elif pb.halt:
            self.set_status('Game connected', GREEN)
        else:
            self.progress['value'] = 1000
            self.set_status('Finished', GREEN); self.say('Finished! Pick another song or press Play again.')
            if self.auto_next.get():
                self.after(1500, self.play_next)
        self.update_buttons()

    def write_playback_log(self, pb):
        steps = self.prepared[0] if self.prepared else []
        lines = [f'Song: {self.song["path"]}', f'Mode: {self.opts.get("mode")}  main track {self.opts.get("track")}  '
                 f'fill {self.opts.get("fill")}  speed {self.opts.get("speed")}',
                 f'Length {fmt(self.total / FPS)}, {len(steps)} steps, {len(self.chunks)} pieces', '',
                 'PLANNED SILENCES of 0.4 s or more (these come from the music / arrangement):']
        f, breaths = 0, 0
        for s in steps:
            if not s['buttons'] and s['frames'] >= 12:
                lines.append(f'  at {fmt(f / FPS)} ({f / FPS:6.1f}s)  silent {s["frames"] / FPS:4.1f}s')
            elif not s['buttons'] and s['frames'] == 1:
                breaths += 1
            f += s['frames']
        lines += [f'  (plus {breaths} one-frame releases between notes / breaths - too short to hear as a stop)', '',
                  'PIECE BOUNDARIES (game frames lost between pieces; 0-2 is normal):']
        prev = None
        for i, start, span, fp, el, wall in pb.trace:
            if prev and fp is not None and prev[3] is not None:
                lost = fp - (prev[3] + prev[2])
                lines.append(f'  at {fmt(start / FPS)} ({start / FPS:6.1f}s)  lost {lost} frames ({lost / FPS * 1000:.0f} ms)'
                             + ('   <-- AUDIBLE GAP' if lost > 6 else ''))
            prev = (i, start, span, fp, el)
        for i, start, span, fp, el, wall in pb.trace:
            if el and span and el > span / FPS * 1.25:
                lines.append(f'  piece at {fmt(start / FPS)} ran slow: {span} frames took {el:.1f}s (game below 30 FPS?)')
        lines.append(f'Result: {"stopped by user" if pb.halt else "error: " + str(pb.error) if pb.error else "finished"}')
        out = APP_DIR / 'last-playback.txt'
        out.write_text('\n'.join(lines), encoding='utf-8')
        log(f'playback log written: {out}')

    def tick(self):
        if self.play:
            pos = self.play.position()
            if pos is not None and self.total:
                self.progress['value'] = 1000 * pos / self.total
                self.time_lbl.config(text=f'{fmt(pos / FPS)} / {fmt(self.total / FPS)}')
                k = next((k for f, k in reversed(self.segs) if f <= pos), self.segs[0][1] if self.segs else None)
                if k is not None and self.opts.get('mode') == 'smart':
                    nm = self.song['tracks'][k]['name'] or f'track {k}'
                    self.follow_lbl.config(text=f'Following: {nm[:26]}')
        self.after(150, self.tick)

    def update_buttons(self):
        playing, ready = self.play is not None, self.prepared is not None
        self.play_btn.config(state='normal' if ready and not playing else 'disabled',
                             text='▶  RESUME' if self.paused_at is not None else '▶  PLAY')
        self.pause_btn.config(state='normal' if playing or self.paused_at is not None else 'disabled',
                              text='▶  Resume' if self.paused_at is not None else '❚❚  Pause')
        self.stop_btn.config(state='normal' if playing or self.paused_at is not None else 'disabled')

    # ---------- connection
    def poll_status(self):
        if self.play:
            self.after(2000, self.poll_status); return

        def work():
            info = BACKEND.probe()
            running = info.state != 'offline' or game_running(Path(self.state.get('emulator') or '').name)
            self.after(0, self.status_result, info, running)
        threading.Thread(target=work, daemon=True).start()

    def status_result(self, info, running):
        self.connected, self.compat = info.usable, info
        if info.usable and info.fps:
            self.set_game_fps(float(info.fps))
        if not self.play and self.paused_at is None and time.time() > self.sticky_until:
            if info.state == 'verified':
                self.set_status('Game connected', GREEN)
            elif info.state == 'untested':
                self.set_status(f'Connected: {info.build or "unknown emulator"} (untested)', AMBER)
            elif info.state == 'incompatible':
                self.set_status('Incompatible emulator', RED)
            elif running:
                self.set_status('Game running without the debug link', AMBER)
            else:
                self.set_status('Game not running', DIM)
            if info.state in ('untested', 'incompatible') and self.compat_said != info.message:
                self.compat_said = info.message; self.say(info.message); log('compatibility: ' + info.message)
            elif info.state == 'offline' and running and self.compat_said != 'nolink':
                self.compat_said = 'nolink'
                self.say('The emulator was started without the debug server. Close it, then use Start game here '
                         '(or see the README for starting it yourself).')
        self.start_btn.config(state='disabled' if running else 'normal')
        if info.usable and self.start_btn.winfo_ismapped():
            self.start_btn.pack_forget()
        elif not info.usable and not self.start_btn.winfo_ismapped():
            self.start_btn.pack(side='right', padx=10)
        self.after(2500, self.poll_status)

    def start_game(self):
        exe = self.state.get('emulator') or ''
        if not exe or not Path(exe).is_file():
            exe = filedialog.askopenfilename(title='Find your emulator (for example fritchii.exe)',
                                             filetypes=[('Programs', '*.exe')])
            if not exe:
                return
            self.state['emulator'] = exe; save_state(self.state)
            if not self.state.get('game'):
                g = filedialog.askopenfilename(title='Optional: pick your Ocarina of Time game file (Cancel to choose it in the emulator)',
                                               filetypes=[('Game files', '*.nup *.nsp *.xci *.nca'), ('All files', '*.*')])
                self.state['game'] = g or ''; save_state(self.state)
        if game_running(Path(exe).name):
            self.say('The emulator is already running. If it was started without MIDI of Time, close it and press Start game.')
            return
        env = dict(os.environ); env[BACKEND.launch_env[0]] = BACKEND.launch_env[1]   # only for this emulator process
        args = [exe] + (['-g', self.state['game']] if self.state.get('game') and Path(self.state['game']).is_file() else [])
        try:
            subprocess.Popen(args, cwd=str(Path(exe).parent), env=env)
            self.say('Starting the emulator with the debug link on. Load your save, then take out the Ocarina.')
            log(f'start game: {Path(exe).name} (game file set: {bool(self.state.get("game"))})')
        except OSError as e:
            log(f'start game failed: {e}'); self.say('Couldn\'t start the emulator. Check its location in Advanced.')

    def set_game_fps(self, fps):
        global FPS
        new = 60.0 if fps > 45 else 30.0
        if new != FPS and not self.play:
            FPS = new; log(f'game frame rate mode: {new:.0f} FPS')
            if self.song:
                self.paused_at = None; self.reprepare()

    # ---------- advanced
    def open_advanced(self):
        w = tk.Toplevel(self); w.title('Advanced'); w.configure(bg=PANEL); w.geometry('560x600'); w.transient(self)
        def lab(t): tk.Label(w, text=t, bg=PANEL, fg=INK, font=('Segoe UI', 10)).pack(anchor='w', padx=16, pady=(10, 2))
        if self.song and not self.play:
            o = self.opts
            lab('Main part (Single part plays only this; Smart prefers it)')
            names = [f'{r[0]}: {r[1]}  ({r[2]} notes, {P.nn(r[3])}-{P.nn(r[4])})' + ('  drums' if r[7] else '') for r in self.song['rows']]
            trk = ttk.Combobox(w, values=names, state='readonly', width=60)
            trk.current(next(i for i, r in enumerate(self.song['rows']) if r[0] == o['track'])); trk.pack(anchor='w', padx=16)
            lab('Fill gaps from another part (when the main part is silent)')
            fills = ['None'] + names
            fil = ttk.Combobox(w, values=fills, state='readonly', width=60)
            fil.current(0 if o.get('fill') is None else 1 + next((i for i, r in enumerate(self.song['rows']) if r[0] == o['fill']), -1))
            fil.pack(anchor='w', padx=16)
            lab('Tuning'); tune = ttk.Combobox(w, values=['tuned', 'raw'], state='readonly'); tune.set(o['tune']); tune.pack(anchor='w', padx=16)
            lab('Slurs (legato)'); leg = ttk.Combobox(w, values=['auto', 'all', 'off'], state='readonly'); leg.set(o['legato']); leg.pack(anchor='w', padx=16)
            lab('Vibrato (cents, 0 = off)'); vib = tk.Scale(w, from_=0, to=60, orient='horizontal', bg=PANEL, fg=INK, highlightthickness=0, length=300); vib.set(o['vibrato']); vib.pack(anchor='w', padx=16)
            lab('Speed'); spd = tk.Scale(w, from_=0.5, to=2.0, resolution=0.05, orient='horizontal', bg=PANEL, fg=INK, highlightthickness=0, length=300); spd.set(o['speed']); spd.pack(anchor='w', padx=16)
            lab('Transpose (semitones, blank = automatic)'); tp = tk.Entry(w, bg=BG, fg=INK, insertbackground=INK, width=8)
            tp.insert(0, '' if o['transpose'] is None else str(o['transpose'])); tp.pack(anchor='w', padx=16)
            lab('Start at (seconds into the MIDI)'); stt = tk.Entry(w, bg=BG, fg=INK, insertbackground=INK, width=8); stt.insert(0, str(o['start'])); stt.pack(anchor='w', padx=16)

            def apply(save=False):
                try:
                    o.update(fill=None if fil.current() <= 0 else self.song['rows'][fil.current() - 1][0])
                    o.update(track=self.song['rows'][trk.current()][0], tune=tune.get(), legato=leg.get(), vibrato=float(vib.get()),
                             speed=float(spd.get()), transpose=int(tp.get()) if tp.get().strip() else None, start=float(stt.get() or 0))
                except ValueError:
                    return
                self.paused_at = None; self.reprepare()
                if save and self.song['path'].parent == MIDI_DIR:
                    side = {'track': o['track']}
                    if o['transpose'] is not None: side['transpose'] = o['transpose']
                    if o['start']: side['start'] = o['start']
                    if o.get('fill') is not None: side['fill'] = o['fill']
                    side['mode'] = o.get('mode', 'smart')
                    (MIDI_DIR / (self.song['path'].stem + '.ocarina.json')).write_text(json.dumps(side))
                    self.say('Saved as this song\'s default.')
            r = tk.Frame(w, bg=PANEL); r.pack(fill='x', padx=16, pady=14)
            self.btn(r, 'Apply', apply, color=GOLD).pack(side='left')
            self.btn(r, 'Save as this song\'s default', lambda: apply(True)).pack(side='left', padx=8)
        else:
            tk.Label(w, text='Pick a song (and stop playback) to change how it plays.', bg=PANEL, fg=INK).pack(padx=16, pady=16)
        r2 = tk.Frame(w, bg=PANEL); r2.pack(side='bottom', fill='x', padx=16, pady=12)
        self.btn(r2, 'Open log folder', lambda: os.startfile(APP_DIR)).pack(side='left')
        self.btn(r2, 'Open Songs folder', lambda: os.startfile(MIDI_DIR)).pack(side='left', padx=8)
        self.btn(r2, 'Settings…', self.open_settings).pack(side='right')

    def open_settings(self):
        w = tk.Toplevel(self); w.title('Settings'); w.configure(bg=PANEL); w.geometry('620x430'); w.transient(self)
        rows = {}

        def row(label, key, pick):
            tk.Label(w, text=label, bg=PANEL, fg=INK, font=('Segoe UI', 10)).pack(anchor='w', padx=16, pady=(12, 2))
            f = tk.Frame(w, bg=PANEL); f.pack(fill='x', padx=16)
            v = tk.StringVar(value=self.state.get(key, '')); rows[key] = v
            tk.Entry(f, textvariable=v, bg=BG, fg=INK, insertbackground=INK, relief='flat').pack(side='left', fill='x', expand=True, ipady=4)
            self.btn(f, 'Browse…', lambda: v.set(pick() or v.get())).pack(side='left', padx=(8, 0))
        row('Emulator program (with the NX2 debug server: fritchii.exe for Fritchii v6, lichii.exe for v5)', 'emulator',
            lambda: filedialog.askopenfilename(filetypes=[('Programs', '*.exe')]))
        row('Game file (optional)', 'game', lambda: filedialog.askopenfilename(
            filetypes=[('Game files', '*.nup *.nsp *.xci *.nca'), ('All files', '*.*')]))
        row('Your MIDI folder (for "Search MIDI folder")', 'library', lambda: filedialog.askdirectory())
        rem = tk.BooleanVar(value=self.state.get('remote', False))
        tk.Checkbutton(w, text='Phone remote on this home network (restart MIDI of Time to apply)', variable=rem,
                       bg=PANEL, fg=INK, selectcolor=BG, activebackground=PANEL, activeforeground=GOLD).pack(anchor='w', padx=12, pady=(14, 0))
        pin_lbl = tk.Label(w, text=f'Remote PIN: {self.state["remote_pin"]}', bg=PANEL, fg=DIM); pin_lbl.pack(anchor='w', padx=16)

        def new_pin():
            self.state['remote_pin'] = f'{secrets.randbelow(1000000):06d}'; save_state(self.state)
            pin_lbl.config(text=f'Remote PIN: {self.state["remote_pin"]} (restart to apply)')

        def save():
            for k, v in rows.items():
                self.state[k] = v.get().strip()
            self.state['remote'] = bool(rem.get()); self.lib_index = None
            save_state(self.state); self.say('Settings saved.'); w.destroy()
        r = tk.Frame(w, bg=PANEL); r.pack(side='bottom', fill='x', padx=16, pady=14)
        self.btn(r, 'Save', save, color=GOLD).pack(side='left')
        self.btn(r, 'New PIN', new_pin).pack(side='left', padx=8)

    def on_mode(self):
        if self.song and not self.play and self.opts:
            self.opts['mode'] = self.mode_var.get(); self.paused_at = None; self.reprepare()

    def play_next(self):
        cur = self.song['path'] if self.song else None
        nxt = self.items.index(cur) + 1 if cur in self.items else 0
        if nxt >= len(self.items):
            self.say('That was the last song in the list.'); return
        if self.play:
            self.play.stop(); self.after(400, lambda: self.load_song(self.items[nxt], autoplay=True)); return
        self.load_song(self.items[nxt], autoplay=True)

    # ---------- phone remote
    def start_remote(self):
        if not self.state.get('remote', False):
            self.remote_lbl.config(text='Phone remote: off (Advanced → Settings)'); return
        port, pin = int(self.state.get('remote_port', 8765)), self.state['remote_pin']
        try:
            R.serve(self, port, pin)
            ips = R.lan_addresses()
            self.remote_lbl.config(text=f'Phone remote: http://{ips[0] if ips else "this-pc"}:{port}   PIN {pin}')
            log(f'remote on port {port}')
        except OSError as e:
            log(f'remote failed: {e}'); self.remote_lbl.config(text='Phone remote unavailable (port in use)')

    def drain_remote(self):
        try:
            while True:
                self.remote_q.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self.drain_remote)

    def remote_state(self):
        colors = {GREEN: 'green', GOLD: 'gold', AMBER: 'amber', RED: 'red', DIM: 'dim'}
        pos = 0
        if self.play and self.play.position() is not None:
            pos = self.play.position() / FPS
        favs = self.state['favorites']
        return {'status': self.status_lbl.cget('text'), 'color': colors.get(self.status_dot.cget('fg'), 'dim'),
                'title': self.title_lbl.cget('text'), 'info': self.info_lbl.cget('text'), 'warn': self.warn_lbl.cget('text'),
                'message': self.msg_lbl.cget('text'), 'following': self.follow_lbl.cget('text') if self.play else '',
                'pos': pos, 'total': self.total / FPS if self.prepared else 0,
                'can_play': bool(self.prepared) and not self.play, 'resume': self.paused_at is not None,
                'mode': (self.opts or {}).get('mode', 'smart'), 'path': str(self.song['path']) if self.song else None,
                'songs_rev': f'{len(self.my_songs())}-{len(favs)}-{"|".join(self.state["recent"][:1])}'}

    def remote_songs(self):
        favs = self.state['favorites']
        item = lambda p: {'name': Path(p).stem, 'path': str(p), 'fav': str(p) in favs, 'size': fsize(p)}
        st = self.remote_state()
        return {'rev': st['songs_rev'], 'all': [item(p) for p in self.my_songs()],
                'fav': [item(p) for p in favs if Path(p).is_file()], 'recent': [item(p) for p in self.state['recent'] if Path(p).is_file()]}

    def remote_search(self, q):
        if not q.strip() or not self.state.get('library'):
            return []
        hits, _ = self.library_search(q, 200)
        return [{'name': p.stem, 'path': str(p), 'where': p.parent.name, 'size': fsize(p),
                 'fav': str(p) in self.state['favorites']} for p in hits]

    def remote_call(self, name, data):
        if name == 'select' and data.get('path') and Path(data['path']).is_file():
            p = Path(data['path'])
            if p.parent != MIDI_DIR and p not in self.items:
                self.library_hits = [p] + [h for h in self.library_hits if h != p]
            self.load_song(p)
        elif name == 'play':
            self.on_play()
        elif name == 'pause':
            self.on_pause()
        elif name == 'stop':
            self.on_stop()
        elif name == 'next':
            self.play_next()
        elif name == 'fav' and data.get('path'):
            k, favs = data['path'], self.state['favorites']
            favs.remove(k) if k in favs else favs.append(k)
            save_state(self.state); self.refresh_list()
            if self.song and str(self.song['path']) == k:
                self.fav_btn.config(text='★ Favorite' if k in favs else '☆ Favorite')
        elif name == 'mode' and data.get('mode') in ('smart', 'part'):
            self.mode_var.set(data['mode']); self.on_mode()
        return {'ok': True}

    def on_resize_right(self, e):
        w = max(200, e.width - 40)
        for lbl in (self.title_lbl, self.info_lbl, self.warn_lbl, self.msg_lbl):
            lbl.config(wraplength=w)

    # ---------- helpers
    def set_status(self, text, color):
        self.status_lbl.config(text=text); self.status_dot.config(fg=color)
        self.sticky_until = time.time() + 8 if text in ('Finished', 'Error') else 0

    def say(self, text):
        self.msg_lbl.config(text=text)

    def on_close(self):
        if self.play:
            self.play.stop(); time.sleep(0.2)
        release_all() if self.connected else None
        self.destroy()


_SIZES = {}


def fsize(p):
    k = str(p)
    if k not in _SIZES:
        try:
            _SIZES[k] = Path(p).stat().st_size
        except OSError:
            _SIZES[k] = 0
    return _SIZES[k]


def kb(n):
    return f'{n / 1024:.0f} KB' if n < 1024 * 1024 else f'{n / 1048576:.1f} MB'


def fmt(sec):
    sec = max(0, int(sec)); return f'{sec // 60}:{sec % 60:02d}'


def main():
    guard = socket.socket()
    try:
        guard.bind(('127.0.0.1', 6548))          # one window at a time
    except OSError:
        r = tk.Tk(); r.withdraw()
        messagebox.showinfo(APP_NAME, f'{APP_NAME} is already open.'); return
    try:
        App().mainloop()
    except Exception as e:  # noqa: BLE001
        log('crash: ' + ''.join(traceback.format_exception(e))); raise


if __name__ == '__main__':
    main()
