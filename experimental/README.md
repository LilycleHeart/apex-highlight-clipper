# Indexed-reader prototype

Opt-in research for reducing video decode work. **The production clipper does not use this module yet.** Sparse pairs do not establish that no combat or result notification occurred between them.

Install the optional dependency in a project environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-experimental.txt
.\.venv\Scripts\python.exe -m unittest test_indexed_reader -v
```

Read-only experiments, with caller-supplied video paths:

```powershell
.\.venv\Scripts\python.exe -m experimental.benchmark_indexed_reader "D:\Recordings\example.mp4" --workers 4 --report validation/indexed.json
.\.venv\Scripts\python.exe -m experimental.benchmark_bursts "D:\Recordings\example.mp4" --workers 4 --span 1/8 --report validation/bursts.json
.\.venv\Scripts\python.exe -m experimental.verify_indexed_bursts "D:\Recordings\example.mp4" --report validation/reference.json
.\.venv\Scripts\python.exe -m experimental.benchmark_remux "D:\Recordings\example.mp4" --duration 60 --report validation/remux.json
```

The reader uses the container index to seek to H.264 keyframe packets. It checks the packet byte position, keyframe flag, decoded PTS and corruption status. Decoder output timestamps are retained rather than pretending these samples form a uniform FPS grid. Only indexed MP4/MOV H.264 is currently supported; unsupported inputs raise explicitly. Each worker owns its own container and decoder.

## Local observations

On the approximately 23-minute, 2560×1080, 120 FPS test source:

| Scope | Time |
| --- | ---: |
| Indexed read of all 672 keyframes, 4 workers × 1 codec thread | 10.22 s |
| Sequential keyframe-only read, 2 codec threads | 35.09 s |
| 672 short bursts, each keyframe plus a frame at least 1/8 s later, 4 workers | 32.27 s |

Both keyframe paths include in-memory scaling and hashing. All 672 timestamps and image hashes matched. The burst experiment produced 1,344 samples, explicitly submitting 11,424 video packets versus 167,814 source index entries. These are IO experiments, **not OCR, combat detection, export or complete one-minute clipping results**. Worker counts differ; OS file caches were not cleared. An earlier run overlapping UI validation was excluded from these timings.

Synthetic-media tests compare keyframes and burst frames to independent sequential decoding. Six real native YUV frames from the first three bursts also matched an independent FFmpeg decode byte for byte. This does not prove whole-video detection equivalence.

Before production adoption, the pipeline still needs bounded in-memory ROI processing, adaptive boundary checks, transient notification coverage, downed/team-continuation validation, and versioned resume support.

The separate remux experiment compares MP4 `faststart` enabled/disabled in ABBA order and removes its own generated clips after verification. On a 60-second, 158 MB section of the same source, the four exports took 0.37/0.34/0.81/1.06 seconds; all five tracks' compressed packets and timestamps matched across outputs, and payloads matched the source. Verification is excluded from these timings. This small, cache-uncontrolled test does not establish a consistent bottleneck or justify changing production export settings.

## Bounded in-memory HUD prototype

`in_memory_hud.py` overlaps independent indexed decoders with numeric OCR, passing images directly to the existing HUD functions. It uses a bounded queue and small ROI batches; no sample JPEGs are written. Rows carry explicit `memory:` IDs, decoded PTS and time bases, and are marked incompatible with the production file-based pipeline.

```powershell
.\.gpu-venv\Scripts\python.exe -m pip install --no-deps -r requirements-experimental.txt
.\.gpu-venv\Scripts\python.exe -m experimental.validate_in_memory_hud "D:\Recordings\example.mp4" --mode keyframes --backend dml --gpu-load fast --report validation/hud-keyframes.json
.\.gpu-venv\Scripts\python.exe -m experimental.validate_in_memory_hud "D:\Recordings\example.mp4" --mode bursts --backend dml --gpu-load fast --report validation/hud-bursts.json
```

Fresh-process measurements with 4 decoder workers and DirectML numeric OCR in fast mode:

| Source | Keyframes + numeric/state HUD | Short bursts + numeric/state HUD |
| --- | ---: | ---: |
| Approximately 6 minutes | 173 frames / 4.39 s | 346 frames / 9.79 s |
| Approximately 23 minutes | 672 frames / 21.14 s | 1,344 frames / 41.17 s |

These include OCR initialization and overlap reading with recognition. They exclude result-toast qualification, weapon-name OCR, boundary refinement, export and verification; OS caches were not cleared. The original batch was paused for these measurements. The bounded queue retained at most 8 pending keyframe tasks, with at most 16 prepared ROI groups per OCR batch.

**Quality is not production-equivalent.** Keyframe-only gaps exceed the production detector's 1.1-second confirmation limit and yield no combat events when passed directly to it. Short bursts reproduce the cached damage/kill totals on the 6-minute sample, but detect only 4 shooting samples versus 35 in the reference and produce different candidate boundaries. Matching totals alone does not validate the clips. Local refinement, transient result-toast coverage, downed/team continuation and versioned resume remain necessary before adoption.

On the 23-minute source, short bursts produce 9 kill increments, matching the reference, but 2,804 damage increments versus 2,713 in the reference, 19 shooting samples versus 117, and different boundaries. These are detector-derived totals, not manually verified ground truth. The prototype has not passed a clipping-quality comparison and is not enabled by default.

API references: [PyAV container seeking](https://pyav.org/docs/develop/api/container.html) and [PyAV frame timestamps](https://pyav.basswood.io/docs/14.2/api/frame.html).
