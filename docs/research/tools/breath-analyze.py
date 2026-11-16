"""Analyze a breath-test recording: python breath-analyze.py audio.wav (mono 8 kHz s16)."""
import math, struct, sys, wave

SR, WIN, HOP = 8000, 320, 160          # 40 ms window, 20 ms hop
CENTS = {'R': 74 * 100 + 23, 'B': 77 * 100 + 9, 'A': 81 * 100 + 28, 'Y': 83 * 100 + 24, 'X': 86 * 100 + 24}
PAIRS = [('R', 'B'), ('B', 'A'), ('A', 'Y'), ('Y', 'X'), ('X', 'Y')]
LABEL = ['no breaths', '1-frame', '2-frame', '4-frame', '8-frame']
hz = {k: 440 * 2 ** ((c / 100 - 69) / 12) for k, c in CENTS.items()}

w = wave.open(sys.argv[1]); n = w.getnframes(); x = struct.unpack(f'<{n}h', w.readframes(n))
hann = [0.5 - 0.5 * math.cos(2 * math.pi * i / (WIN - 1)) for i in range(WIN)]


def goertzel(seg, f):
    k = 2 * math.cos(2 * math.pi * f / SR); s1 = s2 = 0.0
    for v in seg:
        s0 = v + k * s1 - s2; s2, s1 = s1, s0
    return s1 * s1 + s2 * s2 - k * s1 * s2


frames = [[x[i + j] * hann[j] for j in range(WIN)] for i in range(0, n - WIN, HOP)]
T = lambda i: i * HOP / SR


def env(pair):
    return [10 * math.log10(1e-9 + sum(goertzel(fr, hz[p]) for p in pair)) for fr in frames]


pos = 0
for s, pair in enumerate(PAIRS):
    e = env(pair)
    peak = sorted(e[pos:])[int(len(e[pos:]) * 0.98)]
    thr = peak - 25
    on = next(i for i in range(pos, len(e)) if all(v > thr for v in e[i:i + 5]))
    end = min(len(e), on + int(20.0 * SR / HOP))
    gaps, i = [], on
    while i < end:
        if e[i] < thr:
            j = i
            while j < end and e[j] < thr:
                j += 1
            if (j - i) * HOP / SR >= 0.08:
                gaps.append((T(i) - T(on), (j - i) * HOP / SR))
            i = j
        else:
            i += 1
    tail = next((T(i) for i in range(end, len(e)) if e[i] < thr), None)
    print(f'section {s + 1} ({LABEL[s]:10}) starts at {T(on):6.2f}s in file; '
          + ('no dropouts' if not gaps else 'dropouts: ' + ', '.join(f'{a:.2f}s for {d:.2f}s' for a, d in gaps)))
    pos = end + int(1.0 * SR / HOP)
