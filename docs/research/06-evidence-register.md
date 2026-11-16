# Evidence register and publication checklist

**This is a documentary manifest, not a claim that all original evidence has been included in this package.** Historical source summaries were reviewed; original binary artifacts must be located separately by the project owner/Claude and checked against their earlier recorded hashes.

## Four original November 9 OBS recordings

| Source file (historical basename) | Length | Size | Previously recorded SHA-256 |
|---|---:|---:|---|
| `2026-11-09_01-54-44.mp4` | 38.17 s | 22.53 MiB | `b860d8a55290ebd4b96cf9910bdb9da53ea2014fd520915b2f9855a26400d362` |
| `2026-11-09_02-13-16.mp4` | 24.77 s | 21.06 MiB | `7d59b384c2df262d85ebd05dda3324d9fa96e84fdbab26aa4b0e8f59d80ca6f7` |
| `2026-11-09_02-14-03.mp4` | 79.93 s | 58.65 MiB | `aa5ea0aa09dee72590039db4dbcf07a131de57c79479529396b7d330ab226d13` |
| `2026-11-09_02-17-28.mp4` | 40.30 s | 63.07 MiB | `f14759beec9f6a7ff47a70736d7b8078c34c78e184fbdb262a8079f7f021241f` |

These values were copied from the **November 9 master dossier**. **Re-verified 2026-11-15:** all four original files were found in the project creator's OBS capture folder, and their SHA-256 hashes match exactly. The videos are not stored in this repository (large binary files); they can be attached to a release on request.

## Earlier research packages to locate

- `OoT-Ocarina-Baseline-Analysis-2026-11-09.zip`: baseline raw-derived WAV files, five isolated WAVs, CSV, boundary/frequency graphs and a README.
- `OoT-Ocarina-Analog-and-Speed-Analysis-2026-11-09.zip`: additional three recordings analyzed, mono WAVs, dominant-peak CSVs, analog plots, spectrogram, contact sheet, SHA and README.
- November 9 `OoT-Ocarina-Music-Project-Source-2026-11-09` master Markdown dossier (553 lines retrieved from the user's file Library for this preparation; its complete original bytes were not exportable here).
- November 14 `OoT-Ocarina-Calibration-for-Claude-2026-11-14.md` source (134 lines retrieved for this preparation; complete original bytes not exportable here).
- November 14 `OoT-Ocarina-Controller-Map-2026-11-14.json` machine-readable per-note fingering model (699 lines; file source found in the Library but raw bytes were not exportable here). **Do not substitute a generated JSON file for the original.**
- Live Fritchii/MIDI of Time implementation logs, source, user tests and performance captures held in Claude's separate working folder; have Claude review and attach the precise supporting raw logs for articulation/breath/frame timing claims before representing them as independently verified.

## Visual assets audit (2026-11-15)

| Asset | What it is | Status |
|---|---|---|
| `assets/base-note-peaks.png` | Bar chart of the 2026-11-09 FFT peaks vs equal temperament | Reconstructed from recorded numbers; mapping matches the verified Classic layout |
| `assets/a-stick-extremes.png` | Three 2026-11-09 spectral estimates (stick down / centre / up) | Reconstructed; labelled "not a calibrated curve" (the calibrated curve is the 2026-11-14 table in 01) |
| `assets/range-model.png` | Predicted note span B4–F6 around the five measured bases | Model prediction, labelled as such |
| AI-generated twelve-song illustration (not included) | Button sequences for the built-in songs | **Withdrawn: incorrect for the Classic layout.** Verified songs are listed as tables in 01 |

No song tablature images are published. Public song references are built only from the verified mapping and playtested sequences.

## 2026-11-15 breath-test evidence

| File | Notes |
|---|---|
| OBS `2026-11-15 18-09-47.mp4` | Breath test (five release lengths); kept by the project creator, not in repo |
| OBS `2026-11-15 18-15-42.mp4`, `18-17-49.mp4`, `18-18-58.mp4` | Three songs after the breathing fix (about 1 min each); 0 silences of 0.35 s or more |
| `tools/breath-test.py`, `tools/breath-analyze.py`, `tools/song-dropouts.py` | Exact scripts used to generate and analyse them |

Still not located: the two November 9 analysis ZIPs and `OoT-Ocarina-Controller-Map-2026-11-14.json`. They have not been recreated.

## Verify before public release

- [x] Reconcile calibration vs source-study date and explicitly mark **LEFT stick** as current, right-stick hypothesis obsolete. (Nov 14 transfer curve added to 01.)
- [ ] Copy original acoustic WAV/CSV/charts to public evidence directory *only after* verifying provenance, licensing and suitable file sizes; large videos can be linked externally.
- [x] Validate current engine claims: breathing measured 2026-11-15 (02); sequence maximum verified (03). Slur dB figures remain *reported, unreplicated*.
- [ ] Check whether old N64 songs/derivative tab material may be linked rather than reproduced.
- [ ] Label all charts supplied here **reconstructed**.
- [ ] Test public documentation links locally; verify user-facing setup against actual release build.
- [x] Confirm exact emulator fork/tag tested and keep compatibility claims conservative (see [COMPATIBILITY.md](../../COMPATIBILITY.md): only Fritchii v5.8.4 verified).
- [ ] Obtain repository owner's approval before merging, releasing or changing project-level instructions.
