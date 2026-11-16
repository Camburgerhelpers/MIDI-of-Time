# Ocarina Research Lab

This research is published alongside the **MIDI of Time** application, so players and tool authors can understand both how to play the remake's Ocarina and how the software makes Link perform MIDI.

| Resource | Contents |
|---|---|
| [Controls & pitches](01-controls-and-pitches.md) | Tested Xbox-labelled controller mapping, modifier rules, alternative fingerings, the expected chromatic range |
| [Acoustics & charts](02-acoustic-measurements.md) | Four early OBS capture sessions, frequency peaks, bent-note estimates, methods and uncertainty |
| [MIDI performance](03-midi-performance-engine.md) | Held pitches, pitch morphing, retriggers, MIDI translation, timing, breaths, known limitations |
| [Test protocol](04-reproduce-tests.md) | How another player can replicate or improve the measurements |
| [Historical song archive](05-historical-sources.md) | Early community tabs, link provenance, notation warnings and attribution |
| [Test tools](tools/) | Scripts used for the 2026-11-15 breath measurements (need Fritchii v5.8.4 with the debug server) |
| [Evidence register](06-evidence-register.md) | Raw recording hashes, missing evidence, verification status and publication checklist |

## Evidence terms

- **Tested:** directly exercised by the project creator in game and described in dated playtest notes.
- **Measured spectral estimate:** audio-derived numerical value from recorded OBS samples; the strongest FFT peak may not be the synthesized fundamental.
- **Demonstrated in playback:** a behavior observed with MIDI of Time, for which the original raw timing/input logs may still need linking.
- **Derived / predicted:** calculated from a verified base pitch and a modifier rule but not independently measured for that exact combination.
- **Unresolved:** no sufficiently reproducible measurement yet.

**Superseding correction:** the **LEFT** analog stick bends the Ocarina pitch; the **RIGHT** stick controls the camera. A November 9 research snapshot said the right stick might change pitch. That is obsolete and retained only for historical traceability.

**Scope:** currently the remake played through Fritchii, using the Classic one-handed layout on an Xbox-labelled 8BitDo Ultimate 2C. Do not assume the same map for all controllers, emulators, firmware, or game builds.
