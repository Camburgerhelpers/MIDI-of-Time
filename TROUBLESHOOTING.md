# Troubleshooting

The status in the top right of the window tells you where you are:

| Status | Meaning | What to do |
|---|---|---|
| **Game connected** (green) | The debug server is answering. | Take out the Ocarina, then press Play. |
| **Game not running** | No emulator was found. | Press **Start game**. |
| **Connected: … (untested)** (amber) | An emulator build other than the verified Fritchii v6.1 / v5.8.4 answered with the expected debug server. | Playback is allowed, but untested. Please report how it goes. |
| **Incompatible emulator** (red) | The debug server answered, but without the input command MIDI of Time needs (for example, current zortos293 builds). | Use Fritchii v6.1 or v5.8.4 (see COMPATIBILITY.md). |
| **Stopped** (amber), *"you used D-pad left/right"* | The kill switch stopped playback because you put the Ocarina away or opened the song menu. | Take the Ocarina out again, then press Play. |
| **Game running without the debug link** (amber) | The emulator is running, but it was started without the debug server. | Close the emulator and press **Start game** in MIDI of Time, or start it yourself with the environment variable (see README). |

## Common problems

**Link doesn't play, but the status is green.**
- Is Link holding the Ocarina, in its note-playing mode?
- Is a controller connected as **Player 1**? The game ignores injected input otherwise. The app says *"Make sure your controller is connected as Player 1."*
- Are the in-game Ocarina controls set to **Classic**?

**The game's menus go crazy.**
- You pressed Play while Link wasn't holding the Ocarina, or **Auto-play the next song** started a song while you were in a menu.
- Press **Stop** (or **D-pad down** / **D-pad left/right** on the controller), which releases every button. Untick Auto-play while you're browsing.

**The D-pad kill switch / shortcuts do nothing.**
- They need an XInput controller (Xbox-style). Check `data\midi-of-time.log`: it says `controller kill switch: on` or `no XInput controller found, off`.
- Shortcuts only work while a song is playing or paused. They never start a song, because the app can't tell whether the Ocarina is out.

**Wrong notes or wrong octave everywhere.**
- Check that the in-game Ocarina controls are **Classic**.
- Very wide melodies are moved by octaves into Link's range. That's expected.

**Link plays the accompaniment instead of the tune.**
- Try **One part**, or open **Advanced…** and pick another part.
- Press **Apply** to hear it, then **Save as this song's default**.

**Short dropouts in long songs.**
- Link takes a short breath (~0.13 s) at least every ~6.3 s; that is intended. If the sound drops out for seconds at a time, please report the song and attach `data\last-playback.txt`.
- Every play writes `data\last-playback.txt`, which lists planned silences and timing. Please attach it to bug reports.

**"This emulator build answered but did not accept the input."**
- Your emulator has a debug server, but not the expected one. Only the build listed in the README is tested.

**Start game can't find the emulator.**
- Open **Advanced… → Settings…** and set the emulator path. Use the emulator's main `.exe` (for Fritchii v6, `fritchii.exe`; for v5, `lichii.exe`). On v6, starting the small `lichii.exe` also works: it forwards to `fritchii.exe` with the same settings.

**Search MIDI folder is slow.**
- Without Everything, the first search scans the whole folder; later searches are fast.
- Install [Everything](https://www.voidtools.com/) to make it instant. MIDI of Time finds `es.exe` automatically when it's on your PATH or in `C:\Program Files\Everything`.

**The phone remote won't load.**
- Is the phone on the same Wi-Fi as the PC? Was the remote enabled in Settings, and MIDI of Time restarted afterwards?
- Did Windows Firewall get permission for **Private networks**?
- Some VPN apps block local-network access. Enable their "allow LAN" option, or disconnect the VPN.
- The PC's address can change. The current one is always shown at the bottom of the window.

**Windows SmartScreen warns about the program.**
- The alpha build isn't code-signed. Choose **More info → Run anyway** only if you downloaded it from the official release page.

## Where things are

The program uses a portable layout: everything lives next to `MIDI of Time.exe`.
- `Songs\`: your MIDI files and any per-song settings (`*.ocarina.json`)
- `data\settings.json`: settings, favorites and the remote PIN
- `data\midi-of-time.log`: the log
- `data\last-playback.txt`: details of the last song played

If that folder can't be written to (for example, inside Program Files), MIDI of Time uses `%LOCALAPPDATA%\MIDI of Time` instead. To reset everything, delete the `data` folder.

## Reporting bugs

Include:
- Emulator name and version
- Windows version
- 30 or 60 FPS mode
- `data\midi-of-time.log`
- `data\last-playback.txt`. Its first line shows the song's file path, which can include your Windows user name; edit that out if you like.
- The MIDI file, if you're allowed to share it
