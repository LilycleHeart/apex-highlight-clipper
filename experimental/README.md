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

API references: [PyAV container seeking](https://pyav.org/docs/develop/api/container.html) and [PyAV frame timestamps](https://pyav.basswood.io/docs/14.2/api/frame.html).
