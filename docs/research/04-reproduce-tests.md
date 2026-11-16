# Reproducing the Ocarina tests

This protocol is intended for independent players and maintainers who want to refine the data. It does not require changing the user's original configuration, archives or recordings.

## Record the test configuration

For every run record the date, actual game build, emulator fork/version/commit, controller hardware and physical labels, input layout, FPS, audio settings, record format, and exact held input events with timestamps or frame counts.

## Controlled baseline

1. Equip the in-game Ocarina with no background music or effects if a controlled area is available.
2. Record each of the five base inputs separately, starting with the LEFT stick centered. Log button-down and button-up frames independently.
3. Produce multiple takes per button. Avoid confusing lingering reverb tails with continuing input.
4. Analyze the fundamental with waveform periodicity and harmonic consistency in addition to FFT dominant-peak search.
5. Compare nominal notes, measured F0, dominant peaks, confidence and cents differences in the output CSV.

## Pitch modifiers and controller mapping

1. Verify `LB`, `LT`, each held individually and together; report precedence.
2. Hold a single base note and test LEFT-stick positions down / half-down / center / half-up / up while logging actual stick deflection.
3. Record smooth LEFT-stick sweeps and distinguish continuous pitch transition from stepped pitch jumps.
4. Test the original alternative G5 fingerings (`A+up`, `B+down`) and additive ±3 extremes on each base separately.
5. Keep the RIGHT stick in its normal camera role; do not reuse obsolete November 9 right-stick assumptions.

## Articulation and performance

1. Repeat same-note `on → off → on` with different release gaps measured in frames.
2. Transition between equal-pitch alternate fingerings and nearby-pitch fingerings, measuring amplitude envelope and pitch stability.
3. Sustain each note with a known held duration, then repeat near the reported breath limit to estimate behavior with uncertainty.
4. Test chords and overlapping input events; explicitly distinguish polyphony from rapid arpeggiation and reverb.
5. Test a long MIDI with known note counts, server step counts and timestamps to identify dropped events and chunks.

## Data preservation

- Originals are immutable. Save copies and derived WAV/CSV/chart files separately.
- For every original compute SHA-256 and capture date/source metadata.
- Mark each result as measured, observed, derived or unresolved; document uncertainty.
- Do not publish other creators' full copyrighted arrangements or guide text without permission. Prefer attributed links and original newly-created examples.

**The project owner approves changes to the public repository and the working Fritchii setup separately.** No procedure in this page authorizes modifying saves, caches, launcher scripts or game files.
