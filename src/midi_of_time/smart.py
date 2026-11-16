"""ocarina_smart.py - smarter arranging for the Ocarina MIDI app (engine file stays unchanged).

follow_melody(): pick, window by window, the part that carries the tune and stitch it into one line.
phrase_fit():    move whole phrases by octaves into Link's range so runs keep their shape.
"""
import math, re

GOOD = re.compile(r'melod|lead|vocal|voice|vox|sing|soprano|right|solo|flute|piccolo|violin|whistle|ocarina|recorder|'
                  r'trumpet|sax|oboe|clarinet|fiddle|theme|main|\[link\]', re.I)
BAD = re.compile(r'bass|timp|drum|bongo|conga|perc|kick|snare|hat|cymbal|pad|chord|rhythm|harmony|accomp|left|'
                 r'tuba|contrabass|strings? ens|choir|fx|effect', re.I)
WINDOW = 2.0       # seconds per decision window
SWITCH = 3.0       # cost of changing part (keeps the line from hopping around)
SILENT = -2.5      # score for staying on a part that is resting in this window
FILL_GAP = 0.4     # pauses at least this long in the followed part get filled from another part


def follow_melody(tracks, t2s, skyline, main=None):
    """Returns (notes, segments). notes: (start_tick, end_tick, pitch, ch); segments: [(sec, track)]."""
    cands = []
    for k, tr in enumerate(tracks):
        ns = tr['notes']
        if len(ns) < 10 or all(n[3] == 9 for n in ns):
            continue
        sky = skyline(ns)
        cands.append((k, tr['name'] or '', [(t2s(s), s, e, p, ch, t2s(cut), cut) for s, cut, e, p, ch in sky], ns))
    if not cands:
        return [], []
    if len(cands) == 1:
        k, _, sky, _ = cands[0]
        return [(s, e, p, ch) for _, s, e, p, ch, _, _ in sky], [(0.0, k)]
    t_end = max(n[0] for c in cands for n in c[2]) + 0.001
    t_beg = min(n[0] for c in cands for n in c[2])
    nw = max(1, math.ceil((t_end - t_beg) / WINDOW))
    # per-track, per-window notes and raw onset counts (for chord detection)
    per, covers = [], []
    for k, name, sky, raw in cands:
        wins = [[] for _ in range(nw)]
        for n in sky:
            wins[min(nw - 1, int((n[0] - t_beg) / WINDOW))].append(n)
        rawc = [0] * nw
        for s, e, p, ch in raw:
            rawc[min(nw - 1, max(0, int((t2s(s) - t_beg) / WINDOW)))] += 1
        bonus = (2.0 if GOOD.search(name) else 0) - (4.0 if BAD.search(name) else 0) + (1.5 if k == main else 0)
        cov = [0.0] * nw
        for n in sky:
            a, b = n[0], n[5]
            w0 = min(nw - 1, max(0, int((a - t_beg) / WINDOW)))
            w1 = min(nw - 1, max(0, int((b - t_beg) / WINDOW)))
            for w in range(w0, w1 + 1):                 # overlap of [a, b) with each window
                lo, hi = t_beg + w * WINDOW, t_beg + (w + 1) * WINDOW
                cov[w] += max(0.0, min(b, hi) - max(a, lo))
        per.append((k, wins, rawc, bonus)); covers.append([min(1.0, c / WINDOW) for c in cov])

    def emit(i, w):
        k, wins, rawc, bonus = per[i]
        ns = wins[w]
        if not ns:
            return SILENT
        ps = [n[3] for n in ns]
        avg, distinct = sum(ps) / len(ps), len(set(ps))
        chordy = 1 - len(ns) / max(1, rawc[w])
        cover = covers[i][w]                       # share of the window where this part is sounding
        return (1.5 * math.log1p(len(ns)) + 3.0 * cover + 0.12 * (avg - 60) + 1.5 * min(distinct, 6) / 6
                - 4.0 * max(0.0, chordy - 0.1) - (3.0 if avg < 50 else 0) + bonus)

    # Viterbi over windows: best path of parts with a switching cost
    m = len(per)
    score = [emit(i, 0) for i in range(m)]
    back = []
    for w in range(1, nw):
        best_prev = max(range(m), key=lambda j: score[j])
        new, bk = [], []
        for i in range(m):
            stay, switch = score[i], score[best_prev] - SWITCH
            if stay >= switch:
                new.append(stay + emit(i, w)); bk.append(i)
            else:
                new.append(switch + emit(i, w)); bk.append(best_prev)
        score = new; back.append(bk)
    path = [max(range(m), key=lambda i: score[i])]
    for bk in reversed(back):
        path.append(bk[path[-1]])
    path.reverse()
    notes, segs, chosen = [], [], []
    for w, i in enumerate(path):
        k, wins, _, _ = per[i]
        if not segs or segs[-1][1] != k:
            segs.append((round(t_beg + w * WINDOW, 1), k))
        chosen += wins[w]
    chosen.sort(key=lambda n: n[0])
    # fill pauses (>= FILL_GAP s) in the chosen line with the other part that sounds most during the pause
    allsky = [n for c in per for ww in c[1] for n in ww]
    fill = []
    for a, b in zip([None] + chosen, chosen + [None]):
        g0, g1 = (a[5] if a else t_beg), (b[0] if b else t_end)
        if g1 - g0 < FILL_GAP:
            continue
        g0_tick = a[6] if a else None
        best, best_ov = None, 0.0
        for i in range(m):
            ns = [n for ww in per[i][1] for n in ww if n[0] < g1 - 0.05 and n[5] > g0 + 0.1]
            ov = sum(min(n[5], g1) - max(n[0], g0) for n in ns)
            if ns and ov > best_ov:
                best, best_ov = ns, ov
        for n in best or []:
            s0 = n[1] if (g0_tick is None or n[0] >= g0) else max(n[1], g0_tick)   # a held note joins mid-way
            fill.append((max(n[0], g0), s0, n[2], n[3], n[4], n[5], n[6]))
    notes = [(s, e, p, ch) for _, s, e, p, ch, _, _ in chosen + fill]
    return sorted(notes), segs


def phrase_fit(mel, lo, hi, gap=0.3, max_len=24):
    """mel: [(start_s, cut_s, end_s, pitch, ch)]. Octave-shift each phrase as a whole; returns pitches, folded."""
    phrases, cur = [], []
    for k, n in enumerate(mel):
        if cur and (n[0] - mel[k - 1][1] > gap or len(cur) >= max_len):
            phrases.append(cur); cur = []
        cur.append(k)
    if cur:
        phrases.append(cur)
    out, folded, prev = [0] * len(mel), 0, None
    allp = sorted(n[3] for n in mel)
    gmed = allp[len(allp) // 2]
    center = (lo + hi) / 2
    gshift = min(range(-60, 61, 12), key=lambda sh: abs(gmed + sh - center))
    for ph in phrases:
        ps = [mel[k][3] for k in ph]
        med = sorted(ps)[len(ps) // 2]
        def key(sh):
            inside = sum(lo <= p + sh <= hi for p in ps)
            return (inside, -(abs(sh - prev) if prev is not None else abs(sh - gshift)), -abs(med + sh - center))
        sh = max(range(-60, 61, 12), key=key)
        prev = sh
        for k in ph:
            q = mel[k][3] + sh
            while q < lo: q += 12
            while q > hi: q -= 12
            folded += q != mel[k][3] + sh
            out[k] = q
    return out, folded


def broken_intervals(orig, new):
    """How many neighbouring notes changed their interval (octave jumps inside the line)."""
    return sum(1 for a, b, c, d in zip(orig, orig[1:], new, new[1:]) if (b - a) != (d - c))
