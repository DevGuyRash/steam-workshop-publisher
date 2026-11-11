"""Real POSIX cancellation journeys; all Steam/GitHub boundaries are fixtures."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import publisher
import test_publisher

ROOT = Path(__file__).resolve().parents[1]
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux process-lifetime assertions')
class Cancellation(unittest.TestCase):
    def setUp(self):
        self.fixture = test_publisher.PublisherCLI()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.steam = self.root / '.local/share/steam-workshop-publisher/steamcmd'
        self.steam.mkdir(parents=True)
        (self.steam / 'username').write_text('test_account')
        self.pidfile = self.root / 'steam.pid'
        self.marker = self.root / 'continued-upload'
        child = f"import pathlib,time; time.sleep(0.8); pathlib.Path({str(self.marker)!r}).write_text('continued'); time.sleep(30)"
        launcher = self.steam / 'steamcmd.sh'
        launcher.write_text(f'''#!/usr/bin/env python3
import os,pathlib,subprocess,sys,time
print('private-log-canary', flush=True)
subprocess.Popen([sys.executable, '-c', {child!r}])
pathlib.Path({str(self.pidfile)!r}).write_text(str(os.getpid()))
time.sleep(30)
''')
        launcher.chmod(0o700)

    def cleanup_group(self):
        if self.pidfile.exists():
            try:
                os.killpg(int(self.pidfile.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def wait_started(self):
        deadline = time.monotonic() + 5
        while not self.pidfile.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.pidfile.exists(), 'fake SteamCMD did not start')
        return int(self.pidfile.read_text())

    def assert_stopped(self, pid):
        self.assertFalse(Path(f'/proc/{pid}').exists(), 'direct SteamCMD child was not reaped')
        time.sleep(.9)
        self.assertFalse(self.marker.exists(), 'SteamCMD descendant continued work')

    def test_actual_upload_folder_and_local_clis_stop_for_all_signals(self):
        self.fixture.prepare()
        content = self.root / 'content'
        content.mkdir()
        (content / 'fixture.txt').write_text('safe fixture')
        commands = [
            ['publisher.py', 'upload', '--stage', str(self.fixture.stage), '--backend', 'steamcmd', '--steamcmd-dir', str(self.steam), '--username', 'test_account'],
            ['folder.py', str(content), '--app-id', '440', '--item-id', '1234', '--backend', 'steamcmd', '--steamcmd-dir', str(self.steam), '--publish'],
            ['local.py', 'exampleowner/examplemod', 'v0.1.1', '--backend', 'steamcmd', '--publish'],
        ]
        for command in commands:
            for signum in SIGNALS:
                with self.subTest(command=command[0], signal=signum):
                    self.pidfile.unlink(missing_ok=True)
                    process = subprocess.Popen([sys.executable, *command], cwd=ROOT,
                        env={**self.fixture.env, 'HOME': str(self.root)},
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    try:
                        pid = self.wait_started()
                        process.send_signal(signum)
                        stdout, stderr = process.communicate(timeout=5)
                        self.assertEqual(process.returncode, 128 + signum, stderr)
                        self.assertNotIn('Published', stdout + stderr)
                        self.assertNotIn('private-log-canary', stdout + stderr)
                        self.assert_stopped(pid)
                    finally:
                        self.cleanup_group()
                        if process.poll() is None:
                            process.kill()
                        process.communicate(timeout=5)

    def test_signal_during_popen_returns_child_before_cancelling_and_restores_handlers(self):
        real_popen = subprocess.Popen
        children = []
        previous = {s: signal.getsignal(s) for s in SIGNALS}
        def interrupted_launch(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            children.append(process)
            self.wait_started()
            self.assertTrue(callable(signal.getsignal(signal.SIGTERM)), 'launch has no cancellation guard')
            os.kill(os.getpid(), signal.SIGTERM)
            os.kill(os.getpid(), signal.SIGHUP)
            return process
        try:
            with patch.object(publisher.subprocess, 'Popen', interrupted_launch):
                with self.assertRaises(SystemExit) as stopped:
                    publisher.send_to_steam(self.root / 'fixture.vdf', '1234', self.steam, 'test_account')
            self.assertEqual(stopped.exception.code, 143)
            self.assertEqual(previous, {s: signal.getsignal(s) for s in SIGNALS})
            self.assert_stopped(int(self.pidfile.read_text()))
        finally:
            self.cleanup_group()
            for child in children:
                child.wait(timeout=5)

    def test_handlers_restored_on_success_failure_timeout_and_spawn_error(self):
        previous = {s: signal.getsignal(s) for s in SIGNALS}
        launcher = self.steam / 'steamcmd.sh'
        for mode in ('success', 'failure', 'timeout', 'spawn-error'):
            with self.subTest(mode=mode):
                if mode == 'timeout':
                    body = 'import time; time.sleep(30)'
                elif mode == 'spawn-error':
                    body = None
                else:
                    body = "print('Success. Published item 1234.')" if mode == 'success' else "print('ERROR! private-log-canary')"
                launcher.write_text('#!/usr/bin/env python3\n' + body if body else 'not executable format')
                launcher.chmod(0o700)
                if mode == 'success':
                    publisher.send_to_steam(self.root / 'fixture.vdf', '1234', self.steam, 'test_account')
                else:
                    with self.assertRaises(RuntimeError) as raised:
                        publisher.send_to_steam(self.root / 'fixture.vdf', '1234', self.steam, 'test_account', timeout=.1)
                    self.assertNotIn('private-log-canary', str(raised.exception))
                self.assertEqual(previous, {s: signal.getsignal(s) for s in SIGNALS})
