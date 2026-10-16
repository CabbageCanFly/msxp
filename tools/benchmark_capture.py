"""Serial mode/interval benchmarks using owned HLS or an authorized Twitch channel.

By default generates ignored fixtures and serves only generated HLS on loopback.
--channel explicitly selects a live Twitch experiment using the same capture CLI.
"""

import argparse
from contextlib import nullcontext
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def build_fixture(directory, ffmpeg="ffmpeg"):
    directory.mkdir(parents=True, exist_ok=True)
    overlay = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, 1010, 1920, 1080), fill=(35, 35, 35, 255))
    font = ImageFont.load_default(size=26)
    for xy, text in [((550, 1030), "LV."), ((610, 1030), "37"),
                     ((730, 1030), "HP"), ((880, 1030), "MP"),
                     ((950, 1030), "EXP"), ((1020, 1030), "123,456 [12.34%]")]:
        draw.text(xy, text, fill="white", font=font)
    overlay.save(directory / "synthetic-hud.png")
    config = {"level": [604/1920, 1026/1080, 656/1920, 1060/1080],
              "exp": [1016/1920, 1026/1080, 1280/1920, 1060/1080]}
    (directory / "config.json").write_text(json.dumps(config), encoding="utf-8")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
               "testsrc2=size=1920x1080:rate=30", "-loop", "1", "-i", str(directory / "synthetic-hud.png"),
               "-filter_complex", "[0:v][1:v]overlay=0:0", "-t", "8", "-c:v", "libx264",
               "-preset", "veryfast", "-threads", "1", "-b:v", "3000k", "-minrate", "3000k",
               "-maxrate", "3000k", "-bufsize", "6000k", "-x264-params", "nal-hrd=cbr",
               "-g", "60", "-keyint_min", "60", "-sc_threshold", "0", "-pix_fmt", "yuv420p",
               str(directory / "source.mp4")]
    subprocess.run(command, check=True, timeout=120)


class LocalHLS:
    def __init__(self, directory, ffmpeg):
        self.directory = directory
        self.ffmpeg = ffmpeg
        self.encoder = None
        self.server = None
        self.thread = None
        self.http_body_bytes = 0
        self.byte_lock = threading.Lock()

    def __enter__(self):
        live = self.directory / f"hls-{time.time_ns()}"
        live.mkdir()
        owner = self
        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def copyfile(self, source, destination):
                try:
                    while chunk := source.read(65536):
                        destination.write(chunk)
                        with owner.byte_lock:
                            owner.http_body_bytes += len(chunk)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(live)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.encoder = subprocess.Popen([
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-re", "-stream_loop", "-1",
            "-i", str(self.directory / "source.mp4"), "-c:v", "copy", "-an", "-f", "hls",
            "-hls_time", "2", "-hls_list_size", "5", "-hls_flags", "delete_segments+temp_file",
            "-hls_segment_filename", str(live / "segment-%06d.ts"), str(live / "index.m3u8")
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 20
        while not (live / "index.m3u8").exists() or len(list(live.glob("*.ts"))) < 3:
            if self.encoder.poll() is not None or time.monotonic() > deadline:
                self.__exit__(None, None, None)
                raise RuntimeError("local_hls_start_failed")
            time.sleep(.1)
        self.url = f"http://127.0.0.1:{self.server.server_port}/index.m3u8"
        return self

    def __exit__(self, *_args):
        if self.encoder and self.encoder.poll() is None:
            self.encoder.terminate()
            self.encoder.wait(timeout=5)
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "artifacts/benchmark")
    parser.add_argument("--intervals", default="30,15,10")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--modes", default="periodic,persistent")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--full-decode", action="store_true")
    parser.add_argument("--reuse-fixture", action="store_true")
    parser.add_argument("--channel", help="Optional authorized live Twitch trial instead of owned local HLS")
    parser.add_argument("--config", type=Path, help="Normalized ROIs for the authorized live layout")
    parser.add_argument("--quality", default="best")
    args = parser.parse_args()
    try:
        intervals = [float(value) for value in args.intervals.split(",")]
    except ValueError:
        parser.error("Intervals must be numbers")
    modes = args.modes.split(",")
    if (any(mode not in {"periodic", "persistent"} for mode in modes)
            or any(not math.isfinite(value) or value < 1 for value in intervals)
            or not 1 <= args.count <= 10000):
        parser.error("Invalid modes or intervals")
    if not shutil.which(args.ffmpeg):
        parser.error("FFmpeg is required")
    args.directory.mkdir(parents=True, exist_ok=True)
    report_path = args.directory / "summary.jsonl"
    report_path.write_text("", encoding="utf-8")
    if args.channel and not args.config:
        parser.error("Provide --config for a live benchmark")
    if not args.channel and not args.reuse_fixture:
        build_fixture(args.directory, args.ffmpeg)
    with nullcontext(None) if args.channel else LocalHLS(args.directory, args.ffmpeg) as source:
        for interval in intervals:
            for mode in modes:
                label = f"{mode}-{interval:g}" + ("-full" if args.full_decode else "")
                output = args.directory / f"{label}.jsonl"
                command = [sys.executable, "-m", "exp_tracker.capture",
                           *(["--channel", args.channel, "--quality", args.quality] if args.channel else ["--hls", source.url]),
                           "--mode", mode, "--interval", str(interval), "--count", str(args.count),
                           "--config", str(args.config if args.channel else args.directory / "config.json"),
                           "--ffmpeg", args.ffmpeg,
                           "--debug-dir", str(args.directory / (label + "-crops"))]
                if args.full_decode:
                    command.append("--full-decode")
                print(f"Running {label}", flush=True)
                before_bytes = source.http_body_bytes if source else None
                with output.open("w", encoding="utf-8") as handle:
                    result = subprocess.run(command, stdout=handle,
                                            timeout=args.count * (interval + 30) + 30)
                records = [json.loads(line) for line in output.read_text().splitlines()]
                observations = [record for record in records if record["type"] == "observation"]
                expected = {"level": 37, "current_exp": 123456, "percentage": 12.34}
                correct = None if args.channel else sum(record.get("recognition", {}).get("reading") == expected for record in observations)
                report = {"run": label, "exit_code": result.returncode,
                                  "correct_readings": correct, "attempts": len(observations),
                                  "server_http_body_bytes": source.http_body_bytes - before_bytes if source else None,
                                  "capture_waits": [r.get("capture_wait_seconds") for r in observations],
                                  **records[-1]}
                print(json.dumps(report), flush=True)
                with report_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(report) + "\n")


if __name__ == "__main__":
    main()
