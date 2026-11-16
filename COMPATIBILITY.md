# Compatibility report — MIDI of Time v0.1.0-alpha

MIDI of Time controls Link through an emulator's **NX2 debug server**. It needs two things:
- The server's `status` command
- Its `input_sequence` command (frame-timed controller input)

It has been **developed and tested with Fritchii only**.

## Verified

Tested end to end: real playback heard, recorded and measured.

| Emulator | Version | Details |
|---|---|---|
| **Fritchii** (Eden/Lichii fork) | **v5.8.4**, commit `4f5c53149b7e17d1c24445f68d79a83a3b2a17f9`, Windows x64 | `status` reports `"build": "Fritchii v5.8.4"`. Tested in 30 FPS mode, Classic Ocarina controls, player 1 controller connected, game started with `-g <game file>`. |

### Launch requirement (verified)

The emulator must be started with this environment variable:

```
EDEN_NX2_DEBUG_SERVER=127.0.0.1:6545
```

- The variable is read at launch, and the server listens on the PC itself only.
- Without it, the server is off. MIDI of Time then shows "Game running without the debug link".
- **Start game** in MIDI of Time sets the variable for that one emulator process only. It doesn't change emulator settings or system-wide variables.

### Debug-server interface used (verified on v5.8.4)

- **Transport:** TCP `127.0.0.1:6545`. One JSON request per line, and one JSON reply per line.
- **`status`:** returns `build`, `scm_rev`, `fps`, `program_id`, `paused`, `presents` and other fields. MIDI of Time reads `build`, `fps` and `program_id`; Ocarina of Time is `0400486024DEC000`.
- **`input_sequence`** with params `{"controller": "player1", "steps": [...]}`:
  - **Steps:** `{"buttons": [...], "left_stick": [x, y], "frames": n}`, with Nintendo button names and stick values from −1 to 1. `n` counts displayed game frames.
  - **Limit:** 1 to 1,000 steps per request. Anything else gets the error `"steps must be an array of 1 to 1000"`.
  - **Reply:** comes after playback, with `frames`, `first_present` and `elapsed_s`. Input is released at the end and on disconnect.
- **The time lost between back-to-back requests was measured at 1 frame.**

## Untested

These have the same interface, judged from the program files, but nobody has played music through them. They may work. MIDI of Time connects to them and shows **"Connected: … (untested)"** in amber.

| Emulator | Versions | Evidence |
|---|---|---|
| Fritchii / Frizti | v2, v3, v4, v4.1, v5, v5.1–v5.8.3 | Each `lichii.exe` contains the debug-server variable, `input_sequence`, and the same 1,000-step and button-name checks (static scan of the official release archives). Not played. |
| Fritchii | anything newer than v5.8.4 | Unknown until tested. |
| Other builds with the NX2 debug server | — | If `status` answers and `input_sequence` exists, MIDI of Time will try them and label them untested. |

The instrument model (pitches, bends, breath) was measured on v5.8.4. Other versions are expected to behave the same, since the Ocarina is the game's own, but that has not been verified.

## Incompatible (as found)

| Emulator | Versions | Reason |
|---|---|---|
| zortos293 Lichii | build-117, build-125, and the build-130-era installation scanned | The debug server is present, but the **`input_sequence` command is not**, so there is no way to send timed Ocarina input. MIDI of Time detects this and shows **"Incompatible emulator"** with an explanation. |
| Any emulator started **without** `EDEN_NX2_DEBUG_SERVER` | — | No server is listening ("Game running without the debug link"). |
| Emulators with no NX2 debug server | e.g. upstream Eden, other Switch emulators | Nothing to connect to. |

zortos293 **build-95** (older) still contained `input_sequence`, so it would count as untested; it's outdated. Newer zortos293 builds may offer input through a different command. Supporting them would mean adding a new connection backend (see below), not changing the MIDI engine.

### How the scan was done

- Read-only.
- Each `lichii.exe` was searched for the strings `EDEN_NX2_DEBUG_SERVER`, `input_sequence`, `steps must be an array of 1 to` and `unknown button {}: want one of`.
- Official Fritchii release zips were read in memory.
- No emulator was run, installed or changed.
- **A static scan is not a test.** Only rows under *Verified* have been played.

## How MIDI of Time decides at runtime

Every few seconds, while idle, it:

1. Sends `status`.
   - No answer: **Game not running**, or **running without the debug link** if the emulator process exists.
   - An answer without a status result: **Incompatible**.
2. Sends an **empty** `input_sequence`. This is a harmless request that a compatible server rejects with its step-count message, and no input reaches the game.
   - The command is missing: **Incompatible**.
3. Compares `build` with the verified list.
   - Match: **Game connected** (green).
   - Anything else: **Connected (untested)** (amber). Playback is allowed.
4. If the running game isn't Ocarina of Time (by `program_id`), adds a warning.

## Adding another emulator later

All emulator traffic goes through `src/midi_of_time/backends.py`. The MIDI engine and arranger produce emulator-neutral steps (button names, stick values, frame counts). A new emulator only needs a backend class with the same four members:
- `probe()`
- `start_sequence(steps)`
- `release()`
- `launch_env`

Add it to `BACKENDS`. No changes to the engine, arranger or UI are needed.
