# pythonista-jscore-runtime
## JSCore Runtime Framework - Execute JavaScript and WebAssembly in Pythonista 3 natively on iOS with JavaScriptCore.
JSCore Runtime Framework is an experiment in pushing the boundaries of the Python environment and language features in the Pythonista 3 IDE and apps developed with it on iOS. It is an extensive Python 3 mapping of the JavaScriptCore Objective-C and C-APIs via objc-util. Implementing closely analogous Python integrations, wrapping and interop for evaluating JavaScript and WebAssembly in independent and composable JavaScriptCore execution environments from Python 3 applications and scripts. Focused also from a point of view of being a serious attempt to extend vanilla Pythonista 3 to ultimately support Python packages and modules with compiled extensions that can be cross-compiled reliably into WebAssembly. 

The projects overall long term goals aim to offer three core capabilities/features:
- Evaluate/execute JavaScript and WebAssembly with seamless Python interop as a standalone library for Pythonista 3 based Python 3 apps.
- Compile, bundle, import and run custom source code and third party components extensibly with WebAssembly and JavaScript.
- Support Python packages/modules with extensions which can be cross-compiled to WebAssmembly from languages such as C.

A (very) simple example:
```python

from jscore_runtime import *

with (jscore.runtime() as runtime, runtime.context() as context):
  context.eval('function hello_world () { return "hello world"; }')
  print(context.js.hello_world())
  context.js.value_from_python = ["hello", "from", "python", 1, 2.2, 3.333333, {"object":"value", "nested":{"obj":["array", [], {}]}}]
  print(context.eval('value_from_python[2] = "javascript"; value_from_python;').value)

# output: 
# hello world
# ['hello', 'from', 'javascript', 1, 2.2, 3.333333, {'object': 'value', 'nested': {'obj': ['array', [], {}]}}]

```
Currently the main runtime and context implementation for the primary JavaScript evaluation and interop mechanism with JavaScriptCore is mostly working. WebAssembly modules and instances may also be instantiated and evaluated directly from JavaScript at the moment. WASM specific classes for runtime and context are placeholders currently. 

## Installation

Download [jscore_runtime.py](jscore_runtime.py) from the repository and copy to your site-packages folder.

<!--
Install with pip via StaSh 

```bash
pip install pythonista-jscore-runtime 
```
-->

## Usage

JSCore Runtime supports both the context management and explicit create/destroy usage paradigms. 
Alongside also automatically managed (singleton) quick/convenience evaluation and more explicit/multiple virtual machine and contexts instancing for advanced control. 

A runtime singleton can be obtained from the `jscore` static class.
```python
runtime = jscore.runtime()
```
By default if no runtime class is specified a `javascript_runtime` with a virtal machine lifetime of the program is returned.

A runtime class can also be instantiated independently. On creation it will contain a pointer to its own independent JSVirtualMachine instance.
```python
runtime = javascript_runtime()
``` 

A context is required to evaluate code. A context instance is onbtained from an existing runtime instance:
```python
context = runtime.context()
```
The context type matches the runtime type. e.g `javascript_runtime` returns `javascript_context` instances. Similarly to runtimes, contexts are independent of one another such that the state of one context is distinct to and isolated from another unless it is explictly configured for sharing via context groups. 

A context may evaluate javascript via several accessors:
```python

context.eval(jscourceCode) # general javascript string evaluation
# returns eval_result {"value": [python js value representation] or None , "exception": exception string or None }

# module loader based scripts handling. (Note: These methods are still highly experimental and can crash Pythonista!)

context.eval_source(jssourceCode)
context.eval_file(".path/to/js-file.js")

context.eval_module_source(moduleSourceCode, './optional/path/to/virtal-name.js')
context.eval_module_file("./path/to/module/index.js")
```

### context.js accessor
A `javascript_context` provides a `js` property which allows access to the javascript contexts global object in a 'python-esque' interface.
Most simple python values may be retrieved and set through this accessor. It follows JavaScript access rules, and cannot subvert them, e.g. setting a const value fails with an exception. All read/write variables may otherwise be set and manipulated.

```python
context.js.number = 10
context.js.double = 1.1
context.js.array = []
context.js.object = {}
```
Creating a function however is slightly different as it uses javascript source
```python
context.js.my_function = javascript_function.from_source('function() { return 1234; }')
```
Defined functions may be called from Python:
```python
context.js.my_function() # returns 1234
```

## Known issues
- JSScript loading can cause a random crash in Pythonista when Javascript is evaluated with no objective-c trace emitted. 
- Modules and scripts loading has patchy/limited ES6 support, some libaraies may need adjustments to work currently.
- ModulesLoaderDelegate is using a private protcol / api as there is no other way to access the functionality otherwise.
- JSScript source code strings are C++ objects which are more awkward structures to read with ctypes. A work around of separately loading a copy of the script source is used at the moment, so any module preprocessing performed when loading a JSScript is lost currently.
