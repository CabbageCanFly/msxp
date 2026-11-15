"""Shared pytest setup."""
import subprocess

from exp_tracker.msxp import tesseract


def pytest_report_header():
    """The installed Tesseract differs between machines (5.4.0 on Windows, 5.5.3 from Homebrew) and reads some blurred
    crops differently: shown first, so a test that passes elsewhere and fails here is easy to place."""
    executable = tesseract()
    if not executable:return 'tesseract: not installed (OCR tests skip)'
    try:version = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=10).stdout.splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):version = 'version unreadable'
    return f'tesseract (Python tracker): {version}; /local replays use the vendored tesseract.js-core 7.0.0'
