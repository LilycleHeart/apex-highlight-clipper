"""Compare MP4 header relocation cost with identical stream-copy settings.

Writes only temporary benchmark outputs beside the requested report. Does not
change production export settings. Timings exclude packet verification.
"""
import argparse
import json
import math
import subprocess
import time
import uuid
from pathlib import Path

from apex_clipper import probe, tool
from verify_export import packets, subsequence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--duration', type=float, default=60)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    report_path = args.report.resolve()
    if report_path == source or report_path.exists():
        raise ValueError('Report must be a new file, distinct from the source')
    if not math.isfinite(args.start) or not math.isfinite(args.duration) or args.start < 0 or args.duration <= 0:
        raise ValueError('Start and duration must be finite; start >= 0, duration > 0')
    identity = source.stat()
    meta, _ = probe(source)
    end = min(float(meta['format']['duration']), args.start + args.duration)
    if args.start >= end:
        raise ValueError('Start is outside the source')
    source_streams = [s for s in meta['streams'] if s['codec_type'] == 'video'][:1]
    source_streams += [s for s in meta['streams'] if s['codec_type'] == 'audio']
    report_path.parent.mkdir(parents=True, exist_ok=True)
    directory = report_path.parent / ('remux-' + uuid.uuid4().hex)
    directory.mkdir()
    outputs = []
    runs = []
    try:
        # Reverse the second pair to reduce simple warm-cache/order bias.
        for index, faststart in enumerate([True, False, False, True]):
            output = directory / f'{index}.mp4'
            outputs.append(output)
            command = [tool('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
                       '-ss', str(args.start), '-i', str(source), '-t', str(end - args.start),
                       '-map', '0:v:0', '-map', '0:a?', '-map_metadata', '0', '-c', 'copy',
                       '-avoid_negative_ts', 'make_zero']
            if faststart:
                command += ['-movflags', '+faststart']
            started = time.perf_counter()
            subprocess.run(command + [str(output)], capture_output=True, check=True)
            runs.append({'faststart': faststart, 'seconds': time.perf_counter() - started,
                         'bytes': output.stat().st_size})
        reference = packets(outputs[0])
        # Packet fields include compressed-payload SHA256, PTS/DTS, duration and flags.
        equal = all(packets(path) == reference for path in outputs[1:])
        source_packets = packets(source, (max(0, args.start - 2), min(float(meta['format']['duration']), end + 2)))
        source_matches = []
        for output_index, stream in enumerate(source_streams):
            expected = [p['data_hash'] for p in source_packets.get(stream['index'], [])]
            actual = [p['data_hash'] for p in reference.get(output_index, [])]
            source_matches.append(bool(actual) and subsequence(expected, actual) is not None)
        unchanged = (identity.st_size, identity.st_mtime_ns) == (source.stat().st_size, source.stat().st_mtime_ns)
        passed = equal and all(source_matches) and len(reference) == len(source_streams) and unchanged
        result = {'passed': passed, 'runs': runs, 'start': args.start, 'duration': end - args.start,
                  'all_output_packets_and_timestamps_equal': equal, 'source_stream_matches': source_matches,
                  'source_unchanged': unchanged,
                  'scope': 'Stream-copy export only; same disk; ABBA order; OS cache uncontrolled; verification excluded from timings'}
        report_path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, indent=2))
        if not passed:
            raise SystemExit(1)
    finally:
        # Exact generated files only, no recursive deletion or source cleanup.
        for output in outputs:
            if output.parent.resolve() != directory.resolve():
                raise ValueError('Unexpected benchmark output location')
            output.unlink(missing_ok=True)
        directory.rmdir()


if __name__ == '__main__':
    main()
