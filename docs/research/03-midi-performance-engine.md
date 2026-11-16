# Making Link perform MIDI

The MIDI of Time concept is distinct from external soundtrack replacement. MIDI events are translated into emulated controller inputs. The actual game runs its Ocarina instrument and produces the resulting audio.

## Current architecture (from November 14–15 development reports)

`MIDI file / MIDI selection → arranger → playable pitch and fingering selection → frame-scheduled Fritchii input → Link's in-game Ocarina → captured game audio`

Kill switch and controller shortcuts are described under [Safety controls](#safety-controls-added-2026-11-15).

Fritchii's opt-in local debug input server was traced to `src/core/debugger/nx2_debug_tools.cpp` and `tools/nx2/debug_mcp.py` around tag `fritchii-v5.8.4`. On the tested setup the server is configured through `EDEN_NX2_DEBUG_SERVER=127.0.0.1:6545`; JSON-line commands include `input`, `input_sequence`, `input_record`, `input_replay`. The debug API uses Nintendo button names, NOT the physical Xbox legends.

Source reference recorded in the handoff: https://github.com/Frizti/Fritchii/blob/fritchii-v5.8.4/docs/nx2/debug-mcp.md

This is a description of a **specific tested/employed interface**, not an assurance that every Fritchii version or emulator supports it. Confirm compatibility per release.

## Important performance behaviors

| Feature | What was observed/reported | Evidence grade |
|---|---|---|
| Bend while holding a note | LEFT stick changes the audible pitch without requiring a new face-button note-on | Direct player testing, later MIDI demonstrations |
| Slur on held button or pitch modifiers | Switching pitch controls during one held note causes a smaller amplitude dip than a fresh attack | November 14 development tests; original measurement logs should be linked |
| Attacks/retriggers | The engine releases 1 frame before a different note and 2 frames before a repeated note (`GAP_DIFF`/`GAP_SAME`); both re-attack | Implemented and used in all playback; universal minimum not separately measured |
| Sustain/breath | Sound dies ~6.8 s after the last breath; only a release of about 4 frames or more counts as a breath. The engine (`apply_breaths`) places a 4-frame breath at most every 6.3 s, choosing an existing gap or the end of the longest recent note in the previous 2.5 s, without changing song timing | **Measured 2026-11-15** ([details](02-acoustic-measurements.md#breath-limit-and-what-counts-as-a-breath-measured-2026-11-15)); fix verified on three songs |
| Multiple MIDI tracks | Smart arranger can follow melody across different MIDI parts | Demonstrated by user playback and GUI status |
| Polyphony | Two overlapping solos can be rapidly interleaved to yield the impression of multiple parts | Demonstrated DragonForce arrangement; not proof of actual polyphony |
| Frame timing | Debug `input_sequence` step durations are presented frames; at 30 FPS a frame ≈33.3 ms | API semantics; real timing can vary |
| Sequence cap | `input_sequence` accepts 1 to 1,000 steps (server error: *steps must be an array of 1 to 1000*). MIDI of Time sends pieces of at most 1,000 steps, cut at rests; each piece boundary costs 1 presented frame | Verified against Fritchii v5.8.4 and enforced in `backends.py` (offline test) |
| Very short notes | DragonForce replay reported dropping some sub-frame notes | Reported; need logs to quantify per build |

### Pitch change versus new articulation

The same note can have multiple controller fingerings. MIDI of Time can choose a route that changes LEFT-stick position or modifiers while a base button stays pressed, creating an expressive transition rather than forcing a new attack. In November 14 development notes, slur transitions were estimated as roughly 2–8 dB dips versus about 33 dB for a new attack; preserve this as **reported, unreplicated numerical evidence** until the measurement artifacts are linked. Portamento (continuous audible glide), slur (connected phrasing), vibrato and tremolo are different musical behaviors and should not be conflated.

### Arrangement strategy

The Ocarina is treated as **monophonic** unless a future test demonstrates real multiple simultaneous voices. Smart mode can select a leading line across MIDI tracks, while Single Part plays a chosen track. Use the exact dedicated MIDI track name `[Link]` when an author wants to direct selection, rather than relying on General MIDI instrument names such as Ocarina. This is an authoring convention established by this software, not a game-native song tag.

For the public documentation, avoid claims that all songs sound good unmodified: complicated arrangements need melody selection, range fitting, and sometimes phrase-aware rewrites. Preserving rests matters as much as playing notes.

## User experience already demonstrated

The Windows desktop interface includes a song library, play/pause/stop, favorites and recent songs, Smart/Single Part, performance options and autoplay. A LAN-based phone browser remote has also been operated successfully by the project creator. Features and build-specific behavior may change after these dated notes; **the application source and release test report remain authoritative for code-level claims**.

## Safety controls (added 2026-11-15)

- **Kill switch:** D-pad left or right on the physical controller, read through XInput (`src/midi_of_time/padwatch.py`), stops playback instantly. Closing the connection makes the server release all input.
- **Shortcuts while a song is playing or paused:** D-pad up = pause/resume (resumes at the paused note), D-pad down = stop. They never start a song, because the app cannot tell whether the Ocarina is out.
- The debug server handles one request at a time: while a piece plays it doesn't answer other requests. The remake shows no on-screen note staff, so "Ocarina out" can't be checked from screenshots either.

## Open investigations

- Vibrato depth and rate limits (the vertical bend curve itself was measured 2026-11-14)
- Whether a 3-frame release counts as a breath (1–2 frames do not, 4 frames do; measured 2026-11-15)
- Detecting "Ocarina out" from game memory (`read_memory` / `search_memory` exist in the debug server)
- Identical-note retrigger and precise onset/offset timing
- Legato versus reattack attenuation measurements
- Absolute fundamental/octave versus loudest harmonic
- Which fork/build/debug-server versions support the injector
- Whether velocity changes any in-game parameter
