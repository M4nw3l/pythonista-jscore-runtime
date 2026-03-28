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

## Installation

Download [jscore_runtime.py](jscore_runtime.py) from the repository and copy to your site-packages folder.

<!--
Install with pip via StaSh 

```bash
pip install pythonista-jscore-runtime 
```
-->

## Usage
### Javascript Runtime
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

A context may evaluate javascript with several javascript evaluation function variants:
```python
# general purpose javascript string evaluation function
context.eval(jsSourceCode) 
# returns:
# eval_result {"value": [python js value representation] or None , "exception": exception string or None }

# module loader based javascript evaluation functions
# regular javascript scripts/programs loaded synchronously
context.eval_source(jsSourceCode)
context.eval_file(".path/to/js-file.js")

# javascript modules loaded asynchronously
context.eval_module_source(moduleSourceCode, './optional/path/to/virtal-name.js')
context.eval_module_file("./path/to/module/index.js")

# all return:
# eval_result {"value": [python js value representation] or None , "exception": exception string or None }
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

### WebAssembly Runtime
The `wasm_runtime` class, and its associated `wasm_context` and `wasm_module` classes allow WebAssembly modules to be loaded 
with files and byte arrays from Python. They efficiently load WebAssembly modules via a direct buffer copy of an NSData objects bytes into a Uint8Arrays backing store in JavaScriptCore. Allowing a module and its instance to then instantiated, and its exports are bridged directly to Python. Interop with JavaScriptCore allows WebAssembly functions to be mapped and called as any other normal Python callable function. WebAssembly methods are exposed from JavaScriptCore as `function() { [Native Code] }` bodied functions. The performance should be close to excuting code natively but is still being interpreted by JavaScriptCore. It is also likely that JavaScriptCore's WebAssembly runtime may be subject to some restrictions imposed by Apple's general security policies. 

To create a `wasm_context` to instantiate `wasm_module` instances from a `wasm_runtime` instance needs to be created first. This currently works the same way as the `javascript_runtime`. 

A singleton runtime instance, with a lifetime of the program, may be obtained from the `jscore.runtime` accessor.
```python
runtime = jscore.runtime(wasm_runtime)
```

Alternatively a `wasm_runtime` instance may also be created and managed independently. Similarly to the `javascript_runtime` it will contain a pointer to a separate JSVirtualMachine instance.

```python
runtime = wasm_runtime()
```

A `wasm_context` may be obtained from runtime instance:

```python
context = runtime.context()
```

Although a `wasm_context` may execute JavaScript and vice versa, `wasm_runtime` and `wasm_context` are designed to integrate Python with WebAssembly as a first class runtime, without need for any JavaScript by default, to load and call WebAssembly modules from Python.

WebAssembly modules can be loaded from files or as raw bytes with the `wasm_module` class and `wasm_context.load_module` function.

```python
module_file = wasm_module.from_file("./path/to/module.wasm")
module_bytes = wasm_module(b'\0asm\1\0\0\0'+b'[module_body]', 'optional_module_name_or_path')
module_data = wasm_module([0, 97, 115, 109, 1, 0, 0, 0, ...], 'optional_module_name_or_path')

module_instance = module_file
context.load(module_instance)

# once a module has been loaded its instance and exports are available from properties
print(module_instance.instance)
print(module_instance.exports)

```
Previously loaded module instances may also be retrieved from the context:
```python
loaded_module = context.module("module_name_or_path")
```

WebAssembly exported functions are invoked as a regular Python function using an underlying `javascript_function` instance.

```python
module = wasm_module.from_file("./path/to/module.wasm")
context.load(module)

module.exports.exported_function()
module.exports.exported_function_with_parameters(convertible, python, args)
```
Please bear in mind at the moment this functionality is more experimental. It is currently serving as a loading mechansim thats better than passing WebAssembly modules bytes as strings or base64 strings to JavaScriptCore. 

They are exposed to JavaScriptCore through a global lookup, `_jscore_wasm_modules_data` keyed by a unique module name.
Module names are generated as `wasm_module_[loaded_count]` currently if one is not provided. 
There is no guarentee the same module bytes will receive the same generated name if a name is not otherwise specified.

```javascript
const _jscore_wasm_modules = {}
function _jscore_wasm_load(name){
    const loaded_wasm_module = _jscore_wasm_modules[name];
		if(loaded_wasm_module != null) {
			return loaded_wasm_module;
		}
		const wasm_bin = _jscore_wasm_modules_data[name];
		const wasm_module = new WebAssembly.Module(wasm_bin);
		const wasm_instance = new WebAssembly.Instance(wasm_module);
		const wasm_module_instance = {"bytes": wasm_bin, "module": wasm_module, "instance": wasm_instance};
		_jscore_wasm_modules[name] = wasm_module_instance;
		return wasm_module_instance;
}
```
The above function is currently acting as the module loader on JavaScriptCore's side, it is defined in the context by `wasm_context` upon its allocation. Then ultimately called by loading a module with `wasm_context.load_module` to create the `WebAssembly.Module` and `WebAssebly.Instance` instances in JavaScript. Libraries / imports mappings are not currently implemented.

## Known issues
- Loading javascript files from remote sources / cdns etc is not implemented (yet).
- Modules and scripts loading may not work correctly for some javascript libraries and they may need manual adjustments to work currently.
- ModulesLoaderDelegate is using a private protcol / api as there is no other way to access the functionality otherwise.
- JSScript source code strings are C++ objects which are more awkward structures to read with ctypes. A work around of separately loading a copy of the script source is used at the moment, so any module preprocessing performed when loading a JSScript is lost currently.
- WebAssembly module imports mapping mechanisms are missing / manual.
