
import console

import argparse
import sys
from typing import List
from pathlib import Path

from wasi_test_runner.runtime_adapter import RuntimeAdapter
from wasi_test_runner.harness import run_all_tests
from wasi_test_runner.filters import TestFilter
from wasi_test_runner.filters import JSONTestExcludeFilter, UnsupportedWasiTestExcludeFilter
from wasi_test_runner.reporters import TestReporter
from wasi_test_runner.reporters.console import ConsoleTestReporter
from wasi_test_runner.reporters.json import JSONTestReporter


def wasi_test_runner_main(*args) -> int:
	parser = argparse.ArgumentParser(
	 description="WebAssembly System Interface test executor")

	parser.add_argument(
	 "-t",
	 "--test-suite",
	 required=True,
	 nargs="+",
	 help="Locations of suites (directories with *.wasm test files).",
	)
	parser.add_argument(
	 "-f",
	 "--exclude-filter",
	 required=False,
	 nargs="+",
	 default=[],
	 help="Locations of test exclude filters (JSON files).",
	)
	parser.add_argument("-r",
	                    "--runtime-adapter",
	                    required=True,
	                    help="Path to a runtime adapter.")
	parser.add_argument(
	 "--json-output-location",
	 help=
	 "JSON test result destination. If not specified, JSON output won't be generated.",
	)
	parser.add_argument(
	 "--disable-colors",
	 action="store_true",
	 default=True,
	 help="Disables color for console output reporter.",
	)
	options = None
	if len(args) > 0:
		options = parser.parse_args(args)
	else:
		options = parser.parse_args()

	reporters: List[TestReporter] = [
	 ConsoleTestReporter(not options.disable_colors, verbose=True)
	]
	if options.json_output_location:
		reporters.append(JSONTestReporter(options.json_output_location))

	filters: List[TestFilter] = [UnsupportedWasiTestExcludeFilter()]
	for filt in options.exclude_filter:
		filters.append(JSONTestExcludeFilter(filt))

	return run_all_tests(
	 [RuntimeAdapter(options.runtime_adapter)],
	 options.test_suite,
	 reporters,
	 filters,
	)


if __name__ == "__main__":
	console.clear()
	test_suite_path = Path("./wasi_testsuite/wasm32-wasip").absolute()
	test_suite_path = str(test_suite_path)
	test_adapter_path = Path(
	 "./wasi_testsuite/jscore_runtime_adapter.py").absolute()
	test_adapter_path = str(test_adapter_path)
	print(test_suite_path)
	wasi_test_runner_main("-t", test_suite_path + "1", test_suite_path + "3", "-r", test_adapter_path)

