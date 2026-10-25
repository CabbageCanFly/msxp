"""Fresh Streamlink CLI children with imports shared by a Linux forkserver."""
import multiprocessing
import os
import socket
import subprocess
import sys
import threading
import traceback
import weakref

import psutil


def run_cli(command, output, errors, environment, directory):
    """Runs in a fresh child, never on a capture thread or inside the forkserver."""
    # Imported CLI globals also retain the original stdout/stderr objects.
    os.dup2(output.fileno(),1);os.dup2(errors.fileno(),2)
    saved = sys.stdout, sys.stderr
    out = open(1,'w',encoding='utf-8',buffering=1,closefd=False)
    err = open(2,'w',encoding='utf-8',buffering=1,closefd=False)
    sys.stdout, sys.stderr = out, err
    try:
        os.environ.clear();os.environ.update(environment)
        os.chdir(directory)
        sys.argv = [command[2], *command[3:]]
        if command[2] == 'exp_tracker.streamlink_playback':
            from .streamlink_playback import main
        else:
            from streamlink_cli.main import main
        main()
    except SystemExit as error:
        code=error.code
        if code is not None and not isinstance(code,int):
            try:print(code,file=err)
            except OSError:pass
            code=1
        raise SystemExit(code) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except BaseException:
        # Keep unexpected CLI tracebacks in the bounded capture stderr, not the service journal.
        try:traceback.print_exc(file=err)
        except OSError:pass
        raise SystemExit(1) from None
    finally:
        # The CLI deletes stdout on exit; restore it for multiprocessing's own finalizer.
        sys.stdout, sys.stderr = saved
        for stream in (out, err):
            try:stream.close()
            except OSError:pass
        output.close();errors.close()


class StreamlinkProcess:
    """The Popen operations and byte streams used by VideoSession."""
    def __init__(self, context, command):
        self.args = command;self.stdin = None;self.returncode = None
        self.lock = threading.RLock()
        output, child_output = socket.socketpair()
        errors, child_errors = socket.socketpair()
        self.stdout = output.makefile('rb');self.stderr = errors.makefile('rb')
        output.close();errors.close()
        self.process = context.Process(target=run_cli,
            args=(command, child_output, child_errors, dict(os.environ), os.getcwd()), daemon=True)
        try:
            self.process.start()
            self.pid = self.process.pid
            try:self.native=psutil.Process(self.pid)
            except psutil.NoSuchProcess:self.native=None
        except BaseException:
            if self.process.pid is not None:
                self.process.terminate();self.process.join(timeout=2)
                if self.process.is_alive():self.process.kill();self.process.join(timeout=2)
            if not self.process.is_alive():self.process.close()
            self.stdout.close();self.stderr.close()
            raise
        finally:
            child_output.close();child_errors.close()

    def poll(self):
        with self.lock:
            if self.returncode is None:
                code = self.process.exitcode
                # A dead forkserver can report 255 while its playback child is still alive.
                if code==255 and self.native is not None:
                    try:
                        if self.native.is_running() and self.native.status()!=psutil.STATUS_ZOMBIE:return None
                    except psutil.NoSuchProcess:pass
                self.returncode = code
                if self.returncode is not None:self.process.close()
            return self.returncode

    def wait(self, timeout=None):
        with self.lock:
            if self.poll() is None:
                if self.process.exitcode==255 and self.native is not None:
                    try:self.native.wait(timeout=timeout)
                    except psutil.TimeoutExpired:raise subprocess.TimeoutExpired('streamlink',timeout) from None
                else:self.process.join(timeout=timeout)
                if self.poll() is None:raise subprocess.TimeoutExpired('streamlink', timeout)
            return self.returncode

    def terminate(self):
        with self.lock:
            if self.poll() is None and self.native is not None:
                try:self.native.terminate()
                except psutil.NoSuchProcess:pass

    def kill(self):
        with self.lock:
            if self.poll() is None and self.native is not None:
                try:self.native.kill()
                except psutil.NoSuchProcess:pass

    def stop(self):
        self.terminate()
        try:self.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.kill();self.wait(timeout=2)


class PreloadedStreamlink:
    """One preloader per coordinator; the scheduler still bounds playback children."""
    def __init__(self):
        if sys.platform != 'linux' or 'forkserver' not in multiprocessing.get_all_start_methods():
            raise ValueError('Preloaded Streamlink requires Linux with forkserver support')
        multiprocessing.set_forkserver_preload(['__main__', 'exp_tracker._streamlink_preload'])
        self.context = multiprocessing.get_context('forkserver')
        self.children = weakref.WeakSet();self.lock = threading.Lock();self.closed = False

    def __call__(self, command, *, stdout, stderr):
        if (stdout != subprocess.PIPE or stderr != subprocess.PIPE or len(command) < 3
                or command[:2] != [sys.executable, '-m']
                or command[2] not in ('streamlink', 'exp_tracker.streamlink_playback')):
            raise ValueError('Preloaded Streamlink accepts only the capture CLI and byte pipes')
        with self.lock:
            if self.closed:raise OSError('Preloaded Streamlink is closed')
            try:process = StreamlinkProcess(self.context, command)
            except (OSError,EOFError,RuntimeError):
                raise OSError('Preloaded Streamlink worker startup failed') from None
            self.children.add(process)
            return process

    def check(self):
        command = [sys.executable, '-m', 'streamlink', '--no-config', '--no-plugin-cache',
            '--no-plugin-sideloading', '--webbrowser', 'false', '--loglevel', 'error',
            '--can-handle-url-no-redirect', 'https://www.twitch.tv/streamer_a']
        process = self(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            if process.wait(timeout=30) != 0:raise ValueError('Preloaded Streamlink CLI preflight failed')
        except (OSError, subprocess.SubprocessError):
            raise ValueError('Preloaded Streamlink CLI preflight failed') from None
        finally:
            process.stop();process.stdout.close();process.stderr.close()

    def close(self):
        with self.lock:
            self.closed = True;children = list(self.children)
        for process in children:process.stop()
