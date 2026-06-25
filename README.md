# pythonista-jscore-runtime
## JSCore Runtime Framework - Execute JavaScript and WebAssembly in Pythonista 3 natively on iOS with JavaScriptCore.
JSCore Runtime Framework is an experiment in pushing the boundaries of the Python environment and language features in the [Pythonista 3 IDE](https://omz-software.com/pythonista/) and apps developed with it on iOS. 
It is an extensive Python 3 mapping of the JavaScriptCore Objective-C and C-APIs via objc-util. Implementing closely analogous Python integrations, wrapping and interop for evaluating JavaScript and WebAssembly in the JavaScriptCore execution environment from Python 3 applications and scripts. Focused also from a point of view of being a serious attempt to extend vanilla Pythonista 3 to ultimately support Python packages and modules with compiled extensions that can be cross-compiled reliably into WebAssembly. 

The projects overall long term goals aim to support three core capabilities/features:
- Evaluate/execute JavaScript and WebAssembly with seamless Python interop as a standalone library for Pythonista 3 based Python 3 apps.
- Compile, bundle, import and run custom source code and third party components extensibly with WebAssembly and JavaScript.
- Support Python packages/modules with extensions which can be cross-compiled to WebAssmembly from languages such as C. 

Aiming also to be compatible with WebAssembly in Python 3 ongoing through backporting/compliance/support for proposed language-functionality such as [PEP-0816](https://peps.python.org/pep-0816/). Ideally Python libraries with extension modules ultimately become installable, through as close to a standard mechanism as possible, importable into Pythonista 3 as-is without modification or with only minimal changes and boilerplate.

## Features - Stable
- Powerfully extends Pythonista 3 with modern combined JavaScript and WebAssembly, interoperation and execution support.
- Extensive bi-directional type marshalling and conversion supporting primitives, functions, typed arrays, lists, dicts and complex objects.
- Performant, efficient and accurate with values handled in round-tripable formats, and using direct low level memory access where applicable.
- Comprehensive mapping of Apple's [JavascriptCore Objective-C API](https://developer.apple.com/documentation/javascriptcore?language=objc).
- Zero external dependencies in Pythonista, implented as a single file Python module, using just `objc-util` and the python standard library. 
- Cross-compatible with `rubicon.objc` by [BeeWare](https://github.com/beeware/rubicon-objc) so should also be supported in any iOS environment with Python 3.10 or above.

## Features - Unstable
- WebAssembly System Interface at [(WASI) snapshot preview 1](https://github.com/WebAssembly/WASI/tree/wasi-0.1) now has partial support and passes a number of the official [WebAssembly/wasi-testsuite](https://github.com/WebAssembly/wasi-testsuite) tests. 
	- Python WASM components shimming from Python classes mechanism implemented with JavaScriptCore function callbacks. Imports may be satisfied with Python or JavaScript functions. 
	- Folder mounting with near complete file system access to Pythonista's sandboxed file system with wasi fds (file descriptors) manipulation functions. (Note: Symlinks are not currently supported with `path_symlink`).
	- System clocks passthrough to real iOS system clocks with Python `time` module, realtime, monotic, process_cputime and thread_cputime.(process_cputime and thread_cputime are equivalent due to implementation.)
	- Obtain secure random bytes from `random_get` with `secrets.token_bytes`.
- Run `.wasm` file executables with standard `_start` functions in simulated isolated process environments.
	- Implemented with `threading.Thread` using a subprocess compatible interface.
	- Supports passing program arguments, environment variables, standard streams stdin, stdout, stderr.
- **Wasm/Wasi current limitations**
	- Socket functions `sock_accept`, `sock_recv`, `sock_send` and `sock_shutdown` are not implemented currently. 
	- Concurrent polling with `poll_oneoff` is not implented current affecting programs requiring `select` and/or `pselect` to function within the program and for asynchronous code, message loops and other polling applications. 
	- Application binary interface(s) support is limited and not complete, imports may not be resolved correctly, complex programs may behave unexpectedly, or may not run at all or also crash Pythonista.
	- Compiling/cross compiling applications for Pythonista is currently limited and/or has incomplete support. A reliable means of compiling WebAssembly / .wasm executables for Pythonista specifically hasn't yet been completely determined. 
	- Some general advice would be keep compilation flags simple, avoid any extension flags and direct host memory optimisation or anything which would otherwise be restricted in iOS sandboxing. 
	- Single file / statically linked executables are simplest to get running currently. Simple programs such as the wasi_testsuite tests, with .wasm executables that can be sourced freely online have been used for testing so far. WebAssembly is interpreted and run directly in JavaScriptCore, so it should be fairly close to compiling .wasm executables for browsers or other JavaScriptCore based runtimes. 

A few (very) simple examples:

```python

from jscore_runtime import *

context = jscore.javascript() 

context.eval('function hello_world () { return "hello world"; }')
print(context.js.hello_world())
context.js.value_from_python = ["hello", "from", "python", 1, 2.2, 3.333333, {"object":"value", "nested":{"obj":["array", [], {}]}}]
print(context.eval('value_from_python[2] = "javascript"; value_from_python;').value)

context.js.call_python = lambda v: print(f"hello from python {v}!")
context.eval('call_python("called from javascript");')
# output: 
# hello world
# ['hello', 'from', 'javascript', 1, 2.2, 3.333333, {'object': 'value', 'nested': {'obj': ['array', [], {}]}}]
# hello from python called from javascript!

context = jscore.webassembly()
# based on https://developer.mozilla.org/en-US/docs/WebAssembly/Guides/Using_the_JavaScript_API#loading_wasm_modules_in_javascript
module = wasm_module.from_file('./simple.wasm')
module.imports.my_namespace.imported_func = lambda *v: print(*v)
context.load_module(module)
module.exports.exported_func() 

# output:
# 42
# (written to Pythonista's terminal via imported_func)

# run .wasm program with _start function asynchronously in a new thread
process = context.run_async('./program.wasm', 'args', 'for', 'program', env = {"envVar":"value"}, dirs = ['./preopen_dir'])
# starts the process then returns a representation with a subprocess-like interface allowing interaction via stdin, stdout and stderr

```

## Installation

Install with pip using [StaSh](https://github.com/ywangd/stash).

Or install with pip using pipTerminal from [Pythonista pip configration tool](https://github.com/CrossDarkrix/Pythonista3_pip_Configration_Tool/blob/main/README_EN.md).

```bash
pip install pythonista-jscore-runtime 
```

Or download [jscore_runtime.py](https://github.com/M4nw3l/pythonista-jscore-runtime/blob/v0.0.8/jscore_runtime.py) from the latest v0.0.x release tag and copy to your site-packages folder.

### Installation in other iOS apps

An objective-c bridge is required to use jscore-runtime so one of `objc_util` or `rubicon.objc` must be available or installed in the environment beforehand.
- **Rubicon ObjC**

Install or update to the latest version (>= v0.5.4) using Pip.


```
pip install rubicon-objc
```

- **objc_util**
This module comes as part of the built in standard library components with Pythonista 3.
It can be obtained from the app in the standard library site-packages folder from in Pythonista 3. 
Or the code can also be found by searching for "objc_util".

## Usage

### Javascript Runtime
JSCore Runtime supports both the context management and explicit create/destroy usage paradigms. 
It provides singletons for convenience evaluation and while also allows more explicit management of multiple virtual machines and contexts with its class model.

A runtime context singleton and optionally runtime singleton can be obtained from the `jscore` static class.

```python
context = jscore.javascript()

# or shorthand
context = jscore.js()


# obtain javascript_runtime singleton
runtime = jscore.runtime(javascript_runtime)
```

By default if no runtime class is specified a `javascript_runtime` with a virtal machine lifetime of the program is returned.

```python
runtime = jscore.runtime()
```

A runtime class can also be instantiated independently. On creation it will contain a pointer to its own independent JSVirtualMachine instance.

```python
runtime = javascript_runtime()
``` 

A context is required to evaluate code. A context instance is onbtained from an existing runtime instance:

```python
context = runtime.context()
```

The context type matches the runtime type. e.g `javascript_runtime` returns `javascript_context` instances. Similarly to runtimes, contexts are independent of one another such that the state of one context is distinct to and isolated from another unless it is explictly configured for sharing via context groups. 

A context may evaluate javascript with several javascript evaluation function variants:

```python
# general purpose javascript string evaluation function
context.eval(jsSourceCode) 
# returns:
# javascript_eval_result {"value": [python js value representation] or None , "exception": exception string or None }

# module loader based javascript evaluation functions
context.eval_source(jsSourceCode, sourceUrl="./virtual_path/to/file")
context.eval_file(".path/to/js-file.js")

# all return:
# javascript_eval_result {"value": [python js value representation] or None , "exception": exception string or None }
```

### Shared context singleton convenience accessors
As the most typical standard use case is being able to just load and execute some arbitrary JavaScript source code or pre-compiled Web Assembly from Python, that also may interact with one another. A set of convenience accessors to obtain contexts with a shared global scope are provided from the `jscore` static class. They come in both long-form and short-hand variants. 

```python
from jscore_runtime import *

js_context = jscore.javascript()

# short-hand
js_context = jscore.js()

js_context.js.hello = "javascript"

wasm_context = jscore.webassembly()
# short-hand
wasm_context = jscore.wasm()

# all variables in the contexts global scopes are shared
print(wasm_context.js.hello)
# prints javascript

wasm_context.js.hello = "wasm"

print(js_context.js.hello)
# prints wasm

```

They use the same runtime instances returned by `jscore.runtime` sharing the same underlying `JSVirtualMachine` and a single `JSContext` instance between them. The `javascript_context` and `wasm_context` objects returned by `javascript_runtime` and `wasm_runtime` instances craated by `jscore.runtime` respectively, are also sharing these same instances. Although separated runtime environments are also possible to create, they are not necessary for a standard use case. JavaScriptCore's API allows construction of context groupings but note there are some additonal considerations for working with data / memory between them. For example, attempting to pass a `JSValue` to a context that didn't create it, is undefined behaviour and will most likey cause a crash.

Additionally `wasm_runtime` and `wasm_context` track only their own instances that have been created from Python. WebAssembly instance instantiated through JavaScript evaluation may still be accessed however when passed to Python or if they are made accessible from the global scope. 

### context.js accessor
A `javascript_context` provides a `js` property which allows access to the javascript contexts global object in a 'python-esque' interface.
Most simple python values may be retrieved and set through this accessor. It follows JavaScript access rules, and cannot subvert them, e.g. setting a const value fails with an exception. All read/write variables may otherwise be set and manipulated.

```python
context.js.number = 10
context.js.double = 1.1
context.js.array = []
context.js.object = {}

context.js.biginteger = javascript_bigint(12345678910)

```
Typed arrays values are provided in direct access wrappers automatically and may be used efficiently as like Python collections.

```python
# typed arrays
uint8Array = context.eval("new Uint8Array([0,97,115,109,1,0,0,0]);").value
uint16Array = context.eval("new Uint16Array([0,97,115,109,1,0,0,0]);").value
uint32Array = context.eval("new Uint32Array([0,97,115,109,1,0,0,0]);").value
		
int8Array = context.eval("new Int8Array([0,97,115,109,1,0,0,0]);").value
int16Array = context.eval("new Int16Array([0,97,115,109,1,0,0,0]);").value
int32Array = context.eval("new Int32Array([0,97,115,109,1,0,0,0]);").value
		
float32Array = context.eval("new Float32Array([0,97,115,109,1,0,0,0]);").value
flot64Array = context.eval("new Float64Array([0,97,115,109,1,0,0,0]);").value
		
bigUint64Array = context.eval("new BigUint64Array([BigInt(1),BigInt(0),BigInt(0),BigInt(0)]);").value
bigInt64Array = context.eval("new BigInt64Array([BigInt(1),BigInt(0),BigInt(0),BigInt(0)]);").value

# index
typedValue = typedArray[0]
# typed value is returned as an equivalent ctype value 

# iteration directly on values in memory
for typedValue in typedArray:
	pass

# full javascript functions interface support
slicedArray = typedArray.slice(1)

# obtain raw bytes
typedArrayBytes = typedArray.to_bytes()

# copy as raw bytes 
typedArray.copy_to(address)
```

Python functions can be specified as functions callable from javascript:

```python
context = jscore.js()

def python_print(text):
	print(text)
	
context.js.python_print = python_print

# call from javascript
context.eval('python_print("hello from javascript");')
# call from python as javascript_function calling back to python
context.js.python_print("hello via javascript")

# any callable may be specified
context.js.python_fn = lambda text: print(text)

# values can be returned to javascript
context.js.python_val = lambda: {"str": "Hello from python", "num":10, "list":[1,2,3]}
# and back to python
context.eval('python_print(python_val());')
```

A function may also be created with javascript source:

```python
context.js.my_function = javascript_function.from_source('function() { return 1234; }')
```
Defined javascript functions may also be called directly from Python:

```python
context.js.my_function() # returns 1234
```

### WebAssembly Runtime
The `wasm_runtime` class, and its associated `wasm_context` and `wasm_module` classes allow WebAssembly modules to be loaded 
with files and byte arrays from Python. They efficiently load WebAssembly modules via a direct buffer copy of an NSData objects bytes into a Uint8Arrays backing store in JavaScriptCore. Allowing a module and its instance to then instantiated, and its exports are bridged directly to Python. Interop with JavaScriptCore allows WebAssembly functions to be mapped and called as any other normal Python callable function. WebAssembly methods are exposed from JavaScriptCore as `function() { [Native Code] }` bodied functions. The performance should be close to excuting code natively but is still being interpreted by JavaScriptCore. It is also likely that JavaScriptCore's WebAssembly runtime may be subject to some restrictions imposed by Apple's general security policies. 

To create a `wasm_context` a `wasm_runtime` instance needs to be created first. This currently works the same way as the `javascript_runtime`. 

A singleton context and optional runtime instance, with a lifetime of the program, may be obtained from the `jscore` static class accessors.

```python
context = jscore.webassembly()

# or shorthand
context = jscore.wasm()

# obtain wasm_runtime singleton instance
runtime = jscore.runtime(wasm_runtime)
```

Alternatively a `wasm_runtime` instance may also be created and managed independently. Similarly to the `javascript_runtime` it will contain a pointer to a separate JSVirtualMachine instance.

```python
runtime = wasm_runtime()
context = runtime.context()
```

A `wasm_context` is required to run WebAssembly from Python with more direct and efficient access. Its possible to run WebAssembly from just a `javascript_context` however this keeps the state more contained to Javascript and is therefore less convenient to use from Python. Needing more manual wire up and handling for imports / exports, WebAssembly system interface functions, execution blocking / thread management interacting with Python. 

This more specialised `wasm_context` aims to solves these difficulties for a close integration with the Python environment when required. While it is still also a fully functional `javascript_context` too. By default one single JavaScriptCore JSVirtualMachine an JSContext is shared between singleton `javascript_runtime` and `wasm_runtime` instances.

Although a `wasm_context` may execute JavaScript and vice versa, `wasm_runtime` and `wasm_context` are designed to integrate Python with WebAssembly as a first class runtime, with minimal need for any JavaScript by default, to load and call WebAssembly modules from Python. 
A `wasm_context` therefore focuses on loading `wasm_module` instances for library functionality, and running simulated wasm executable processes as `wasm_process`instances which mimic subprocesses with a compatible interface.

WebAssembly modules can be loaded from files or as raw bytes with the `wasm_module` class and `wasm_context.load_module` function.

```python
module_file = wasm_module.from_file("./path/to/module.wasm")
module_bytes = wasm_module(b'\0asm\1\0\0\0'+b'[module_body_bytes]', 'optional_module_name_or_path')
module_data = wasm_module([0, 97, 115, 109, 1, 0, 0, 0, ...], 'optional_module_name_or_path')

module_instance = module_file

context = jscore.wasm()
context.load_module(module_instance)

# once a module has been loaded its instance and exports are available from properties
print(module_instance.instance)
print(module_instance.exports)

```
Imports may be specified before loading a `wasm_module` instance obtained from a files or bytes into the context.
Python functions may be specified as imports directly, they will be converted automatically into a `javascript_callback` instance.

```python
module = wasm_module.from_file("./path/to/module.wasm")
# define python functions for imports
def imported_func(arg):
	pass
module.imports.my_namespace.imported_func = imported_func

# any callable may be specified as an import, the only requirement is parameters counts match.
module.imports.my_namespace.imported_func = lambda v: print(v)

# a javascript_function may also be specified as an import
module.imports.my_namespace.imported_func = javascript_function.from_source("function (arg) { }")

# an ImportError is raised if load_module is called for modules expecting imports without functions 
# for all of the expected imports specified.
context = jscore.wasm()
context.load_module(module)

```

Previously loaded module instances may be retrieved from the context:
```python
loaded_modules = context.modules # all modules

loaded_module = context.module("module_name_or_path")
```

WebAssembly exported functions are invoked as a regular Python function using an underlying `javascript_function` instance.

```python
module = wasm_module.from_file("./path/to/module.wasm")
context.load(module)

module.exports.exported_function()
module.exports.exported_function_with_parameters(convertible, python, args)
```
The following  function is currently acting as the module loader on JavaScriptCore's side, it is defined in the context by `wasm_context` upon its allocation. 

```javascript
const _jscore_wasm_modules = {}
function _jscore_wasm_load(name, wasm_bin, namespace){
		if(namespace === null) { namespace = {}; }
		const wasm_module = new WebAssembly.Module(wasm_bin);
		const wasm_instance = new WebAssembly.Instance(wasm_module, namespace);
		const wasm_module_instance = {"instance": wasm_instance, "namespace": namespace, "module": wasm_module};
		_jscore_wasm_modules[name] = wasm_module_instance; // ensure module remains in scope
		return wasm_module_instance;
}
```
Calling `wasm_context.load_module` will call this function to create `WebAssembly.Module` and `WebAssebly.Instance` instances in JavaScript with a WebAssembly binary passed as an `Uint8Array` typed array instance and an imports namespace. 

#### Example: Loading and calling Mozilla's simple.wasm
An end to end example of loading and using a WebAssembly module from Pythonista can be demonstrated by replicating [Mozilla's Loading Wasm Modules in Javascript](https://developer.mozilla.org/en-US/docs/WebAssembly/Guides/Using_the_JavaScript_API#loading_wasm_modules_in_javascript) example.

- Firstly, download the [simple.wasm](https://raw.githubusercontent.com/mdn/webassembly-examples/master/js-api-examples/simple.wasm) module from the page. 
- After downloading simple.wasm, the next step is to copy this into Pythonista. To do this, navigate to the simple.wasm file in your Files app, then select the file and open the sharing sheet, then tap "Run Pythonista Script" and then choose the "Import File" option. 
- Create a folder for your project and copy simple.wasm inside.
- In your folder with the simple.wasm module create the following script:

```python

from jscore_runtime import * 
context = jscore.wasm()

# load module file
module = wasm_module.from_file('./simple.wasm')
# define imports
module.imports.my_namespace.imported_func = lambda v: print(v)
# load module into context
context.load_module(module)
# once loaded, a modules exports become available and may be invoked
module.exports.exported_func() # prints 42
	
# output: 42
```
**Important Note:** "Run Pythonista Script->Import File" is the only safe way to import .wasm files into Pythonista besides a custom script. As the import function from the Pythonista app's menu ui does not appear to support .wasm files or binary in general. In fact it seems to even attempt to convert the data to text, by replacing unprintable characters with '?' rather than leaving it as-is, if the restriction is bypassed with an acceptable file extension. So therefore it **must not** be used to import binary files, nor the editor used to edit or even view them due to the editors autosaving functionality! Its easy to avoid this with some care double checking filenames before choosing the "Edit as text" option. Use only hex editors or disassemblers/assemblers packages to view / edit assemblies as binary.


Modules loading has been made to closely align with javascript with a couple of notable differences, firstly Python functions/callables may be used as imports as well as javascript functions. A fixed imports table is defined per `wasm_module` and `wasm_context`, imports must therefore be specified via the `wasm_module.imports`, module specific imports property, or `wasm_context.imports` context-wide imports property. A modules imports namespace always overrides any context-wide imports of the same matching structure and keys. 

#### WebAssembly Processes Execution
Compiled WebAssembly executable programs, having a `_start` function export, may now be run with limited support for WebAssembly System Interface (WASI) snapshot preview 1. A somewhat crude recursive dynamic dependency resolution based on module / file and function names is performed to load a runnable module with `_start` loading exports from any side-effect modules with `_init` beforehand currently. Ideally this would be fully dynamic lazy loading on invoking calls, however it is done up front currently for debugging.

Mobile device environments like iOS and Pythonista do not ordinarily support running isolated processes with `subprocess` which would normally be availble to Python on a PC. Instead a simulation `wasm_process` with a `subprocess` compatible/complaint interface with a backing `threading.Thread` `wasm_process_thread` are used to implement this functionality instead.

WebAssembly processes always run in association to a `wasm_context` and can be started from an existing `wasm_context`either asynchronously or synchronously. 

To start a process asynchronously on a background thread use `wasm_context.run_async` as follows:

```python
context = jscore.wasm()

# run .wasm program with _start function asynchronously in a new thread
process = context.run_async('./program.wasm', 'args', 'for', 'program', env = {"envVar":"value"}, dirs = ['./preopen_dir'])
# starts the process then returns a representation with a subprocess-like interface allowing interaction via stdin, stdout and stderr
```
To start a process synchronously on the current thread use `wasm_context.run` instead. 

```python
# run .wasm program with _start function synchronously (on the current thread)
process = context.run('./program.wasm', 'args', 'for', 'program', env = {"envVar":"value"}, dirs = ['./preopen_dir'])
# starts process and blocks current thread until execution is complete / terminated. 
# The process representation is returned so exit code / termination state etc may be inspected
# The full post execution state of stdin, stdout and stderr is also captured. 
```
Program arguments are provided as the `*args` array.
Named keyword arguments are used to pass additional configuration for the wasm environment.

- `env` a dict/object representing the environment variarbles state
- `dirs` a list of directory paths to be pre-opened and mounted into the wasm environment.
	- A directories list of at least one directory must be provided for WebAssembly to have access to Pythonistas filesystem as specified.

Important note: This function is more inteded for implementions using custom thread management. It will execute the .wasm executable on Pythonistas main thread by default, so use `run_async` if this is not desirable, freezes or deadlocks! 

The `wasm_process` class provides the following interface:

```python
class wasm_process:
	def __init__(self, env, module, args, kwargs, callback = None):
		self.env = env
		self.module = module
		self.args = args
		self.kwargs = kwargs
		self.thread = None
		self.exception = None
		self.killing = False
		self.killed = False
		self.running = False
		self.callback = callback
		self.lock = threading.RLock()
		self.awaiter = threading.Condition(self.lock)
		self.env.init_process(self)
	
	@property
	def module_path(self):
		return self.module.path
	
	@property
	def exit_code(self):
		return self.env.exit_code
		
	@exit_code.setter
	def exit_code(self, value):
		self.env.exit_code = value
	
	@property
	def returncode(self):
		if self.exit_code is None:
			return 0
		return self.exit_code
		
	@property
	def stdin(self):
		return self.env.stdin
		
	@property
	def stdout(self):
		return self.env.stdout
		
	@property
	def stderr(self):
		return self.env.stderr
	
	def run(self):
		pass
	
	def run_async(self):
		pass

	def communicate(self, stdin = None, timeout = None):
		pass
		
	def notify(self):
		pass
			
	def notify_all(self):
		pass

	def kill(self, *args, **kwargs):
		pass
		
	def wait(self, timeout = None, join = False):
		pass
		
	def wait_until_exit(self, timeout = None):
		pass
		
	def send_signal(self, sig):
		pass
```

A `wasm_process` instance is intended to be interchangable and be same equivalent to `subprocess` based execution as can be observed in Python WebAssembly framework implementations inteded for desktop which perform execution on the system directly running a self contained runtime command program like [Wasmtime](https://github.com/bytecodealliance/wasmtime) and [Wasmer](https://github.com/wasmerio/wasmer). Except using JavaScriptCore as the WebAssembly interpreter and execution engine. 

Processes contain a reference to their `wasm_module` code and a `wasm_env` instance representing the isolated process environments system state.
A `wasm_env` provides access to memory, representations of standard streams `stdin`, `stdout` and `stderr`, program arguments, environment variables and the filesystem alongside tracking file descriptors. It is used to hold and bridge the process memory and system state between Wasm and Python via `wasm_component`Python class instances, which represent interfaces / components provided by the runtime for implementing platform/system specific functionality. In this case as Python with Pythonista as the 'host' / 'target' platform/system. 

Isolated process environments provided by `wasm_env` instances have the following interface.

```python
class wasm_env:
	def __init__(self, parent = None, args = [], kwargs = {}, allocator = None):
		self.parent = parent # parent wasm env
		self.args = args
		self.kwargs = kwargs
		self._vars = kwargs.get("env", {})
		self._dirs = kwargs.get("dirs", [])
		self.world = kwargs.get("world", None)
		self.version = kwargs.get("version", None)
		self._exit_code = None
		self.stdin = kwargs.get("stdin")
		if self.stdin is None:
			self.stdin = wasm_io()
		self.stdout = kwargs.get("stdout")
		if self.stdout is None:
			self.stdout = wasm_io()
		self.stderr = kwargs.get("stderr")
		if self.stderr is None:
			self.stderr = wasm_io()
		self._clock = None
		if parent is None:
			self._clock = wasi_clock()
		else:
			self._clock = parent.clock
		self._allocator = allocator
		self._memory = None
		self._memory_view = None
		self._components = None
		self._fds = wasm_fds(self.stdin, self.stdout, self.stderr)
		self._process = None

	@property
	def vars(self):
		return self._vars
		
	@property
	def dirs(self):
		return self._dirs

	@property
	def exit_code(self):
		return self._exit_code
		
	@exit_code.setter
	def exit_code(self, value):
		self._exit_code = value
	
	@property
	def clock(self):
		return self._clock
	
	@property
	def components(self):
		return self._components
		
	@property
	def process(self):
		return self._process
		
	@process.setter
	def process(self, value):
		self._process = value
		
	def notify(self):
		self.process.notify()
	
	@property
	def memory(self):
		self._ensure_memory()
		return self._memory
		
	@memory.setter
	def memory(self, value):
		pass
		
	@property
	def memory_view(self):
		self._ensure_memory_view()
		return self._memory_view
	
	def init_process(self, process):
		pass
	
	def process_raise(self, signal):
		pass
	
	def process_exit(self, exit_code):
		self.exit_code = exit_code
		self.cleanup()
	
	def preopen(self, dir):
		pass
	
	def get_fd(self, fd):
		return self._fds.get_fd(fd)

	def get_stream(self, fd):
		return self._fds.get_stream(fd)
		
	def open_fd(self, fd, path, oflags, fs_rights_base, fs_rights_inheriting, fdflags):
		#
		return self._new_fd(mount, stream)
	
	def renumber_fd(self, from_fd, to_fd):
		pass
	
	def close_fd(self, fd):
		pass
		
	def close_stream(self, fd):
		pass
		
	def cleanup(self):
		pass
```

A wasm/wasi component model integration with Python implemented with derived `wasm_component` class instances is also in development towards expanding support to the [WASI snapshot preview 2/3 specifications](https://github.com/WebAssembly/WASI). Support for the [WASIX](https://github.com/wasix-org/wasix-witx) WASI preview 1 superset / extensions is also being considered. 

#### Running WASI Testsuite tests

WASI testsuite tests can be run by downloading compiled .wasm executables from the official WASI testsuite prod/testsuite-base branch [https://github.com/WebAssembly/wasi-testsuite/tree/prod/testsuite-base/tests](https://github.com/WebAssembly/wasi-testsuite/tree/prod/testsuite-base/tests). 

Clone this repository and import it into Pythonista by your preferred means. A slighly modified version of the testsuite's tests runner fixing a couple of Pythonista specific issues and runtime adapter harness are provided. 

To run the tests:

- Download .wasm executables, corresponding .json artefacts and test folders/files for filesystem tests onto your device from the offical testsuite repository. 
- Import and place all of the test artefacts into the folder path`wasi_testsuite/wasm32-wasip1`relative to the repository. 
- The runner can then be executed in two ways:
	- Set the`run_wasi_tests = True` flag in the `__main__` tests executed by `jscore_runtime.py`, then run the script.
		- It is preconfigured to any run tests from artefacts in `wasi_testsuite/wasm32-wasip1.`
		- This method is recommended for development, as it also has tracing for WASM assembly loading and WASI calls enabled. 
	- Alternatively WASI tests can be ran the`wasi_testsuite.py` script, which is also preconfigured to run tests from artefacts in the `wasi_testsuite/wasm32-wasip1.`
		- This method is more a means of providing a 'proof' but is less useful fir development as debugging information is omitted. 

```python
if __name__ == '__main__':
	import console
	console.clear()

	run_tests = True # run javascript / python tests
	run_wasi_tests = True # run WASI testsuite test runner on any tests in wasi_testsuite/wasm32-wasip1
```

---

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/M4nw3l/pythonista-jscore-runtime) [DeepWiki Documentation](https://deepwiki.com/M4nw3l/pythonista-jscore-runtime)

Disclaimer: DeepWiki documentation is AI generated, some inaccuracies or incorrect details are present and should be expected, if in doubt always reference the code. 
Further content with more agent guidance and wrangling to attempt to improve this documentations accuracy will be added on-going.

## Known issues
- Loading javascript files from remote sources / cdns etc is not implemented (yet).
- Modules and scripts loading may not work correctly for some javascript libraries and they may need manual adjustments to work correctly.
- ModulesLoaderDelegate is using a private protcol / api as there is no other way to access the functionality otherwise.

## Contribution
Contributions are very much welcome! The goals of this project are ambitious and the code aims to provide and bootstrap underlying support for a fairly sophisticated set of mechanisms and functionalities into Pythonista 3. So there is lots of room for contibutions small, medium and large!

Please feel free to raise issues for problems encountered. Make sure that you include details of what you tried and what happend, your expected/actual results, your code, stack traces etc. The more information the better! Debugging is especially hard without data, and sometimes even with data...

Pull requests for code contributions will be reviewed where time permits and accepted, if they are of sufficient quality, add value and are reasoned within the scope of the module and/or the overall goals it aims to accomplish. Code should be entirely your own work and be both sensibly presented and accurately represented, with also thorough depth where neccessary. 


