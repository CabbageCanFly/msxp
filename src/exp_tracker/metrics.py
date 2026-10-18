"""Sample aggregate process-tree CPU/RSS. Byte counts are supplied by the video relay."""

import os
import threading
import time

import psutil


class ResourceMonitor:
    def __init__(self, *, sample_interval=.25, scope="capture Python + Streamlink + FFmpeg + OCR subprocesses"):
        if not .005 <= sample_interval <= 10:
            raise ValueError("resource sampling interval must be between .005 and 10 seconds")
        self.sample_interval = sample_interval
        self.scope = scope
        self.root = psutil.Process(os.getpid())
        times = self.root.cpu_times()
        self.baseline_cpu = times.user + times.system
        self.started = time.monotonic()
        self.cpu = {}
        self.retired_cpu = 0
        self.sampled_cpu = 0
        self.peak_rss = 0
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _sample(self):
        rss = 0
        try:
            processes = [self.root, *self.root.children(recursive=True)]
        except psutil.Error:
            return
        present = set()
        for process in processes:
            try:
                key = (process.pid, process.create_time())
                present.add(key)
                times = process.cpu_times()
                cpu = times.user + times.system
                if process.pid == self.root.pid:
                    cpu -= self.baseline_cpu
                self.cpu[key] = max(self.cpu.get(key, 0), cpu)
                rss += process.memory_info().rss
            except psutil.Error:
                pass
        # Retain the sampled total, not every exited OCR/capture PID forever.
        for key in self.cpu.keys() - present:
            self.retired_cpu += self.cpu.pop(key)
        self.sampled_cpu = self.retired_cpu + sum(self.cpu.values())
        self.peak_rss = max(self.peak_rss, rss)

    def _run(self):
        while not self.stop_event.wait(self.sample_interval):
            self._sample()

    def snapshot(self):
        # Sample on the monitor thread only to avoid concurrent dict mutation.
        elapsed = time.monotonic() - self.started
        cpu = self.sampled_cpu
        return {"wall_seconds": round(elapsed, 3), "cpu_seconds_sampled": round(cpu, 3),
                "cpu_percent_one_core": round(100 * cpu / elapsed, 2) if elapsed else 0,
                "peak_tree_rss_mib_sampled": round(self.peak_rss / 1024**2, 2),
                "metric_scope": f"{self.scope}; {self.sample_interval * 1000:g}ms samples; short-lived CPU may be missed"}

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=2)
        self._sample()
