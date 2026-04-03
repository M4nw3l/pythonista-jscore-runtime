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
module_bytes = wasm_module(b'\0asm\1\0\0\0'+b'[module_body_bytes]', 'optional_module_name_or_path')
module_data = wasm_module([0, 97, 115, 109, 1, 0, 0, 0, ...], 'optional_module_name_or_path')

module_instance = module_file
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
An end to end example of loading and using a WebAssembly from Pythonista can be demonstrated by replicating [Mozilla's Loading Wasm Modules in Javascript](https://developer.mozilla.org/en-US/docs/WebAssembly/Guides/Using_the_JavaScript_API#loading_wasm_modules_in_javascript) example.

- Firstly, download the [simple.wasm](https://raw.githubusercontent.com/mdn/webassembly-examples/master/js-api-examples/simple.wasm) module from the page. 
- After downloading simple.wasm, the next step is to copy this into Pythonista. To do this, navigate to the simple.wasm file in your Files app, then select the file and open the sharing sheet, then tap "Run Pythonista Script" and then choose the "Import File" option. 
	- **Note: This is the only safe way to import .wasm files into Pythonista. The import function from in the Pythonista app itself does not support .wasm files and must not be used to import binary!**
- Create a folder for your project and copy simple.wasm inside.
- In your folder with the simple.wasm module create the following script:

```python

from jscore_runtime import * 
with (jscore.runtime(wasm_runtime) as runtime, runtime.context() as context):
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
Modules loading has been made to closely align with javascript with a couple of notable differences, firstly Python functions/callables may be used as imports as well as javascript functions. A fixed imports table is defined per `wasm_module` and `wasm_context`, imports must therefore be specified via the `wasm_module.imports` module specific imports or `wasm_context.imports` context-wide imports properties. A modules imports always override context-wide imports. 

## Known issues
- Loading javascript files from remote sources / cdns etc is not implemented (yet).
- Modules and scripts loading may not work correctly for some javascript libraries and they may need manual adjustments to work currently.
- ModulesLoaderDelegate is using a private protcol / api as there is no other way to access the functionality otherwise.
- JSScript source code strings are C++ objects which are more awkward structures to read with ctypes. A work around of separately loading a copy of the script source is used at the moment, so any module preprocessing performed when loading a JSScript is lost currently.

