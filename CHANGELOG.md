# Changelog

## 0.1.1-alpha — Fritchii v6 and 60 FPS

- **Fritchii v6.1 verified** (60 FPS mode): tempo, fast passages, held notes and the D-pad kill switch tested in game.
- **Breathing fix for fast slurred runs.** When every note is too short to lend a whole breath (e.g. Bloody Tears, long runs of ~0.13 s notes with no gaps), the breath is now borrowed from several notes. Before, such runs could go 20+ seconds without a breath and the Ocarina went silent. Song timing is unchanged; at 30 FPS and 60 FPS alike.
- Fritchii v6 support: the app recognizes the emulator running as `fritchii.exe` (v6) as well as `lichii.exe` (v5 and the v6 forwarder). Before, a Fritchii v6 started outside MIDI of Time could show as "Game not running".
- Settings and file pickers suggest `fritchii.exe` for Fritchii v6.
- 60 FPS timing (already automatic in 0.1.0) is now tested: the breath limit follows real time (~6.3 s), measured on v6.1.
- Docs: README, TROUBLESHOOTING and COMPATIBILITY updated for v6.

## 0.1.0-alpha — first public alpha

- Desktop app:
  - Song list (Songs folder, Favorites, Recent), filter, sort by name or size
  - Play, Pause/Resume, Stop, Next, progress bar, auto-play next song
- Ocarina Research Lab (`docs/research/`): controller mapping, pitch and breath measurements, test tools, historical song sources, evidence register.
- Smart breathing: fixes multi-second dropouts in busy passages. Measured on Fritchii v5.8.4: the game only counts a release of about 4 frames or more as a breath (1–2 frames don't), and the sound dies ~6.8 s after the last breath. Breaths are now 4 frames, placed at the most musical spot in the preceding 2.5 s, with timing unchanged. Verified with OBS recordings of three busy songs: no dropouts.
- Controller kill switch: D-pad left/right during a song stops playback and releases all input (tested on Fritchii v5.8.4: those are the only buttons that leave the Ocarina or open its song menu).
- Controller shortcuts while a song is playing or paused: D-pad up = pause/resume, D-pad down = stop. They never start a song.
- Resume continues from the note that was playing when you paused.
- Smart mode: follows the melody across MIDI parts and fills short pauses from the part still playing. One part mode plays a single chosen track.
- Expressive engine:
  - Slurs and pitch bend
  - Mod-wheel or added vibrato
  - Per-note tuning correction
  - Phrase-aware octave fitting into the Ocarina's range
- Instrument model measured on Fritchii v5.8.4 in 30 FPS mode. Timing scales automatically in 60 FPS mode (untested).
- Connection layer (`backends.py`) with runtime compatibility detection (verified / untested / incompatible / offline). Only Fritchii v5.8.4 is verified.
- **Start game** launches your emulator with the NX2 debug server enabled for that launch only.
- Optional phone remote: home network only, 6-digit PIN, temporary lockout after wrong PINs, off by default.
- Search MIDI folder: Everything integration when installed, otherwise a cached folder scan.
- Per-song defaults (`*.ocarina.json`) and `[Link]` track override.
- Playback diagnostics written to `data\last-playback.txt`.
- Built-in original demo song.
- Portable Windows build: no Python required.
