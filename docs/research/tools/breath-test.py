"""Breath test for the Ocarina (2026-11-15). Run from the repo: python docs/research/tools/breath-test.py
Needs: Fritchii v5.8.4 with the debug server on, Ocarina out, hands off; D-pad left/right aborts.

Five sections, each 20 s of continuous slurred notes (no gaps), separated by 3 s of silence.
Each section is higher than the one before. Inside sections 2-5 a forced "breath" (release) is
inserted every 180 frames (6 s); only the release length differs:
  1: no breaths at all (control: should cut out after ~7 s)
  2: 1-frame release (what the app does today inside slurred passages)
  3: 2-frame release
  4: 4-frame release
  5: 8-frame release
Listen for sections where the sound drops out and comes back.
"""
import json, socket, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from midi_of_time import padwatch as PW   # D-pad left/right aborts the test

PAIRS = [('R', 'B'), ('B', 'A'), ('A', 'Y'), ('Y', 'X'), ('X', 'Y')]
RELEASE = [0, 1, 2, 4, 8]
SECTION, NOTE, EVERY = 600, 10, 180


def section(i):
    a, b = PAIRS[i]
    steps, f, since = [], 0, 0
    while f < SECTION:
        n = min(NOTE, SECTION - f)
        if RELEASE[i] and since + n > EVERY:
            steps.append({'buttons': [], 'left_stick': [0, 0], 'frames': RELEASE[i]}); f += RELEASE[i]; since = 0
            continue
        steps.append({'buttons': [a if (f // NOTE) % 2 == 0 else b], 'left_stick': [0, 0], 'frames': n})
        f += n; since += n
    return steps


steps = []
for i in range(5):
    steps.append({'buttons': [], 'left_stick': [0, 0], 'frames': 90})
    steps += section(i)
steps.append({'buttons': [], 'left_stick': [0, 0], 'frames': 10})
print(f'{len(steps)} steps, {sum(s["frames"] for s in steps) / 30:.0f} s', flush=True)

sock = socket.create_connection(('127.0.0.1', 6545), timeout=10)
watch = PW.Watch(lambda what: (print('ABORTED by', what, flush=True), sock.close()))
sock.settimeout(300)
t0 = time.time()
sock.sendall((json.dumps({'id': 1, 'method': 'input_sequence', 'params': {'controller': 'player1', 'steps': steps}}) + '\n').encode())
buf = b''
try:
    while not buf.endswith(b'\n'):
        c = sock.recv(65536)
        if not c:
            break
        buf += c
except OSError:
    pass
watch.stop()
print(f'done after {time.time() - t0:.1f} s:', buf.decode(errors='replace').strip()[:300], flush=True)
