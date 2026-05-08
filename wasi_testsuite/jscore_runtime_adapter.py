
from jscore_runtime import *


import subprocess
import os
import shlex
import sys
from pathlib import Path
from typing import Dict, List, Tuple
import importlib



def get_name() -> str:
	return "jscore_runtime"

def get_version() -> str:
	# ensure no args when version is queried
	return jscore.version

def get_wasi_versions() -> List[str]:
#	return ["wasm32-wasip1", "wasm32-wasip3"]
	return ["wasm32-wasip1"] #, "wasm32-wasip3"]

def get_wasi_worlds() -> List[str]:
	return ["wasi:cli/command"]

import glob
import json
import os
import re
import shutil
import subprocess
import socket
import time

from datetime import datetime
from pathlib import Path
from typing import List, NamedTuple, Tuple, Dict, Any, IO

import requests

from wasi_test_runner.filters import TestFilter
from wasi_test_runner.runtime_adapter import RuntimeAdapter
from wasi_test_runner.test_case import (
	Result, Failure, WasiVersion, Config,
	TestCase, TestCaseRunnerBase, TestCaseValidator,
	# Operation types
	Run, Read, Write, Wait, Send, Recv, Connect, Request, Kill
)
from wasi_test_runner.reporters import TestReporter
from wasi_test_runner.test_suite import TestSuite, TestSuiteMeta


class Manifest(NamedTuple):
	name: str
	wasi_version: WasiVersion

def _append_stdout_and_stderr(msg: str, out: str | None, err: str | None) -> str:
    if out:
        msg += f"\n\n==STDOUT==\n{out}"

    if err:
        msg += f"\n\n==STDERR==\n{err}"

    return msg


def _cleanup_test_output(host_dir: Path) -> None:
    for f in host_dir.glob("**/*.cleanup"):
        if f.is_file():
            f.unlink()
        elif f.is_dir():
            shutil.rmtree(f)

class JSCoreRuntimeWasiTestCaseRunner(TestCaseRunnerBase):
	# pylint: disable-msg=too-many-instance-attributes
	_test_path: str
	_wasi_version: WasiVersion
	_runtime: RuntimeAdapter
	_proc: subprocess.Popen[Any] | None
	_cleanup_dirs: List[Path]
	_pipes: Dict[str, IO[str]]
	_sockets: Dict[str, socket.socket]
	_last_argv: List[str]
	_http_server: str | None

	def __init__(self, config: Config, test_path: str, wasi_version: WasiVersion, runtime: RuntimeAdapter) -> None:
		TestCaseRunnerBase.__init__(self, config)
		self._test_path = test_path
		self._wasi_version = wasi_version
		self._runtime = runtime
		self._proc = None
		self._cleanup_dirs = []
		self._pipes = {}
		self._sockets = {}
		self._last_argv = []
		self._http_server = None
		self._runtime = None
		self._context = None

	def _add_cleanup_dir(self, d: Path) -> None:
		_cleanup_test_output(d)
		self._cleanup_dirs.append(d)

	def _wait(self, timeout: float | None) -> Tuple[int, str, str]:
		proc = self._proc
		assert proc is not None
		out, err = proc.communicate(timeout=timeout)
		self._proc = None
		return proc.returncode, out, err

	def fail_unexpected(self, msg: str) -> None:
		self._failures.append(Failure.unexpected(msg))

	def fail_expectation(self, msg: str) -> None:
		self._failures.append(Failure.expectation(msg))

	def has_failure(self) -> bool:
		return bool(self._failures)

	def add_socket(self, name: str, sock: socket.socket) -> None:
		self._sockets[name] = sock

	def add_pipe(self, name: str, pipe: IO[str]) -> None:
		self._pipes[name] = pipe

	def get_socket(self, name: str) -> socket.socket:
		assert name in self._sockets
		return self._sockets[name]

	def get_pipe(self, name: str) -> IO[str]:
		assert name in self._pipes
		return self._pipes[name]

	def last_argv(self) -> List[str]:
		return self._last_argv

	def get_http_server(self) -> str | None:
		if self._http_server:
			return self._http_server
		line = self.get_pipe('stderr').readline().strip()
		start = line.find('http://')
		if start < 0:
			self.fail_unexpected(f"Expected 'http://' in first line, got {line}")  # noqa: E231
			return None
		# The server URL starts with http:// and ends at EOL or whitespace.
		self._http_server = line[start:].split()[0]
		return self._http_server

	def do_run(self, run: Run) -> None:
		#print("run", os.pipe())
		for (host, _guest) in run.dirs:
			self._add_cleanup_dir(host)
		proposals = self.config.proposals_as_str()
		env = run.env
		dirs = run.dirs
		argv = [ self._test_path ] + run.args
		world = self.config.world, 
		version = self._wasi_version
		self._last_argv = argv
		
		self._runtime = wasm_runtime() 
		self._context = self._runtime.context()
		try:
			args = run.args
			self._proc = self._context.run_async(self._test_path, *args)
			stdin, stdout, stderr = self._proc.stdin, self._proc.stdout, self._proc.stderr
			assert stdin is not None
			assert stdout is not None
			assert stderr is not None
			self.add_pipe('stdin', stdin)
			self.add_pipe('stdout', stdout)
			self.add_pipe('stderr', stderr)
		except Exception as e:
			self.fail_unexpected(f"Failed to start process: {e}")

	def do_read(self, read: Read) -> None:
		stream = self.get_pipe(read.id)
		expected_length = len(read.payload)
		payload = stream.read(expected_length)
		if payload != read.payload:
			self.fail_expectation(f"{read} {read.id} failed: expected {read.payload}, got {payload}")

	def do_write(self, write: Write) -> None:
		stream = self.get_pipe(write.id)
		stream.write(write.payload)
		stream.flush()

	def do_wait(self, wait: Wait) -> None:
		try:
			exit_code, out, err = self._wait(5)
			if wait.exit_code != exit_code:
				msg = f"{wait} failed: expected {wait.exit_code}, got {exit_code}"
				msg = _append_stdout_and_stderr(msg, out, err)
				self.fail_expectation(msg)

		except subprocess.TimeoutExpired:
			self.fail_expectation(f"{wait} failed: timeout expired")

	def do_connect(self, conn: Connect) -> None:
		# Discover the port.
		line = self.get_pipe('stdout').readline().strip()
		match line.split(':'):
			case [host, port_str] if port_str.isnumeric():
				port = int(port_str)
				sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				try:
					sock.connect((host, port))
					self.add_socket(conn.id, sock)
				except (socket.timeout, ConnectionRefusedError, OSError) as e:
					sock.close()
					self.fail_unexpected(
						f"{conn}: Could not connect to {host}:{port}: {e}")  # noqa: E231
					return
			case _:
				self.fail_unexpected(
					f"{conn}: Expected address information to be available as <host>: <port>, found {line}")
				return

	def do_send(self, send: Send) -> None:
		sock = self.get_socket(send.id)
		try:
			sock.sendall(send.payload.encode('utf-8'))
		except (OSError, socket.error) as e:
			self.fail_unexpected(f"{send}: Failed to send data: {e}")

	def do_recv(self, recv: Recv) -> None:
		sock = self.get_socket(recv.id)
		try:
			response_bytes = sock.recv(len(recv.payload))
			response = response_bytes.decode('utf-8')
			if response != recv.payload:
				self.fail_unexpected(f"{recv}: Expected {recv.payload}, got {response}")
		except (OSError, socket.error) as e:
			self.fail_unexpected(f"{recv}: Failed to receive data: {e}")
		except UnicodeDecodeError as e:
			self.fail_unexpected(f"{recv}: Failed to decode response: {e}")

	def do_request(self, req: Request) -> None:
		# pylint: disable-msg=too-many-return-statements
		http_server = self.get_http_server()
		if http_server is None:
			return
		url = http_server + req.path
		try:
			response = requests.request(req.method, url, timeout=5)
		except requests.exceptions.Timeout:
			self.fail_unexpected(f"{req}: Timeout waiting for response")
			return
		except requests.exceptions.RequestException as e:
			self.fail_unexpected(f"{req}: Failed to make request: {e}")
			return
		if response.status_code != req.response.status:
			self.fail_unexpected(
				f"{req}: Expected status {req.response.status}, got {response.status_code}")
			return
		for h, expected in req.response.headers.items():
			if h not in response.headers:
				self.fail_unexpected(f"{req}: Response missing header {h}")
				return
			actual = response.headers[h]
			if actual != expected:
				self.fail_unexpected(
					f"{req}: Expected response header {h}={expected}, got {actual}")
				return
		if response.text != req.response.body:
			self.fail_unexpected(
				f"{req}: Expected response body '{req.response.body}', got '{response.text}'")
			return

	def do_kill(self, kill: Kill) -> None:
		try:
			proc = self._proc
			assert proc is not None
			proc.send_signal(kill.signal)
		except OSError as e:
			self.fail_unexpected(f"{kill}: Failed to send {kill.signal}: {e}")

	def do_cleanup(self, successful: bool) -> None:
		if self._proc:
			self._proc.kill()
			try:
				_, out, err = self._wait(timeout=5)
				self.fail_unexpected(
					_append_stdout_and_stderr("", out, err))
			except subprocess.TimeoutExpired:
				self.fail_unexpected(
					f"Timeout expired after killing proc {self._proc}")
				self._proc = None
		if self._context:
			self._context.destroy()
			self._context = None
		if self._runtime:
			self._runtime.destroy()
			self._runtime = None
		for d in self._cleanup_dirs:
			_cleanup_test_output(d)
		self._cleanup_dirs = []

def get_runner_class():
	return JSCoreRuntimeWasiTestCaseRunner
