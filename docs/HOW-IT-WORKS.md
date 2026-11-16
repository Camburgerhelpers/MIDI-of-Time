# How MIDI of Time works

## The connection

Compatible emulator builds include the **NX2 debug server**. When the emulator is started with `EDEN_NX2_DEBUG_SERVER=127.0.0.1:6545`, it listens on your own PC (localhost only) for one-line JSON requests.

MIDI of Time uses two of them:
- `status`: build, frame rate, and whether the game is running
- `input_sequence`: a list of steps, each one a set of controller buttons and stick positions held for a number of **displayed game frames**

The server is limited to 1,000 steps per request, so songs are sent in pieces of about 8 seconds, always split at a rest. The time lost between pieces was measured at 1 frame, which is inaudible. When a sequence ends or the connection closes, all input is released.

## The instrument model

Measured from microphone and OBS recordings of the remake, with the Classic Ocarina layout, on Fritchii v5.8.4 at 30 FPS. Buttons use the Nintendo names the debug server expects.

| Button | Note | Measured tuning |
|---|---|---|
| R | D5 | +23 cents |
| B | F5 | +9 cents |
| A | A5 | +28 cents |
| Y | B5 | +24 cents |
| X | D6 | +24 cents |

- **L** raises a note by a semitone (+100 cents); **ZL** lowers it by one (−100 cents).
- The **left stick, pushed up or down**, bends the pitch smoothly:
  - −1 = −202 cents
  - −0.5 = −100 cents
  - +0.5 = +88 cents
  - +1 = +192 cents
- Changing the stick, a modifier or the button while a note is held **slurs** to the new note without a new attack.
- The sound dies about 6.8 seconds after the last breath. Only a release of about 4 frames or more counts as a breath; the 1–2-frame gaps between notes do not (measured 2026-11-15).
- A 1-frame release re-attacks a different note; repeated notes get 2 frames. Up to about 15 notes per second register.

## Arranging

1. **Melody**
   - **Smart mode:** every non-drum part is scored in 2-second windows on these factors:
     - How much it is sounding
     - Register
     - Pitch variety
     - Chords
     - Track-name hints

     A switching cost keeps it from hopping between parts. Pauses of 0.4 s or more are filled from the part sounding most at that moment.
   - **One part mode:** the chosen track; when several notes start together, the top one is used.
2. **Range:** each phrase moves by whole octaves into C5–E6. Notes still outside the range are moved individually.
3. **Fingering:** for each note, a cost-based choice of base button, modifier and stick position. It prefers small stick movements, and the same button when slurring.
4. **Timing:** notes are converted to frames at the game's reported frame rate.
   - Connected notes slur.
   - Others get a 1–2 frame release.
   - Smart breathing: before 6.3 s pass without a real breath, a 4-frame breath is placed at the most musical spot in the previous 2.5 s (an existing gap, or the end of the longest note). The frames come out of the note before it, so timing doesn't change.
