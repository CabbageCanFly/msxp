// The text reader runs one job at a time. `exclusive(task)` returns the task's result, or null when it
// cannot run: a scan that is still running makes the next tick skip. EXP scans come first: a scan waits
// for a background job (one pickup read, ~0.1 s), and background jobs give way while a scan waits
// (measured: letting pickup reads make scans skip left EXP tracking without readings for minutes).
export function readerLock() {
  let holder = null, running = null, scanWaiting = false;
  return async function exclusive(task, {background = false} = {}) {
    if (background ? holder || scanWaiting : holder === 'scan' || scanWaiting) return null;
    if (holder) {
      scanWaiting = true;
      try { await running.catch(() => {}); } finally { scanWaiting = false; }
      if (holder) return null;
    }
    holder = background ? 'background' : 'scan';
    running = (async () => task())();
    try { return await running; } finally { holder = null; running = null; }
  };
}
