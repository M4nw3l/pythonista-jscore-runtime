# pythonista-jscore-runtime
## JSCore Runtime Framework - Execute JavaScript and WebAssembly in Pythonista 3 natively on iOS with JavaScriptCore.
JSCore Runtime Framework is an experiment in pushing the boundaries of the Python environment and language features in the [Pythonista 3 IDE](https://omz-software.com/pythonista/) and apps developed with it on iOS. It is an extensive Python 3 mapping of the JavaScriptCore Objective-C and C-APIs via objc-util. Implementing closely analogous Python integrations, wrapping and interop for evaluating JavaScript and WebAssembly in independent and composable JavaScriptCore execution environments from Python 3 applications and scripts. Focused also from a point of view of being a serious attempt to extend vanilla Pythonista 3 to ultimately support Python packages and modules with compiled extensions that can be cross-compiled reliably into WebAssembly. 

The projects overall long term goals aim to offer three core capabilities/features:
- Evaluate/execute JavaScript and WebAssembly with seamless Python interop as a standalone library for Pythonista 3 based Python 3 apps.
- Compile, bundle, import and run custom source code and third party components extensibly with WebAssembly and JavaScript.
- Support Python packages/modules with extensions which can be cross-compiled to WebAssmembly from languages such as C.

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
# (written to Pythonistas terminal via imported_func)
```

## Installation

Install with pip using [StaSh](https://github.com/ywangd/stash).

```bash
pip install pythonista-jscore-runtime 
```

Or download [jscore_runtime.py](jscore_runtime.py) from the repository and copy to your site-packages folder.

## Usage
### Javascript Runtime
JSCore Runtime supports both the context management and explicit create/destroy usage paradigms. 
It provides singletons for convenience evaluation and while also allows more explicit management of multiple virtual machines and contexts with its class model.

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

They use the same runtime instances returned by `jscore.runtime` sharing the same underlying `JSVirtualMachine` and a single `JSContext` instance between them. The `javascript_context` and `wasm_context` objects returned by `javascript_runtime` and `wasm_runtime` instances craated by `jscore.runtime` respectively, are also sharing these same instances. Although separated runtime environments are also possible to create, they are not necessary for a standard use case. JavaScriptCore's API allows construction of context groupings but note there are some additonal considerations for working with data / memory between them. For example attempting to pass a `JSValue` to a context that didn't create is undefined behaviour and will most likey cause a crash.

Additionally `wasm_runtime` and `wasm_context` track only their own instances that have been created from Python. WebAssembly instance instantiated through JavaScript evaluation may still be accessed however when passed to Python or if they are made accessible from the global scope. 

### context.js accessor
A `javascript_context` provides a `js` property which allows access to the javascript contexts global object in a 'python-esque' interface.
Most simple python values may be retrieved and set through this accessor. It follows JavaScript access rules, and cannot subvert them, e.g. setting a const value fails with an exception. All read/write variables may otherwise be set and manipulated.

```python
context.js.number = 10
context.js.double = 1.1
context.js.array = []
context.js.object = {}
```

Python functions can be specified as functions callable from javascript:

```python

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

Although a `wasm_context` may execute JavaScript and vice versa, `wasm_runtime` and `wasm_context` are designed to integrate Python with WebAssembly as a first class runtime, without need for any JavaScript by default, to load and call WebAssembly modules from Python. A `wasm_context` therefore focuses on loading `wasm_module` instances.

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
An end to end example of loading and using a WebAssembly module from Pythonista can be demonstrated by replicating [Mozilla's Loading Wasm Modules in Javascript](https://developer.mozilla.org/en-US/docs/WebAssembly/Guides/Using_the_JavaScript_API#loading_wasm_modules_in_javascript) example.

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
- Modules and scripts loading may not work correctly for some javascript libraries and they may need manual adjustments to work correctly.
- ModulesLoaderDelegate is using a private protcol / api as there is no other way to access the functionality otherwise.

