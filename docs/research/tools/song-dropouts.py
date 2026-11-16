"""Find Ocarina dropouts in OBS recordings: python song-dropouts.py file1.mp4 [file2 ...]
Band-passes the audio to the Ocarina's range, then lists every silence >= 0.35 s between the first and last note."""
import math, struct, subprocess, sys, wave
from pathlib import Path

SR, HOP = 8000, 160      # 20 ms
for f in sys.argv[1:]:
    wav = Path(f).with_suffix('.ocarina.wav')
    wav = Path(sys.argv[0]).parent / wav.name
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', f, '-vn', '-ac', '1', '-ar', str(SR),
                    '-af', 'highpass=f=520,highpass=f=520,lowpass=f=1500,lowpass=f=1500', '-c:a', 'pcm_s16le', str(wav)], check=True)
    w = wave.open(str(wav)); n = w.getnframes(); x = struct.unpack(f'<{n}h', w.readframes(n))
    e = [10 * math.log10(1e-9 + sum(v * v for v in x[i:i + HOP]) / HOP) for i in range(0, n - HOP, HOP)]
    peak = sorted(e)[int(len(e) * 0.95)]; thr = peak - 22
    on = [i for i, v in enumerate(e) if v > thr]
    if not on:
        print(f'{Path(f).name}: no Ocarina sound found'); continue
    a, b = on[0], on[-1]
    gaps, i = [], a
    while i <= b:
        if e[i] < thr:
            j = i
            while j <= b and e[j] < thr:
                j += 1
            gaps.append(((i - a) * HOP / SR, (j - i) * HOP / SR)); i = j
        else:
            i += 1
    long_ = [(t, d) for t, d in gaps if d >= 0.35]
    breaths = [d for t, d in gaps if 0.08 <= d < 0.35]
    print(f'{Path(f).name}: {(b - a) * HOP / SR:.1f} s of playing; short gaps (breaths/rests) {len(breaths)}; '
          f'silences >= 0.35 s: {len(long_)}')
    for t, d in long_:
        print(f'    at {int(t // 60)}:{t % 60:05.2f}  silent {d:.2f} s')
