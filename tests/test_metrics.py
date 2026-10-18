from types import SimpleNamespace

from exp_tracker.metrics import ResourceMonitor


def test_exited_children_are_retired_without_unbounded_pid_history(monkeypatch):
    class Process:
        def __init__(self,pid,cpu): self.pid,self.cpu=pid,cpu
        def cpu_times(self): return SimpleNamespace(user=self.cpu,system=0)
        def create_time(self): return self.pid  # PID reuse is still a distinct process.
        def memory_info(self): return SimpleNamespace(rss=100)
        def children(self,recursive): return children
    root=Process(1,0)
    children=[]
    monkeypatch.setattr('exp_tracker.metrics.psutil.Process',lambda _:root)
    monitor=ResourceMonitor(sample_interval=10)
    monitor.close()  # Deterministic manual samples; no competing monitor thread.
    for i in range(200):
        children[:]=[Process(i+2,1)]
        root.cpu=i/10
        monitor._sample()
    assert monitor.snapshot()['cpu_seconds_sampled']==219.9
    assert len(monitor.cpu)<=2  # Only the root and current child, not all past children.
    children.clear();monitor._sample()
    assert monitor.snapshot()['cpu_seconds_sampled']==219.9
    assert len(monitor.cpu)==1
