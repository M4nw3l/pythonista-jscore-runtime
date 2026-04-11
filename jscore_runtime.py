"""
Pythonista JSCore Runtime Framework - Execute JavaScript and WebAssembly with seamless interop support natively in Pythonista 3.
Develop apps with Python, JavaScript and WebAssembly libraries, components and code. 

https://github.com/M4nw3l/pythonista-jscore-runtime
"""

__version__ = '0.0.1'

from ctypes import *
from ctypes.util import find_library
from objc_util import *
from objc_util import (c, object_getClass, class_getName, objc_getProtocol)
import weakref
from datetime import (datetime, timezone)
import json, re
from pathlib import Path
import tempfile, shutil, os
import ui

NSDate = ObjCClass("NSDate")
NSFileManager = ObjCClass("NSFileManager")

#objective c helpers
class objc:
	# load_library from rubicon 
	#https://github.com/beeware/rubicon-objc/blob/1a97f483fdd83f4fc31050ee863535e3ed962944/src/rubicon/objc/runtime.py#L77
	_lib_path = ["/usr/lib"]
	_framework_path = ["/System/Library/Frameworks"]
	@staticmethod
	def load_library(name):
		path = find_library(name)
		if path is not None:
			return CDLL(path)

		for loc in _lib_path:
			try:
				return CDLL(os.path.join(loc, "lib" + name + ".dylib"))
			except OSError:
				pass

		for loc in _framework_path:
			try:
				return CDLL(os.path.join(loc, name + ".framework", name))
			except OSError:
				pass
		raise ValueError(f"Library {name!r} not found")
	
	@staticmethod
	def const(dll, name, typ = c_void_p):
		if issubclass(typ, c_void_p):
			return ObjCInstance(typ.in_dll(dll, name))
		return typ.in_dll(dll, name)
	
	@staticmethod
	def c_func(func, restype, *argtypes):
		func.restype = restype
		func.argtypes = argtypes
		return staticmethod(func)
	
	objc_allocateProtocol = c_func(c.objc_allocateProtocol, c_void_p, c_char_p)
	objc_protocol_addMethodDescription = c_func(c.protocol_addMethodDescription, None, c_void_p, c_void_p, c_char_p, c_bool, c_bool)
	objc_protocol_addProtocol = c_func(c.protocol_addProtocol, None, c_void_p, c_void_p)
	objc_protocol_addProperty = c_func(c.protocol_addProperty, None, c_void_p, c_char_p, c_void_p, c_uint, c_bool, c_bool)
	objc_registerProtocol = c_func(c.objc_registerProtocol, None, c_void_p)

	@staticmethod
	def getProtocol(name):
		return objc_getProtocol(name.encode("ascii"))
	
	@staticmethod
	def allocateProtocol(name):
		return objc.objc_allocateProtocol(name.encode("ascii"))
	
	@staticmethod
	def get_type_encoding(typ):
		# https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ObjCRuntimeGuide/Articles/ocrtTypeEncodings.html
		# objective-c type encoding from a source type reference string - covers a fair few cases but is incomplete. 
		# While it also cannot understand some c type definitions properly e.g definitions containing refernces to typedef names
		enc = []
		while typ.endswith('*'):
			enc.append("^")
			typ = typ[:len(typ)-1]
		typ = typ.strip()
		parts = typ.split(' ')
		upper = False
		val = None
		while len(parts) > 0:
			part = parts.pop(0)
			if part == "unsigned":
				upper = True
			elif part == "char":
				c = len(enc)
				for i in range(c):
					enc[i] = "*" if enc[i] == "^" else enc[i]
				val = "c" if c == 0 else ""
			elif part in ["int", "void", "short", "float", "double"]:
				val = part[0]
			elif part == "long":
				val = "l" if val is None else "q"
			elif part in ["bool", "BOOL", "_Bool"]:
				val = "B"
		array = typ.endswith("]")
		ptr = len(enc) == 1
		struct = val is None and len(enc) > 0
		arrlen=""
		if array:
			idx = list(typ).index('[')
			arrlen = typ[idx:len(typ)-1]
			typ = typ[:idx]
		if val is not None:
			enc.append(val)
		if struct:
			enc.append("{")
			enc.append(typ)
			if ptr:
				enc.append("=#}")
			else:
				enc.append("}")
		if array:
			enc.insert(0, "["+arrlen)
			enc.append("]")
		return "".join(enc)

	@staticmethod
	def protocol_addMethodDescription(protocol, method, required, types = None, instance = None):
		# add a protocol method description from its objective-c definition
		method = method.strip()
		name = "".join(re.findall("([A-z0-9]+:)", method))
		description = ""
		if instance is None:
			instance = method.startswith("-")
			if not instance and not method.startswith("+"):
				raise ValueError(f"Method type is not specified as class (+) or instance (-) for method '{method}'")
		if types is not None:
			if isinstance(types, str):
				description = types
			else:
				description = "".join(types)
		else:
			types = re.findall("\\(([A-z0-9 \*_\[\]]+)\\)", method)
			description = []
			for typ in types:
				enc = objc.get_type_encoding(typ)
				description.append(enc)
			description = "".join(description)
		#print(name)
		selector = sel(name)
		description = description.encode("ascii")
		objc.objc_protocol_addMethodDescription(protocol, selector, description, required, instance)
		
	@staticmethod
	def protocol_addProperty(protocol, property, required, types = None, instance = None):
		raise NotImplementedError("TODO: protocol_addProperty")
		
	@staticmethod
	def protocol_addProtocol(protocol, parent):
		objc.objc_protocol_addProtocol(protocol, parent)
	
	@staticmethod
	# create a protocol from an objc definition
	def protocol(name, body = [], types = [], protocols=["NSObject"], debug = True):
		basename = name
		p = objc.getProtocol(name)
		if p is not None and not debug:
			return name
		counter = 0
		while debug:
			p = objc.getProtocol(name)
			if p is None:
				break
			name = f"{basename}_{counter}"
			counter = counter + 1
		p = objc.allocateProtocol(name)
		for id in protocols:
			parent = objc.getProtocol("NSObject")
			if parent is None:
				 raise ValueError(f"Protocol not found '{id}'")
			objc.protocol_addProtocol(p, parent)
		required = True
		typesLen = len(types)
		for i in range(len(body)):
			method = body[i].strip()
			methodTypes = None
			if i < typesLen:
				t = types[i]
				if isinstance(t, str):
					t = t.strip()
					if t != "":
						methodTypes = t
				elif t is not None and len(t) > 0:
					methodTypes = t
			if method == "@required":
				required = True
			elif method == "@optional":
				required = False
			elif not ":" in method:
				objc.protocol_addProperty(p, method, required, methodTypes) # TODO: properties
				print(method)
			else:
				objc.protocol_addMethodDescription(p, method, required, methodTypes)
		objc.objc_registerProtocol(p)
		#print(name)
		return name
		
	new_class = create_objc_class

	@staticmethod
	def ns_class(nsobject):
		if not (isinstance(nsobject, c_void_p) or isinstance(nsobject, ObjCInstance)):
			return None
		objClass = ObjCInstance(object_getClass(nsobject))
		objClassName = class_getName(objClass)
		return objClass

	@staticmethod
	def ns_subclass_of(nsobject, objcClass, objClass=None):
		if not (isinstance(nsobject, c_void_p) or isinstance(nsobject, ObjCInstance)):
			return False
		if objClass is None:
			objClass = objc.ns_class(nsobject)
		if objClass is None:
			return False
		return objClass.isSubclassOfClass_(objcClass)

	@staticmethod
	def ns_to_py(nsobject, objClass=None):
		if objClass is None:
			objClass = objc.ns_class(nsobject)
		if objc.ns_subclass_of(nsobject, NSString, objClass):
			v = str(nsobject)
			return v
		if objc.ns_subclass_of(nsobject, NSNumber, objClass):
			nsnumber = nsobject
			doubleValue = float(nsnumber.doubleValue())
			intValue = int(nsnumber.longLongValue())
			if doubleValue == intValue:
				return intValue
			return doubleValue
		if objc.ns_subclass_of(nsobject, NSDate, objClass):
			nsdate = nsobject
			timestamp = nsdate.timeIntervalSince1970()
			return datetime.fromtimestamp(timestamp, timezone.utc)
		if objc.ns_subclass_of(nsobject, NSArray, objClass):
			nsarray = nsobject
			items = []
			for i in range(nsarray.count()):
				item = objc.ns_to_py(nsarray.objectAtIndex_(i))
				items.append(item)
			return items
		if objc.ns_subclass_of(nsobject, NSDictionary, objClass):
			nsdict = nsobject
			keys = nsdict.allKeys()
			values = nsdict.allValues()
			items = {}
			for i in range(nsdict.count()):
				key = objc.ns_to_py(keys.objectAtIndex_(i))
				value = objc.ns_to_py(values.objectAtIndex_(i))
				items[key] = value
			return items
		className = "unknown"
		if objClass is not None:
			className = class_getName(objClass)
		raise NotImplementedError("Unhandled NSObject type {objClass} ({className}) for {nsobject}.")
	
	@staticmethod
	def c_array(count, items = None, typ = c_byte, ptr = c_void_p):
		if items is None:
			if callable(count):
				items = []
				iter = count
				count = 0
				while True:
					try:
						item = iter(count)
						if item is None:
							break
						count = count + 1
						items.append(item)
					except:
						break
			elif isinstance(count, bytes) or isinstance(count, list):
				items = count
				count = len(items)
		if count == 0:
			if ptr is None:
				return None
			return cast(c_void_p(None), ptr) # NULL
		c_array_typ = typ * count
		array = c_array_typ()
		if items is None:
			if ptr is None:
				return array
			return cast(array, ptr)
		if isinstance(items, bytes) or isinstance(items, list):
			for i in range(count):
				array[i] = items[i]
		elif callable(items):
			for i in range(count):
				array[i] = items(i)
		else:
			raise NotImplementedError()
		if ptr is None:
			return array
		return cast(array, ptr)
	
	@staticmethod
	def c_array_p(count, items = None, typ = c_void_p, ptr = c_void_p):
		return objc.c_array(count, items, typ, ptr)
	
	@staticmethod
	def nsdata_from_file(path, fileManager = None):
		if fileManager is None:
			fileManager = NSFileManager.defaultManager()
		path = Path(str(path))
		if not path.is_absolute():
			path = path.cwd().joinpath(path)
		if not path.exists():
			raise FileNotFoundError(f"File not found at path '{path}'")
		path = str(path)
		data = fileManager.contentsAtPath_(path)
		return data


#JavaScriptCore api
class jscore:
	JSVirtualMachine = ObjCClass("JSVirtualMachine")
	JSContext = ObjCClass("JSContext")
	JSValue = ObjCClass("JSValue")
	JSManagedValue = ObjCClass("JSManagedValue")
	JSScript = ObjCClass("JSScript")
	JSExport = ObjCClass("JSExport")
	JSObjCClassInfo = ObjCClass("JSObjCClassInfo")
	JSWrapperMap = ObjCClass("JSWrapperMap")
	JSVMWrapperCache = ObjCClass("JSVMWrapperCache")
	WTFWebFileManagerDelegate = ObjCClass("WTFWebFileManagerDelegate")
	
	# c api
	lib = objc.load_library("JavaScriptCore")
	
	JSContextGetGroup = objc.c_func(lib.JSContextGetGroup, c_void_p, c_void_p)
	JSContextGroupCreate = objc.c_func(lib.JSContextGroupCreate, c_void_p)
	JSContextGroupRetain = objc.c_func(lib.JSContextGroupRetain, c_void_p, c_void_p)
	JSContextGroupRelease = objc.c_func(lib.JSContextGroupRelease, None, c_void_p)
	JSContextGetGlobalContext = objc.c_func(lib.JSContextGetGlobalContext, c_void_p, c_void_p)
	JSContextGetGlobalObject = objc.c_func(lib.JSContextGetGlobalObject, c_void_p, c_void_p)
	
	JSGlobalContextCreate = objc.c_func(lib.JSGlobalContextCreate, c_void_p, c_void_p)
	JSGlobalContextCreateInGroup = objc.c_func(lib.JSGlobalContextCreateInGroup, c_void_p, c_void_p, c_void_p)
	JSGlobalContextRetain = objc.c_func(lib.JSGlobalContextRetain, c_void_p, c_void_p)
	JSGlobalContextRelease = objc.c_func(lib.JSGlobalContextRelease, None, c_void_p)
	JSGlobalContextCopyName = objc.c_func(lib.JSGlobalContextCopyName, c_void_p, c_void_p)
	JSGlobalContextSetName = objc.c_func(lib.JSGlobalContextSetName, None, c_void_p, c_void_p)
	JSGlobalContextIsInspectable = objc.c_func(lib.JSGlobalContextIsInspectable, c_bool, c_void_p)
	JSGlobalContextSetInspectable = objc.c_func(lib.JSGlobalContextSetInspectable, None, c_void_p, c_bool)
	
	JSChar_p = POINTER(c_ushort)
	JSStringCreateWithCharacters = objc.c_func(lib.JSStringCreateWithCharacters, c_void_p, c_void_p, c_size_t)
	JSStringCreateWithUTF8CString = objc.c_func(lib.JSStringCreateWithUTF8CString, c_void_p, c_void_p)
	JSStringRetain = objc.c_func(lib.JSStringRetain, c_void_p, c_void_p)
	JSStringRelease = objc.c_func(lib.JSStringRelease, None, c_void_p)
	JSStringGetLength = objc.c_func(lib.JSStringGetLength, c_size_t, c_void_p)
	JSStringGetCharactersPtr = objc.c_func(lib.JSStringGetCharactersPtr, JSChar_p, c_void_p)
	JSStringGetMaximumUTF8CStringSize = objc.c_func(lib.JSStringGetMaximumUTF8CStringSize, c_size_t, c_void_p)
	JSStringGetUTF8CString = objc.c_func(lib.JSStringGetUTF8CString, c_size_t, c_void_p, c_void_p, c_size_t)
	JSStringIsEqual = objc.c_func(lib.JSStringIsEqual, c_bool, c_void_p, c_void_p)
	JSStringIsEqualToUTF8CString = objc.c_func(lib.JSStringIsEqualToUTF8CString, c_bool, c_void_p, c_void_p)
	JSStringCreateWithCFString = objc.c_func(lib.JSStringCreateWithCFString, c_void_p, c_void_p)
	JSStringCopyCFString = objc.c_func(lib.JSStringCopyCFString, c_void_p, c_void_p, c_void_p)
	
	JSValueGetType = objc.c_func(lib.JSValueGetType, c_int, c_void_p, c_void_p)
	JSValueIsUndefined = objc.c_func(lib.JSValueIsUndefined, c_bool, c_void_p, c_void_p)
	JSValueIsNull = objc.c_func(lib.JSValueIsNull, c_bool, c_void_p, c_void_p)
	JSValueIsBoolean = objc.c_func(lib.JSValueIsBoolean, c_bool, c_void_p, c_void_p)
	JSValueIsNumber = objc.c_func(lib.JSValueIsNumber, c_bool, c_void_p, c_void_p)
	JSValueIsString = objc.c_func(lib.JSValueIsString, c_bool, c_void_p, c_void_p)
	JSValueIsSymbol = objc.c_func(lib.JSValueIsSymbol, c_bool, c_void_p, c_void_p)
	JSValueIsObject = objc.c_func(lib.JSValueIsObject, c_bool, c_void_p, c_void_p)
	JSValueIsObjectOfClass = objc.c_func(lib.JSValueIsObjectOfClass, c_bool, c_void_p, c_void_p, c_void_p)
	JSValueIsArray = objc.c_func(lib.JSValueIsArray, c_bool, c_void_p, c_void_p)
	JSValueIsDate = objc.c_func(lib.JSValueIsDate, c_bool, c_void_p, c_void_p)
	JSValueGetTypedArrayType = objc.c_func(lib.JSValueGetTypedArrayType, c_int, c_void_p, c_void_p, c_void_p)
	JSValueMakeUndefined = objc.c_func(lib.JSValueMakeUndefined, c_void_p, c_void_p)
	JSValueMakeNull = objc.c_func(lib.JSValueMakeNull, c_void_p, c_void_p)
	JSValueMakeBoolean = objc.c_func(lib.JSValueMakeBoolean, c_void_p, c_void_p, c_bool)
	JSValueMakeNumber = objc.c_func(lib.JSValueMakeNumber, c_void_p, c_void_p, c_double)
	JSValueMakeString = objc.c_func(lib.JSValueMakeString, c_void_p, c_void_p, c_void_p)
	JSValueMakeSymbol = objc.c_func(lib.JSValueMakeSymbol, c_void_p, c_void_p, c_void_p)
	JSValueToBoolean = objc.c_func(lib.JSValueToBoolean, c_bool, c_void_p, c_void_p)
	JSValueToNumber = objc.c_func(lib.JSValueToNumber, c_double, c_void_p, c_void_p, c_void_p)
	JSValueToStringCopy = objc.c_func(lib.JSValueToStringCopy, c_void_p, c_void_p, c_void_p, c_void_p)
	JSValueToObject = objc.c_func(lib.JSValueToObject, c_void_p, c_void_p, c_void_p, c_void_p)
	JSValueMakeFromJSONString = objc.c_func(lib.JSValueMakeFromJSONString, c_void_p, c_void_p, c_void_p)
	JSValueCreateJSONString = objc.c_func(lib.JSValueCreateJSONString, c_void_p, c_void_p, c_void_p, c_uint, c_void_p)
	JSValueIsEqual = objc.c_func(lib.JSValueIsEqual, c_bool, c_void_p, c_void_p, c_void_p, c_void_p)
	JSValueIsStrictEqual = objc.c_func(lib.JSValueIsStrictEqual, c_bool, c_void_p, c_void_p, c_void_p)
	JSValueIsInstanceOfConstructor = objc.c_func(lib.JSValueIsInstanceOfConstructor, c_bool, c_void_p, c_void_p, c_void_p, c_void_p)
	JSValueProtect = objc.c_func(lib.JSValueProtect, None, c_void_p, c_void_p)
	JSValueUnprotect = objc.c_func(lib.JSValueUnprotect, None, c_void_p, c_void_p)
	
	JSObjectCallAsConstructor = objc.c_func(lib.JSObjectCallAsConstructor, c_void_p, c_void_p, c_void_p, c_size_t, c_void_p, c_void_p)
	JSObjectCallAsFunction = objc.c_func(lib.JSObjectCallAsFunction, c_void_p, c_void_p, c_void_p, c_void_p, c_size_t, c_void_p, c_void_p)
	JSObjectCopyPropertyNames = objc.c_func(lib.JSObjectCopyPropertyNames, c_void_p, c_void_p, c_void_p)
	JSObjectDeleteProperty = objc.c_func(lib.JSObjectDeleteProperty, c_bool, c_void_p, c_void_p, c_void_p, c_void_p)
	JSObjectGetPrivate = objc.c_func(lib.JSObjectGetPrivate, c_void_p, c_void_p)
	JSObjectGetProperty = objc.c_func(lib.JSObjectGetProperty, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)
	JSObjectGetPropertyAtIndex = objc.c_func(lib.JSObjectGetPropertyAtIndex, c_void_p, c_void_p, c_void_p, c_uint, c_void_p)
	JSObjectGetPrototype = objc.c_func(lib.JSObjectGetPrototype, c_void_p, c_void_p, c_void_p)
	JSObjectHasProperty = objc.c_func(lib.JSObjectHasProperty, c_bool, c_void_p, c_void_p, c_void_p)
	JSObjectIsConstructor = objc.c_func(lib.JSObjectIsConstructor, c_bool, c_void_p, c_void_p)
	JSObjectIsFunction = objc.c_func(lib.JSObjectIsFunction, c_bool, c_void_p, c_void_p)
	JSObjectMake = objc.c_func(lib.JSObjectMake, c_void_p, c_void_p, c_void_p, c_void_p)
	JSObjectMakeArray = objc.c_func(lib.JSObjectMakeArray, c_void_p, c_void_p, c_size_t, c_void_p, c_void_p)
	JSObjectMakeConstructor = objc.c_func(lib.JSObjectMakeConstructor, c_void_p, c_void_p, c_void_p, c_void_p)
	JSObjectMakeDate = objc.c_func(lib.JSObjectMakeDate, c_void_p, c_void_p, c_size_t, c_void_p, c_void_p)
	JSObjectMakeError = objc.c_func(lib.JSObjectMakeError, c_void_p, c_void_p, c_size_t, c_void_p, c_void_p)
	JSObjectMakeFunction = objc.c_func(lib.JSObjectMakeFunction, c_void_p, c_void_p, c_void_p, c_uint, c_void_p, c_void_p, c_void_p, c_int, c_void_p)
	JSObjectCallAsFunctionCallback = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_void_p, c_ulong, c_void_p, c_void_p)
	JSObjectMakeFunctionWithCallback = objc.c_func(lib.JSObjectMakeFunctionWithCallback, c_void_p, c_void_p, c_void_p, c_void_p)
	JSObjectMakeRegExp = objc.c_func(lib.JSObjectMakeRegExp, c_void_p, c_void_p, c_size_t, c_void_p, c_void_p)
	JSObjectSetPrivate = objc.c_func(lib.JSObjectSetPrivate, c_bool, c_void_p, c_void_p)
	JSObjectSetProperty = objc.c_func(lib.JSObjectSetProperty, None, c_void_p, c_void_p, c_void_p, c_void_p, c_uint, c_void_p)
	JSObjectSetPropertyAtIndex = objc.c_func(lib.JSObjectSetPropertyAtIndex, None, c_void_p, c_void_p, c_uint, c_void_p, c_void_p)
	JSObjectGetPropertyForKey = objc.c_func(lib.JSObjectGetPropertyForKey, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)
	JSObjectSetPrototype = objc.c_func(lib.JSObjectSetPrototype, None, c_void_p, c_void_p, c_void_p)
	JSObjectDeletePropertyForKey = objc.c_func(lib.JSObjectDeletePropertyForKey, c_bool, c_void_p, c_void_p, c_void_p, c_void_p)
	JSObjectHasPropertyForKey = objc.c_func(lib.JSObjectHasPropertyForKey, c_bool, c_void_p, c_void_p, c_void_p, c_void_p)
	JSObjectSetPropertyForKey = objc.c_func(lib.JSObjectSetPropertyForKey, None, c_void_p, c_void_p, c_void_p, c_void_p, c_uint, c_void_p)
	JSObjectMakeDeferredPromise = objc.c_func(lib.JSObjectMakeDeferredPromise, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)
	
	JSClassCreate = objc.c_func(lib.JSClassCreate, c_void_p, c_void_p)
	JSClassRelease = objc.c_func(lib.JSClassRelease, None, c_void_p)
	JSClassRetain = objc.c_func(lib.JSClassRetain, c_void_p, c_void_p)
	
	JSPropertyNameAccumulatorAddName = objc.c_func(lib.JSPropertyNameAccumulatorAddName, None, c_void_p, c_void_p)
	JSPropertyNameArrayGetCount = objc.c_func(lib.JSPropertyNameArrayGetCount, c_size_t, c_void_p)
	JSPropertyNameArrayGetNameAtIndex = objc.c_func(lib.JSPropertyNameArrayGetNameAtIndex, c_void_p, c_void_p, c_size_t)
	JSPropertyNameArrayRelease = objc.c_func(lib.JSPropertyNameArrayRelease, None, c_void_p)
	JSPropertyNameArrayRetain = objc.c_func(lib.JSPropertyNameArrayRetain, c_void_p, c_void_p)
	
	JSObjectMakeTypedArray = objc.c_func(lib.JSObjectMakeTypedArray, c_void_p, c_void_p, c_int, c_size_t, c_void_p)
	JSObjectMakeTypedArrayWithBytesNoCopy = objc.c_func(lib.JSObjectMakeTypedArrayWithBytesNoCopy, c_void_p, c_void_p, c_int, c_void_p, c_size_t, c_void_p, c_void_p, c_void_p)
	JSObjectMakeTypedArrayWithArrayBuffer = objc.c_func(lib.JSObjectMakeTypedArrayWithArrayBuffer, c_void_p, c_void_p, c_int, c_void_p, c_void_p)
	JSObjectMakeTypedArrayWithArrayBufferAndOffset = objc.c_func(lib.JSObjectMakeTypedArrayWithArrayBufferAndOffset, c_void_p, c_void_p, c_int, c_void_p, c_size_t, c_size_t, c_void_p)
	JSObjectGetTypedArrayBytesPtr = objc.c_func(lib.JSObjectGetTypedArrayBytesPtr, c_void_p, c_void_p, c_void_p, c_void_p)
	JSObjectGetTypedArrayLength = objc.c_func(lib.JSObjectGetTypedArrayLength, c_size_t, c_void_p, c_void_p, c_void_p)
	JSObjectGetTypedArrayByteLength = objc.c_func(lib.JSObjectGetTypedArrayByteLength, c_size_t, c_void_p, c_void_p, c_void_p)
	JSObjectGetTypedArrayByteOffset = objc.c_func(lib.JSObjectGetTypedArrayByteOffset, c_size_t, c_void_p, c_void_p, c_void_p)
	JSObjectGetTypedArrayBuffer = objc.c_func(lib.JSObjectGetTypedArrayBuffer, c_void_p, c_void_p, c_void_p, c_void_p)
	JSObjectMakeArrayBufferWithBytesNoCopy = objc.c_func(lib.JSObjectMakeArrayBufferWithBytesNoCopy, c_void_p, c_void_p, c_void_p, c_size_t, c_void_p, c_void_p, c_void_p)
	JSObjectGetArrayBufferByteLength = objc.c_func(lib.JSObjectGetArrayBufferByteLength, c_size_t, c_void_p, c_void_p, c_void_p)
	JSObjectGetArrayBufferBytesPtr = objc.c_func(lib.JSObjectGetArrayBufferBytesPtr, c_void_p, c_void_p, c_void_p, c_void_p)
	
	kJSTypedArrayTypeInt8Array = 0
	kJSTypedArrayTypeInt16Array = 1
	kJSTypedArrayTypeInt32Array = 2
	kJSTypedArrayTypeUint8Array = 3
	kJSTypedArrayTypeUint8ClampedArray = 4
	kJSTypedArrayTypeUint16Array = 5
	kJSTypedArrayTypeUint32Array = 6
	kJSTypedArrayTypeFloat32Array = 7
	kJSTypedArrayTypeFloat64Array = 8
	kJSTypedArrayTypeArrayBuffer = 9
	kJSTypedArrayTypeNone = 10
	kJSTypedArrayTypeBigInt64Array = 11
	kJSTypedArrayTypeBigUint64Array = 12
	
	JSCheckScriptSyntax = objc.c_func(lib.JSCheckScriptSyntax, c_bool, c_void_p, c_void_p, c_void_p, c_int, c_void_p)
	JSEvaluateScript = objc.c_func(lib.JSEvaluateScript, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p, c_int, c_void_p)
	JSGarbageCollect = objc.c_func(lib.JSGarbageCollect, None, c_void_p)
	
	JSBigIntCreateWithDouble = objc.c_func(lib.JSBigIntCreateWithDouble, c_void_p, c_void_p, c_double, c_void_p)
	JSBigIntCreateWithInt64 = objc.c_func(lib.JSBigIntCreateWithInt64, c_void_p, c_void_p, c_int64, c_void_p)
	JSBigIntCreateWithString = objc.c_func(lib.JSBigIntCreateWithString, c_void_p, c_void_p, c_void_p, c_void_p)
	JSBigIntCreateWithUInt64 = objc.c_func(lib.JSBigIntCreateWithUInt64, c_void_p, c_void_p, c_uint64, c_void_p)
	
	JSValueCompare = objc.c_func(lib.JSValueCompare, c_int, c_void_p, c_void_p, c_void_p, c_void_p)
	JSValueCompareDouble = objc.c_func(lib.JSValueCompareDouble, c_int, c_void_p, c_void_p, c_void_p, c_void_p)
	JSValueCompareInt64 = objc.c_func(lib.JSValueCompareInt64, c_int, c_void_p, c_void_p, c_void_p, c_void_p)
	JSValueCompareUInt64 = objc.c_func(lib.JSValueCompareUInt64, c_int, c_void_p, c_void_p, c_void_p, c_void_p)
	JSValueIsBigInt = objc.c_func(lib.JSValueIsBigInt, c_bool, c_void_p, c_void_p)
	JSValueToInt32 = objc.c_func(lib.JSValueToInt32, c_int32, c_void_p, c_void_p, c_void_p)
	JSValueToInt64 = objc.c_func(lib.JSValueToInt64, c_int64, c_void_p, c_void_p, c_void_p)
	JSValueToUInt32 = objc.c_func(lib.JSValueToUInt32, c_uint32, c_void_p, c_void_p, c_void_p)
	JSValueToUInt64 = objc.c_func(lib.JSValueToUInt64, c_uint64, c_void_p, c_void_p, c_void_p)
	
	# internal api (for module loader)
	
	# https://github.com/WebKit/WebKit/blob/7321e0dc891bcc0dce916e8d71204e58d92641cd/Source/JavaScriptCore/API/JSScriptRefPrivate.h
	#JSScriptRef
	JSScriptCreateReferencingImmortalASCIIText = objc.c_func(lib.JSScriptCreateReferencingImmortalASCIIText, c_void_p, c_void_p, c_void_p, c_int, c_void_p, c_size_t, c_void_p, c_void_p)
	JSScriptCreateFromString = objc.c_func(lib.JSScriptCreateFromString, c_void_p, c_void_p, c_void_p, c_int, c_void_p, c_void_p, c_void_p)
	JSScriptRetain = objc.c_func(lib.JSScriptRetain, None, c_void_p)
	JSScriptRelease = objc.c_func(lib.JSScriptRelease, None, c_void_p)
	JSScriptEvaluate = objc.c_func(lib.JSScriptEvaluate, c_void_p, c_void_p, c_void_p, c_void_p, c_void_p)
	
	kJSScriptTypeProgram = 0
	kJSScriptTypeModule = 1
	
	# It is necessary to define the JSModuleLoaderDelegate protocol before we can use it as its not a public protocol, for original definition
	# see: https://github.com/WebKit/WebKit/blob/3a620254c233064790f172eb54eee6db874be7b1/Source/JavaScriptCore/API/JSContextPrivate.h
	JSModuleLoaderDelegate = objc.protocol("JSModuleLoaderDelegate", body=[
		"@required",
		"- (void)context:(JSContext *)context fetchModuleForIdentifier:(JSValue *)identifier withResolveHandler:(JSValue *)resolve andRejectHandler:(JSValue *)reject;",
		"@optional",
		"- (void)willEvaluateModule:(NSURL *)key;",
		"- (void)didEvaluateModule:(NSURL *)key;"
	], debug=False)
	
	# forwards calls to loader
	def JSCoreModuleLoaderDelegate_context_fetchModuleForIdentifier_withResolveHandler_andRejectHandler_(_self,_cmd, _ctx, _id, _resolve, _reject):
		loader = ObjCInstance(_self)._pyinstance()
		module = javascript_value(ObjCInstance(_id)).value
		resolve = javascript_function(ObjCInstance(_resolve))
		reject = javascript_function(ObjCInstance(_reject))
		loader.fetch_module(module, resolve, reject)

	f = JSCoreModuleLoaderDelegate_context_fetchModuleForIdentifier_withResolveHandler_andRejectHandler_
	f.argtypes = [c_void_p,c_void_p,c_void_p,c_void_p]
	f.encoding = "@:@@@@@"
	
	# forward to loader when defined (though does not appear to be called)
	def JSCoreModuleLoaderDelegate_willEvaluateModule_(_self,_cmd,_url):
		loader = ObjCInstance(_self)._pyinstance()
		handler = getattr(loader, 'will_eval_module')
		if handler is not None:
			handler(ObjCInstance(_url))
		
	f = JSCoreModuleLoaderDelegate_willEvaluateModule_
	f.argtypes = [c_void_p]
	f.encoding = "@:@@"
	
	# forward to loader when defined (though does not appear to be called)
	def JSCoreModuleLoaderDelegate_didEvaluateModule_(_self,_cmd,_url):
		loader = ObjCInstance(_self)._pyinstance()
		handler = getattr(loader, 'did_eval_module')
		if handler is not None:
			handler(ObjCInstance(_url))
		
	f = JSCoreModuleLoaderDelegate_didEvaluateModule_
	f.argtypes = [c_void_p]
	f.encoding = "@:@@"
	
	# JSModuleLoaderDelegate protocol implementation
	JSCoreModuleLoaderDelegate = objc.new_class("JSCoreModuleLoaderDelegate", protocols=[JSModuleLoaderDelegate], methods = [
		JSCoreModuleLoaderDelegate_context_fetchModuleForIdentifier_withResolveHandler_andRejectHandler_,
		JSCoreModuleLoaderDelegate_willEvaluateModule_,
		JSCoreModuleLoaderDelegate_didEvaluateModule_
	])
	
	# representation of WTFString
	class WTFString(Structure):
		class WTFStringData(Union):
			_fields_ = [
				("m_data8", c_char_p),
				("m_data16", c_wchar_p),
				("m_data8Char", c_char_p),
				("m_data16Char", c_wchar_p)	
			]
		_fields_ = [
			("m_refCount", c_uint32),
			("m_length", c_uint),
			("m_data", WTFStringData),
			("m_hashAndFlags", c_uint)
		]
		
		def is_8bit(self):
			return self.m_hashAndFlags & 4 != 0
			
		def to_str(self):
			if self.is_8bit():
				return string_at(self.m_data.m_data8, self.m_length).decode()
			return wstring_at(self.m_data.m_data16, self.m_length).decode()
			
	WTFStringPtr = POINTER(POINTER(WTFString))
	
	# representation of context CallbackData
	class CallbackData(Structure):
		pass
	CallbackDataPtr = POINTER(CallbackData)
	CallbackData._fields_ = [
			("next", CallbackDataPtr),
			("context", c_void_p),
			("preservedException", c_void_p),
			("calleeValue", c_void_p),
			("thisValue", c_void_p),
			("argumentCount", c_size_t),
			("arguments", c_void_p),
			("currentArguments", c_void_p)
		]
	
	_runtime_vm = None
	_runtime_context = None
	_runtimes = {}
	_runtimes_contexts = {}
	_runtime_cleanups = []
	@classmethod
	def new_runtime(cls, runtime_class, *args, **kwargs):
		if runtime_class is None:
			raise ValueError("runtime_class must be specified")
		return runtime_class(*args, **kwargs)
	
	# runtime singleton access
	@classmethod
	def runtime(cls, runtime_class = None):
		if runtime_class is None:
			runtime_class = javascript_runtime
		runtime = cls._runtimes.get(runtime_class)
		if runtime is None:
			if cls._runtime_vm is None:
				cls._runtime_vm = cls.vm_allocate()
				cls._runtime_context = cls.context_allocate(cls._runtime_vm)
			runtime = cls.new_runtime(runtime_class, cls._runtime_vm, cls._runtime_context)
			cls._runtimes[runtime_class] = runtime
		return runtime

	@classmethod
	def _runtimes_cleanup(cls):
		cls.context_deallocate(cls._runtime_context)
		cls.vm_deallocate(cls._runtime_vm) # if we destroyed the last singleton runtime reference cleanup shared context and vm  
		for cleanup in cls._runtime_cleanups:
			cleanup()
		# reset everything
		cls._runtimes = {}
		cls._runtime_cleanups = []
		cls._runtimes_contexts = {}
		cls._runtime_vm = None
		cls._runtime_context = None

	@classmethod
	def context(cls, runtime_class = None):
		if runtime_class is None:
			runtime_class = javascript_runtime
		context = cls._runtimes_contexts.get(runtime_class)
		if context is None:
			runtime = cls.runtime(runtime_class)
			context = runtime.context()
			cls._runtimes_contexts[runtime_class] = context
		return context

	@classmethod
	def javascript(cls):
		return cls.context(javascript_runtime)
	#aliases
	js = javascript

	@classmethod
	def webassembly(cls):
		return cls.context(wasm_runtime)
	#aliases
	wasm = webassembly

	@classmethod
	def destroy(cls):
		for typ,context in dict(cls._runtimes_contexts).items():
			context.destroy()
		for typ,runtime in dict(cls._runtimes).items():
			runtime.destroy()

	@classmethod
	def vm_allocate(cls):
		vm = jscore.JSVirtualMachine.alloc().init()
		retain_global(vm)
		return vm
	
	@classmethod
	def vm_deallocate(cls, vm):
		release_global(vm)
	
	@classmethod
	def runtime_deallocate(cls, runtime, vm_owner):
		vm = runtime.vm
		if vm_owner:
			cls.vm_deallocate(vm)
		runtime.vm = None # always drop the vm reference as the runtime is done with it
		runtime_scripts = list(runtime.scripts)
		def cleanup():
			released = [] # avoid releasing more than once
			for script in runtime_scripts:
				if not script in released:
					if isinstance(script, jsscript_ref):
						script.release()
					else:
						release_global(script)
					released.append(script)
		if vm_owner:
			cleanup()
		else:
			cls._runtime_cleanups.append(cleanup)
		key = runtime.__class__
		rt = cls._runtimes.get(key)
		if runtime is rt: # remove destroyed runtime if its a tracked singleton instance
			del cls._runtimes[key]
			if len(cls._runtimes) == 0:
				cls._runtimes_cleanup()
	
	_context_lookup = {}
	_prototype_lookup = {}
	@classmethod
	def context_allocate(cls, vm):
		context = jscore.JSContext.alloc().initWithVirtualMachine_(vm)
		retain_global(context)
		context.setInspectable(True)
		context_ref = context.JSGlobalContextRef()
		metadata = cls._context_metadata(context, context_ref, dict(cls._prototype_lookup))
		cls._context_lookup[context] = metadata
		cls._context_lookup[context_ref.value] = metadata
		return context
	
	@classmethod
	def context_deallocate(cls, context):
		context_ref = context.JSGlobalContextRef()
		metadata = cls._context_lookup[context]
		del cls._context_lookup[context]
		del cls._context_lookup[context_ref.value]
		release_global(context)

	@classmethod
	def context_eval(cls, context, script, sourceUrl = None):
		result = None
		if sourceUrl is None or sourceUrl.strip() == '':
			result = context.evaluateScript_(script)
		else:
			result = context.evaluateScript_withSourceUrl_(script, sourceUrl)
		result = ObjCInstance(result)
		ex = context.exception()
		if ex is not None:
			context.setException(None) # clear exception if set
		return result, ex

	@classmethod
	def context_ref_to_context(cls, context_ref):
		if context_ref is None:
			return None
		return cls._context_metadata.get(context_ref).context
	
	class _prototype_metadata:
		def __init__(self, name, layout):
			self.name = name
			self.layout = layout
	
	class _context_metadata:
		_context_lookup = None
		def __init__(self, context, context_ref, prototypes):
			self._context_lookup[context] = self
			self._context_lookup[context_ref.value] = self
			self.context = context
			self.context_ref = context_ref
			self.jsvalueref_to_jsvalue_object = jscore.JSValue.valueWithNewObjectInContext_(context)
			self.jsvalueref_to_jsvalue_object_ref = self.jsvalueref_to_jsvalue_object.JSValueRef()
			self.undefined_jsvalue = jscore.JSValue.valueWithUndefinedInContext_(context)
			get_prototypes,ex = jscore.context_eval(self.context, """(function(){
				return function(prototypes) {
					const wrappers = {};
					for(const [name, metadata] of Object.entries(prototypes)) {
						const _class = this[name];
						const _prototype = _class.prototype;
						const wrapper = {
							"_class_": _class,
							"_prototype_": _prototype
						};
						for(const field of metadata.layout) {
							wrapper[field] = _prototype[field];
						}
						wrappers[name] = wrapper;
					}
					return wrappers;
				};
			})();""")
			js_get_prototypes = jscore.jsvalue_to_py(get_prototypes)
			js_prototypes = js_get_prototypes.call(prototypes)
			self.prototypes = {}
			for key,prototype in js_prototypes.jsobject:
				_class = (~prototype._class_).JSValueRef()
				_prototype = (~prototype._prototype_).JSValueRef()
				self.prototypes[_class.value] = prototype
				self.prototypes[_prototype.value] = prototype
		
		@classmethod
		def get(cls, id):
			if isinstance(id, c_void_p):
				return cls._context_lookup[id.value]
			return cls._context_lookup[id]

	_context_metadata._context_lookup = _context_lookup
	
	@classmethod
	def prototype_register(cls, name, layout):
		metadata = cls._prototype_metadata(name, layout)
		cls._prototype_lookup[name] = metadata
	
	# jscore values conversions 
	@classmethod
	def jsstringref_to_py(cls, str_ref):
		chars_len = jscore.JSStringGetLength(str_ref)
		chars_ref = jscore.JSStringGetCharactersPtr(str_ref)
		str_utf16 = string_at(chars_ref, chars_len*2)
		str_decoded = str_utf16.decode('utf-16')
		return str_decoded
	
	@classmethod
	def str_to_jsstringref(cls, str_py):
		if str_py is None:
			return None
		str_py = str(str_py)
		str_len = len(str_py)
		str_utf16 = objc.c_array(str_py.encode("utf-16le"))
		str_ref = jscore.JSStringCreateWithCharacters(str_utf16, str_len)
		return cast(cls.JSStringRetain(str_ref), c_void_p)

	@classmethod
	def jsscript_source_to_str(cls, script):
		if not objc.ns_subclass_of(script, cls.JSScript):
			raise Exception(f"'{script}' is not a JSScript instance")
		source_ptr = cast(script.source(), cls.WTFStringPtr)
		if source_ptr is None or source_ptr.contents is None:
			return None
		source_wtf = source_ptr.contents.contents
		if source_wtf is None:
			return None
		return source_wtf.to_str()

	@classmethod
	def jsobjectref_keys(cls, context_ref, value_ref):
		names = []
		names_ref = jscore.JSObjectCopyPropertyNames(context_ref, value_ref)
		count = jscore.JSPropertyNameArrayGetCount(names_ref)
		for i in range(count):
			str_ref = jscore.JSPropertyNameArrayGetNameAtIndex(names_ref, i)
			name = cls.jsstringref_to_py(str_ref)
			names.append(name)
		jscore.JSPropertyNameArrayRelease(names_ref)
		return names
	
	@classmethod
	def jsvalue_get_refs(cls, value):
		context_ref = value.context().JSGlobalContextRef()
		value_ref = value.JSValueRef()
		return context_ref, value_ref
	
	@classmethod
	def jsvalueref_to_jsvalue(cls, context_ref, value_ref, index = 0, metadata = None):
		# obtain a jsvalue by setting it by value_ref into an object with the c-api
		# then retrieving it from the objc side of that objects jsvalue accessor.
		# this works where other methods that are more suggestive towards this purpose don't such as valueWithJSValueRef:inContext:
		# JSValue.initWithValue:inContext: or the wrapperMap, which either crash or don't seem to yield an expected jsvalue for the ref given...
		if metadata is None:
			metadata = cls._context_metadata.get(context_ref)
		ex_ref = c_void_p(None)
		cls.JSObjectSetPropertyAtIndex(context_ref, metadata.jsvalueref_to_jsvalue_object_ref, index, value_ref, byref(ex_ref))
		jsvalue = metadata.jsvalueref_to_jsvalue_object.valueAtIndex(index)
		metadata.jsvalueref_to_jsvalue_object.setValue_atIndex_(index, metadata.undefined_jsvalue)
		return jsvalue
	
	@classmethod
	def jsvalueref_get_prototype(cls, context_ref, value_ref):
		prototype_ref = cls.JSObjectGetPrototype(context_ref, value_ref)
		metadata = cls._context_metadata.get(context_ref)
		metadata_prototype = metadata.prototypes.get(prototype_ref)
		
		if metadata_prototype is None:
			seen = []
			for key,p in dict(metadata.prototypes).items():
				class_ref = (~p._class_).JSValueRef()
				if not class_ref in seen and jscore.JSValueIsObjectOfClass(context_ref, value_ref, class_ref):
					return (~p).JSValueRef()
				seen.append(class_ref)
		else:
			return (~metadata_prototype).JSValueRef()
		return cast(prototype_ref, c_void_p)
	
	@classmethod
	def jsvalue_get_prototype(cls, value, context_ref = None, value_ref = None):
		if value_ref is None:
			context_ref, value_ref = cls.jsvalue_get_refs(value)
		prototype_ref = cls.jsvalueref_get_prototype(context_ref, value_ref)
		return cls.jsvalueref_to_jsvalue(context_ref, prototype_ref)
	
	@classmethod
	def jsvalue_jsobject_to_py(cls, value, context_ref = None, value_ref = None, parent_ref = None):
		if value_ref is None:
			context_ref, value_ref = cls.jsvalue_get_refs(value)
		if jscore.JSObjectIsFunction(context_ref, value_ref):
			return javascript_function(value, context_ref, value_ref, parent_ref)
		keys = cls.jsobjectref_keys(context_ref, value_ref)
		if value.isArray():
			count = len(keys)
			items = []
			for i in range(count):
				v = value.valueAtIndex_(i)
				v = cls.jsvalue_to_py(v, value_ref)
				items.append(v)
			return items
		prototype = cls.jsvalue_get_prototype(value, context_ref, value_ref)
		obj = cls.jsvalue_to_py(prototype, value_ref if parent_ref is None else parent_ref)
		if javascript_value.is_null_or_undefined(obj):
			obj = {}
		keys = set(keys + list(obj.keys())) # combine object and prototype keys
		#keys.discard("_class_") # hide these fields?
		#keys.discard("_prototype_")
		for key in list(keys):
			v = value.valueForProperty_(key)
			v = cls.jsvalue_to_py(v, value_ref if parent_ref is None else parent_ref)
			if not javascript_value.is_undefined(v):
				 # avoid setting undefined values as this can unset inherited values
				obj[key] = v
		return obj

	@classmethod
	def jsvalue_to_py(cls, value, parent_ref = None):
		if javascript_value.is_null_or_undefined(value):
			return value
			
		if not objc.ns_subclass_of(value, cls.JSValue):
			raise Exception("Value must be JSValue")
		
		if value.isUndefined():
			return javascript_value.undefined
		
		if value.isNull():
			return None
			
		if value.isBoolean():
			return value.toBool()
		
		if value.isNumber() or value.isString() or value.isDate():
			return objc.ns_to_py(value.toObject())
		
		if value.isSymbol():
			return javascript_symbol(value)
		
		return cls.jsvalue_jsobject_to_py(value, parent_ref = parent_ref)

	@classmethod
	def jsvalue_is_object(cls, value, context_ref = None, value_ref = None):
		if javascript_value.is_undefined(value) or not value.isObject():
			return False
		if value_ref is None:
			context_ref, value_ref = cls.jsvalue_get_refs(value)
		if jscore.JSObjectIsFunction(context_ref, value_ref):
			return False
		return True
		
	@classmethod
	def jsvalue_is_array_type(cls, value, typedArrayType, context_ref = None, value_ref = None):
		if not objc.ns_subclass_of(value, jscore.JSValue):
			return False
		if value_ref is None:
			context_ref, value_ref = cls.jsvalue_get_refs(value)
		ex = c_void_p(None)
		arrayType = cls.JSValueGetTypedArrayType(context_ref, value_ref, byref(ex))
		return arrayType == typedArrayType
	
	@classmethod
	def jsobject_get_keys(cls, value, context_ref = None, value_ref = None):
		if javascript_value.is_undefined(value) or not value.isObject():
			return []
		if value_ref is None:
			context_ref, value_ref = cls.jsvalue_get_refs(value)
		if jscore.JSObjectIsFunction(context_ref, value_ref):
			return []
		return cls.jsobjectref_keys(context_ref, value_ref)
	
	@classmethod
	def jsobjectref_to_py(cls, context_ref, value_ref, parent_ref = None):
		ex = c_void_p(None)
		value_ref = cls.JSValueToObject(context_ref, value_ref, byref(ex))
		if cls.JSObjectIsFunction(context_ref, value_ref):
			str_ref = cls.JSValueToStringCopy(context_ref, value_ref, byref(ex))
			source = None
			if str_ref:
				source = cls.jsstringref_to_py(str_ref)
			return javascript_function(None, context_ref, value_ref, parent_ref, source)
		names_ref = cls.JSObjectCopyPropertyNames(context_ref, value_ref)
		count = cls.JSPropertyNameArrayGetCount(names_ref)
		obj = None
		if cls.JSValueIsArray(context_ref, value_ref):
			obj = []
			for i in range(count):
				key_ref = cls.JSPropertyNameArrayGetNameAtIndex(names_ref, i)
				jsvalue_ref = cls.JSObjectGetProperty(context_ref, value_ref, key_ref, byref(ex))
				obj.append(cls.jsvalueref_to_py(context_ref, jsvalue_ref, value_ref))
		else:
			prototype_ref = cls.jsvalueref_get_prototype(context_ref, value_ref)
			obj = cls.jsvalueref_to_py(context_ref, prototype_ref, value_ref if parent_ref is None else parent_ref)
			if javascript_value.is_null_or_undefined(obj):
				obj = {}
			for i in range(count):
				key_ref = cls.JSPropertyNameArrayGetNameAtIndex(names_ref, i)
				jsvalue_ref = cls.JSObjectGetProperty(context_ref, value_ref, key_ref, byref(ex))
				key = cls.jsstringref_to_py(key_ref)
				obj[key] = cls.jsvalueref_to_py(context_ref, jsvalue_ref, value_ref)
		cls.JSPropertyNameArrayRelease(names_ref)
		return obj
	
	@classmethod
	def jsvalueref_to_py(cls, context_ref, value_ref, parent_ref = None):
		if value_ref is None:
			return None
		if cls.JSValueIsUndefined(context_ref, value_ref):
			return javascript_value.undefined
		if cls.JSValueIsNull(context_ref, value_ref):
			return None
		if cls.JSValueIsBoolean(context_ref, value_ref):
			return cls.JSValueToBoolean(context_ref, value_ref)
		if cls.JSValueIsNumber(context_ref, value_ref):
			ex = c_void_p(None)
			return cls.JSValueToNumber(context_ref, value_ref, byref(ex))
		if cls.JSValueIsString(context_ref, value_ref):
			ex = c_void_p(None)
			str_ref = cls.JSValueToStringCopy(context_ref, value_ref, byref(ex))
			if str_ref:
				return cls.jsstringref_to_py(str_ref)
			return ""
		if cls.JSValueIsDate(context_ref, value_ref):
			ex = c_void_p(None)
			str_ref = cls.JSValueCreateJSONString(context_ref, value_ref, 0, byref(ex))
			json_date = cls.jsstringref_to_py(str_ref)
			return datetime.strptime(json_date, '"%Y-%m-%dT%H:%M:%S.%fZ"').replace(tzinfo=timezone.utc)
		if cls.JSValueIsSymbol(context_ref, value_ref):
			ex = c_void_p(None)
			str_ref = cls.JSValueToStringCopy(context_ref, value_ref, byref(ex))
			symbol = cls.jsstringref_to_py(str_ref)
			return javascript_symbol(symbol)
		if cls.JSValueIsObject(context_ref, value_ref):
			return cls.jsobjectref_to_py(context_ref, value_ref, parent_ref)
		raise NotImplementedError("Unknown value_ref type")

	@classmethod
	def _py_to_jsvalueref(cls, context_ref, value, parent_ref = None):
		if value is None:
			return cls.JSValueMakeNull(context_ref)
		if javascript_value.is_undefined(value):
			return cls.JSValueMakeUndefined(context_ref)
		if isinstance(value, c_void_p):
			return value # assume a void pointer is a value ref
		if objc.ns_subclass_of(value, cls.JSValue):
			return value.JSValueRef() # return refs from existing JSValues
		if objc.ns_subclass_of(value, cls.JSScript):
			raise Exception("JSScript")
		# convert
		if isinstance(value, bool):
			return cls.JSValueMakeBoolean(context_ref, value)
		if isinstance(value, int) or isinstance(value, float):
			return cls.JSValueMakeNumber(context_ref, value)
		if isinstance(value, datetime):
			value_utc = datetime.fromtimestamp(value.timestamp(), tz = timezone.utc)
			value_str = value_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
			str_ref = jscore.str_to_jsstringref(value_str)
			return cls.JSValueMakeFromJSONString(context_ref, str_ref)
		if isinstance(value, str):
			str_ref = jscore.str_to_jsstringref(value)
			return cls.JSValueMakeString(context_ref, str_ref)
		if isinstance(value, javascript_function):
			source = str(value)
			value_ref = javascript_function.from_source(source, context_ref, parent_ref).compile()
			return value_ref
		if callable(value):
			value = javascript_callback(value)
		if isinstance(value, javascript_callback):
			value_ref = value.get_jsvalue_ref(context_ref, parent_ref)
			return value_ref
		if isinstance(value, bytes):
			count = len(value)
			ex_ref = c_void_p(None)
			value_ref = cls.JSObjectMakeTypedArray(context_ref, cls.kJSTypedArrayTypeUint8Array, count, byref(ex_ref))
			bytes_ptr = jscore.JSObjectGetTypedArrayBytesPtr(context_ref, value_ref, byref(ex_ref))
			if bytes_ptr is not None:
				memmove(bytes_ptr, value, count)
			return value_ref
		if objc.ns_subclass_of(value, NSData):
			count = value.length()
			ex_ref = c_void_p(None)
			value_ref = cls.JSObjectMakeTypedArray(context_ref, cls.kJSTypedArrayTypeUint8Array, count, byref(ex_ref))
			bytes_ptr = jscore.JSObjectGetTypedArrayBytesPtr(context_ref, value_ref, byref(ex_ref))
			if bytes_ptr is not None:
				value.getBytes_length_(bytes_ptr, count)
			return value_ref
		if isinstance(value, list) or isinstance(value, set):
			ex_ref = c_void_p(None)
			value_ref = cls.JSObjectMakeArray(context_ref, 0, None, byref(ex_ref))
			count = len(value)
			for i in range(count):
				val_ref = cls.py_to_jsvalueref(context_ref, value[i], value_ref)
				cls.JSObjectSetPropertyAtIndex(context_ref, value_ref, i, val_ref, byref(ex_ref))
			return value_ref
		if not isinstance(value, dict):
			try:
				value = vars(value)
			except Exception as e:
				value = {}
				#print(type(value), value)
				#raise e
		value_ref = cls.JSObjectMake(context_ref, None, None)
		ex_ref = c_void_p(None)
		for k,v in value.items():
			key_ref = cls.str_to_jsstringref(k)
			val_ref = cls.py_to_jsvalueref(context_ref, v, value_ref)
			cls.JSObjectSetProperty(context_ref, value_ref, key_ref, val_ref, 0, byref(ex_ref))
		return value_ref
		
	@classmethod
	def py_to_jsvalueref(cls, context_ref, value, parent_ref = None):
		value_ref = cls._py_to_jsvalueref(context_ref, value, parent_ref)
		#cls.JSValueProtect(context_ref, value_ref)
		return cast(value_ref, c_void_p) # ensure a c_void_p
	
	@classmethod
	def py_to_jsvalue(cls, context, value, parent = None):
		if value is None:
			return cls.JSValue.valueWithNullInContext_(context)
		if javascript_value.is_undefined(value):
			return cls.JSValue.valueWithUndefinedInContext_(context)
		if objc.ns_subclass_of(value, jscore.JSValue) or objc.ns_subclass_of(value, jscore.JSScript):
			return value # pass back jsvalue instances as-is
		if isinstance(value, bool):
			return cls.JSValue.valueWithBool_inContext_(value, context)
		if isinstance(value, int) or isinstance(value, float) or isinstance(value, str):
			return cls.JSValue.valueWithObject_inContext_(ns(value), context)
		if isinstance(value, datetime):
			timestamp = value.timestamp()
			return cls.JSValue.valueWithObject_inContext_(cls.initWithTimeIntervalSince1970_(timestamp), context)
		if isinstance(value, javascript_function):
			jsvalue = value.jsvalue
			if jsvalue is not None:
				return jsvalue
			if value.is_native:
				raise ValueError("Cannot evaluate native functions (this shouldn't be reachable!')")
			source = str(value)
			# this obtains a new jsvalue for a javascript function by evaluating it in the context, 
			# further escaping and resolving may be required here...
			jsvalue, ex  = cls.context_eval(context, f'(function() {{ return ({source}); }})()') 
			return jsvalue
		if callable(value):
			value = javascript_callback(value)
		if isinstance(value, javascript_callback):
			jsvalue = value.get_jsvalue(context, parent)
			return jsvalue
		if isinstance(value, bytes):
			count = len(value)
			jsvalue = cls.context_eval(context, f"new Uint8Array({count});")
			context_ref, value_ref = cls.jsvalue_get_refs(jsvalue)
			ex_ref = c_void_p(None)
			bytes_ptr = jscore.JSObjectGetTypedArrayBytesPtr(context_ref, value_ref, byref(ex_ref))
			if bytes_ptr is not None:
				memmove(bytes_ptr, value, count)
			return jsvalue
		if objc.ns_subclass_of(value, NSData):
			count = value.length()
			jsvalue = cls.context_eval(context, f"new Uint8Array({count});")
			context_ref, value_ref = cls.jsvalue_get_refs(jsvalue)
			ex_ref = c_void_p(None)
			bytes_ptr = jscore.JSObjectGetTypedArrayBytesPtr(context_ref, value_ref, byref(ex_ref))
			if bytes_ptr is not None:
				value.getBytes_length_(bytes_ptr, count)
			return jsvalue
		if isinstance(value, list) or isinstance(value, set):
			jsvalue = cls.JSValue.valueWithNewArrayInContext_(context)
			for i in range(len(value)):
				val = cls.py_to_jsvalue(context, value[i], jsvalue)
				jsvalue.setValue_atIndex_(val, i)
			return jsvalue
		if not isinstance(value, dict):
			try:
				value = vars(value)
			except Exception as e:
				value = {}
				#print(type(value), value)
				#raise e
		jsvalue = cls.JSValue.valueWithNewObjectInContext_(context)
		for k,v in value.items():
			val = cls.py_to_jsvalue(context, v, jsvalue)
			jsvalue.setValue_forProperty_(val, k)
		return jsvalue

	@classmethod
	def py_to_js(cls, value):
		value = jsobject_accessor.unwrap(value)
		return json.dumps(value, cls=javascript_encoder)
	
	_initialised = False
	@classmethod
	def _init(cls):
		if cls._initialised:
			return
		cls.prototype_register("Error", ["name", "message", "toString"])
		cls.prototype_register("EvalError", ["name", "message", "toString"])
		cls.prototype_register("RangeError", ["name", "message", "toString"])
		cls.prototype_register("ReferenceError", ["name", "message", "toString"])
		cls.prototype_register("SyntaxError", ["name", "message", "toString"])
		cls.prototype_register("TypeError", ["name", "message", "toString"])
		cls.prototype_register("URIError", ["name", "message", "toString"])
		cls.prototype_register("AggregateError", ["name", "message", "toString"])
		#cls.prototype_register("InternalError", ["name", "message", "toString"])
		cls.prototype_register("Promise", ["then", "catch", "finally"])
		cls._initialised = True

# init metadata
jscore._init()

class javascript_encoder(json.JSONEncoder):
	# An overriden json encoder to write javascript objects encoding functions / raw literal js 
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.raw = False
	
	def default(self, obj):
		if javascript_value.is_undefined(obj):
			return None
		elif isinstance(obj, datetime):
			self.raw = True
			return obj.replace(tzinfo=timezone.utc).strftime('new Date("%Y-%m-%dT%H:%M:%S.%fZ")')
		elif isinstance(obj, bytes):
			self.raw = True
			return "".join(["new Uint8Array(",str(list(obj)),")"])
		elif isinstance(obj, javascript_function):
			self.raw = True
			return str(obj)
		return json.JSONEncoder.default(self, obj)
	
	def raw_unescape(self, chunk):
		raw = json.loads(chunk) #unescape
		return str(raw) # ensure string result
	
	def encode(self, o):
		chunks = []
		for chunk in super().iterencode(o):
			if self.raw: # handle chunk as a literal raw string
				chunk = self.raw_unescape(chunk)  #unescape the string
				self.raw = False
			chunks.append(chunk)
		return ''.join(chunks)

			
# types for js values
class javascript_undefined_value:
	def __repr__(self):
		return "undefined"

# not sure what this is...
class javascript_symbol:
	def __init__(self, symbol):
		self.symbol = symbol
		print(f"javascript_symbol {symbol}")


class javascript_function:
	def __init__(self, jsvalue = None, context_ref = None, value_ref = None, parent_ref = None, source = None):
		self.jsvalue = jsvalue
		self.context_ref = context_ref
		self.value_ref = value_ref
		self.parent_ref = parent_ref
		self.source = source

	def compile(self, context_ref = None):
		if context_ref is None:
			context_ref = self.context_ref
		if context_ref is None:
			raise ImportError("Cannot compile function from source without context_ref")
		if self.source is None:
			raise ImportError("Cannot compile function with no source")
		self.source = self.source.strip()
		name_match = re.match("function([^\(]*)\(", self.source)
		fn_name = name_match.group(0).strip()
		params_match = re.match("function[^\(]*\(([^\)]*)\)", self.source)
		params = params_match.group(0).split(",")
		params_refs = []
		for p in params:
			param = p.strip()
			if param != "":
				param_ref = jscore.str_to_jsstringref(param)
				params_refs.append(param_ref)
		params_refs = objc.c_array(params_refs)
		name_ref = jscore.str_to_jsstringref(fn_name)
		body = body[body.index('{'):body.rindex('}')]
		body_ref = jscore.str_to_jsstringref(body)
		ex_ref = c_void_p(None)
		self.value_ref = jscore.JSObjectMakeFunction(context_ref, name_ref, params_count, params_refs, body_ref, None, 0, by_ref(ex_ref))
		self.context_ref = context_ref
		if ex_ref.value is not None:
			exception = jscore.jsvalueref_to_py(context_ref, ex_ref)
			raise ImportError("Exception compiling function: {exception}")
		return self.value_ref
	
	def ns_arg(self, context, arg):
		if isinstance(arg, dict):
			copy = {}
			for k,v in arg.items():
				copy[k]=self.ns_arg(context, v)
			return copy
		if isinstance(arg, list):
			copy = []
			for i in range(len(arg)):
				copy.append(self.ns_arg(context, arg[i]))
			return copy
		return jscore.py_to_jsvalue(context, arg)
	
	def ns_args(self, context, args):
		args = list(args)
		args = self.ns_arg(context, args)
		nsargs = ns(args)
		return nsargs

	def call(self, *args, this = None):
		if this is None and self.parent_ref is not None:
			this = self.parent_ref
		if self.jsvalue is not None and this is None:
			context = self.jsvalue.context()
			nsargs = self.ns_args(context, args)
			self.jsvalue.context().setException_(None)
			value = self.jsvalue.callWithArguments_(nsargs)
			exception = self.jsvalue.context().exception()
			if exception is not None:
				self.jsvalue.context().setException_(None)
				raise Exception(str(exception))
			return javascript_value(value)
		if self.jsvalue is not None and self.context_ref is None and self.value_ref is None:
			self.context_ref, self.value_ref = jscore.jsvalue_get_refs(self.jsvalue)
		if self.source is not None and self.value_ref is None:
			if self.context_ref is not None:
				self.compile()
			else:
				raise NotImplementedError("Cannot call source only functions without a context_ref")
		
		if self.context_ref is not None and self.value_ref is not None:
			count = len(args)
			args_ref = None
			if count > 0:
				args_ref = objc.c_array(count, lambda i: jscore.py_to_jsvalueref(self.context_ref, args[i]), typ = c_void_p)
			this_ref = None
			if isinstance(this, c_void_p):
				this_ref = this
			elif objc.ns_subclass_of(this, jscore.JSValue):
				this_ref = this.JSValueRef()
			exception_ref = c_void_p(None)
			value_ref = jscore.JSObjectCallAsFunction(self.context_ref, self.value_ref, this_ref, count, args_ref, byref(exception_ref))
			if exception_ref.value is not None:
				raise Exception(jscore.jsvalueref_to_py(self.context_ref, exception_ref))
			jsvalue = jscore.jsvalueref_to_jsvalue(self.context_ref, value_ref)
			return javascript_value(jsvalue, self.context_ref, value_ref)

		raise NotImplementedError("Cannot call this type of javascript_function")

	@property
	def is_native(self):
		repr = str(self).strip()
		return re.fullmatch("function[^\{]+\{[^\[]+\[native code\][^\}]+}", repr) is not None
	
	def __call__(self, *args, **kwargs):
		return self.call(*args, **kwargs).value

	def __repr__(self):
		if self.source is not None:
			return self.source
		if self.jsvalue is not None:
			return str(self.jsvalue)
			
	def __invert__(self):
		if self.jsvalue is not None:
			return self.jsvalue
		elif self.contect_ref and self.value_ref is not None:
			return jscore.jsvalueref_to_jsvalue(self.context_ref, self.value_ref)
		raise Exception("Compile function to access jsvalue")
		
	@classmethod
	def from_source(cls, source, context = None, parent_ref = None):
		context_ref = None
		if isinstance(context, c_void_p):
			context_ref = context
		elif context is not None:
			if isinstance(context, jscore_context):
				context = context.context
			if objc.ns_subclass_of(context, jscore.JSContext):
				context_ref = context.JSGlobalContextRef()
		return cls(source=source, context_ref=context_ref, parent_ref=parent_ref)


class javascript_callback:
	def __init__(self, callback, name = None):
		self.callback = callback
		self.name = name
		self.callback_ref = None
		self.context_ref = None
		self.value_ref = None
		self._jsvalue = None
		
	def compile(self, context_ref = None, parent_ref = None):
		if context_ref is None:
			context_ref = self.context_ref
		if context_ref is None:
			raise Exception("Context is required to compile callbacks")
		if self.value_ref is not None:
			raise Exception("Cannot recompile callbacks")
		if self.name is None:
			self.name = javascript_callback.unique_name()
		name_ref = jscore.str_to_jsstringref(self.name)
		self.callback_ref = jscore.JSObjectCallAsFunctionCallback(self._invoke_callback)
		value_ref = jscore.JSObjectMakeFunctionWithCallback(context_ref, name_ref, self.callback_ref)
		jscore.JSValueProtect(context_ref, value_ref)
		self.context_ref = context_ref
		self.value_ref = value_ref
		if parent_ref is None:
			parent_ref = jscore.JSContextGetGlobalObject(self.context_ref)
		ex = c_void_p(None)
		jscore.JSObjectSetProperty(self.context_ref, parent_ref, name_ref, value_ref, 0, byref(ex))
	
	def get_jsvalue_ref(self, context_ref, parent_ref = None):
		if self.context_ref is not None and self.context_ref != context_ref:
			raise Exception("Cannot change context")
		if self.value_ref is None:
			self.compile(context_ref, parent_ref)
		return self.value_ref
	
	def get_jsvalue(self, context, parent = None):
		context_ref = context.JSGlobalContextRef()
		parent_ref = None
		if parent is not None:
			parent_ref = parent.JSValueRef()
		if self._jsvalue is None:
			value_ref = self.get_jsvalue_ref(context_ref, parent_ref)
			if parent is None:
				parent = context.globalObject()
			self._jsvalue = jscore.jsvalueref_to_jsvalue(context_ref, value_ref)
		return self._jsvalue

	def _invoke_callback(self, ctx, funcObj, thisObj, args_count, args, ex):
		ctx = c_void_p(ctx)
		funcObj = c_void_p(funcObj)
		thisObj = c_void_p(thisObj)
		callback_args = []
		for i in range(args_count):
			arg = c_void_p.from_address(args + (i * sizeof(c_void_p)))
			arg_value = jscore.jsvalueref_to_py(ctx, arg)
			if isinstance(arg_value, dict):
				arg_value = javascript_object(arg_value)
			callback_args.append(arg_value)
		returnValue = self.callback(*callback_args)
		returnJSValue_ref = jscore.py_to_jsvalueref(ctx, returnValue)
		return returnJSValue_ref.value
		
	def __invert__(self):
		if self._jsvalue is not None:
			return self.jsvalue
		elif self.contect_ref and self.value_ref is not None:
			return jscore.jsvalueref_to_jsvalue(self.context_ref, self.value_ref)
		raise Exception("Compile function to access jsvalue")

	_name_count = 0
	@classmethod
	def unique_name(cls):
		name = f"python_callback_{cls._name_count}"
		cls._name_count = cls._name_count + 1
		return name
		
	@classmethod
	def is_callable(cls, func):
		return not isinstance(func, javascript_function) and callable(func)
		
	@classmethod
	def wrap(cls, context, value, name = None):
		if javascript_callback.is_callable(value):
			return context.callback(value, name)
		if isinstance(value, dict):
			for k, v in value.items():
				value[k] = cls.wrap(context, v, k)
		elif isinstance(value, list):
			for i in range(len(value)):
				k = str(i)
				v = value[i]
				value[i] = cls.wrap(context, v, k)
		return value

class javascript_object(dict):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.___init___ = True
		
	def __getattr__(self, key):
		value = self.get(key, javascript_value.undefined)
		if isinstance(value, dict):
			value = javascript_object(value)
		return value
		
	def __setattr__(self, key, value):
		if not self.__dict__.get("___init___", False):
			super().__setattr__(key, value)
		else:
			self[key] = value

class jsvalue_accessor:
	def __init__(self, jsvalue = None, context_ref = None, value_ref = None):
		self.___jsvalue___ = jsvalue
		if jsvalue is None:
			self.___jsvalue___ = jscore.jsvalueref_to_jsvalue(context_ref, value_ref)

	def __iter__(self):
		self.___keys___ = jscore.jsobject_get_keys(self.___jsvalue___)
		self.___keys___ = iter(self.___keys___)
		return self
		
	def __next__(self):
		key = next(self.___keys___)
		return key, self.___get___(key)
		
	def __getattr__(self, key):
		v = self.___get___(key)
		return v
		
	def __getitem__(self, key):
		v = self.___get___(key)
		if v is None:
			raise KeyError()
		return v

	def ___get___(self, name):
		jsvalue = self.___jsvalue___
		if not jsvalue.hasProperty_(name):
			return None
		v = jsvalue.valueForProperty_(name)
		return jsvalue_accessor(v)

	def __repr__(self):
		return str(jscore.jsvalue_to_py(self.___jsvalue___))
		
	def __invert__(self):
		return self.___jsvalue___


class javascript_value:
	undefined = javascript_undefined_value()
	@classmethod
	def is_undefined(cls, value):
		return value is cls.undefined
	
	@classmethod
	def is_null(cls, value):
		return value is None
	
	@classmethod
	def is_null_or_undefined(cls,value):
		return cls.is_null(value) or cls.is_undefined(value)

	def __init__(self, jsvalue = None, context_ref = None, value_ref = None):
		if jsvalue is None and context_ref is None and value_ref is None:
			raise ArgumentError("Either jsvalue or context_ref and value_ref must be specified")
		self._jsvalue = jsvalue
		self._context_ref = context_ref
		self._value_ref = value_ref
		self._val = None
		self._cached = False
	
	@property
	def jsvalue(self):
		if self._jsvalue is not None:
			return self._jsvalue
		if self._context_ref is not None and self._value_ref is not None:
			self._jsvalue = jscore.jsvalueref_to_jsvalue(self._context_ref, self._value_ref)
		else:
			raise ValueError("Invalid javascript_value, JSValue and refs are null")
		return self._jsvalue
		
	@property
	def jsobject(self):
		return jsvalue_accessor(self._jsvalue, self._context_ref, self._value_ref)

	@property
	def value(self):
		if not self._cached:
			if self._jsvalue is not None:
				self._val = jscore.jsvalue_to_py(self._jsvalue)
			elif self._context_ref is not None and self._value_ref is not None:
				self._val = jscore.jsvalueref_to_py(self._context_ref, self._value_ref)
			else:
				self._val = javascript_value.undefined
			if isinstance(self._val, dict):
				self._val = javascript_object(self._val)
			self._cached = True
		return self._val
		
	def __repr__(self):
		return str(self.value)
		
	def __invert__(self):
		return self.jsvalue


class jsscript_ref:
	def __init__(self, runtime, url, source):
		self.runtime = runtime
		self.vm = runtime.vm
		self.context_group_ref = self.vm.JSContextGroupRef()
		self.url = url
		self.source = source
		self.url_ref = jscore.str_to_jsstringref(url)
		self.source_ref = jscore.str_to_jsstringref(source)
		error_ref = c_void_p(None)
		error_line = c_void_p(0)
		script_ref = jscore.JSScriptCreateFromString(self.context_group_ref, self.url_ref, 0, self.source_ref, byref(error_ref), byref(error_line))
		self.script_ref = script_ref
		self.error_ref = error_ref
		self.error_line = error_line
		if self.script_ref:
			jscore.JSScriptRetain(self.script_ref)
	
	def release(self):
		if self.runtime.vm is not None:
			raise Exception("VM must be released before releasing scripts")
		jscore.JSScriptRelease(self.script_ref) # must outlive VM
		jscore.JSStringRelease(self.source_ref)
		jscore.JSStringRelease(self.url_ref)
		
	def eval(self, context):
		context = context.context
		context_ref = context.JSGlobalContextRef()
		if not self.script_ref:
			line = self.error_line
			exception = jscore.jsvalueref_to_py(context_ref, self.error_ref)
			raise ImportError(f"Error importing script at {line}, {exception}")
		this_ref = context.globalObject()
		this_ref = this_ref.JSValueRef()
		exception_ref = c_void_p(None)
		value_ref = jscore.JSScriptEvaluate(context_ref, self.script_ref, this_ref, byref(exception_ref))
		value = jscore.jsvalueref_to_py(context_ref, value_ref)
		exception = jscore.jsvalueref_to_py(context_ref, exception_ref)
		return value, exception
		
	def __invert__(self):
		return self.script_ref


class jscore_module_loader:
	def __init__(self, context):
		self.runtime = context.runtime
		self.pycontext = context
		self.context = context.context
		self.scripts = {}
		self.modules = {}
		self.delegate = jscore.JSCoreModuleLoaderDelegate.alloc().init().autorelease()
		retain_global(self.delegate)
		self.delegate._pyinstance = weakref.ref(self)
		self.context.setModuleLoaderDelegate_(self.delegate)
		self.resolved = []
		self.failed = []
		self.attempted = []
		self.evaluated = []
		
	def release(self):
		self.context.setModuleLoaderDelegate_(None)
		release_global(self.delegate)
		self.delegate = None
		
	def fetch_module(self, module, resolve, reject):
		if module in self.evaluated:
			reject()
			return
		script = None
		try:
			script = self.load_file(module, jscore.kJSScriptTypeModule)
		except:
			pass
		if script is not None:
			self.resolved.append(module)
			resolve(script)
		else:
			self.failed.append(module)
			reject()
			
	def will_eval_module(self, url):
		self.attempted.append(url)
		pass
		
	def did_eval_module(self, url):
		self.evaluated.append(url)
		pass
		
	def get_script(self, path):
		path = self.runtime.get_file_path(path)
		sourceUrl = self.runtime.get_source_url(None, path)
		keys = [path, f"file://{path}", sourceUrl]
		for key in keys:
			module = self.modules.get(key)
			if module is not None:
				return module
			script = self.scripts.get(key)
			if script is not None:
				return script
		return None
		
	def load_script(self, script, scriptType, path, sourceUrl, source = None):
		file_path = self.runtime.get_file_path(path)
		lookup = self.modules if scriptType == jscore.kJSScriptTypeModule else self.scripts
		if source is not None:
			lookup[source] = script
		lookup[path] = script
		lookup[f"file://{file_path}"] = script
		lookup[sourceUrl] = script

	def load_source(self, source, scriptType, modulePath = None):
		lookup = self.modules if scriptType == jscore.kJSScriptTypeModule else self.scripts
		script, sourceUrl, exception = self.runtime.load_source(source, scriptType, modulePath)
		if exception is not None: 
			 raise ImportError(exception)
		self.load_script(script, scriptType, path, sourceUrl, source)
		return script

	def load_file(self, path, scriptType):
		lookup = self.modules if scriptType == jscore.kJSScriptTypeModule else self.scripts
		script, sourceUrl, exception = self.runtime.load_file(path, scriptType, sourceUrl=path)
		if exception is not None: 
			 raise ImportError(exception)
		self.load_script(script, scriptType, path, sourceUrl)
		return script


# base runtime framework
class jscore_context:
	def __init__(self, runtime, context = None):
		self.runtime = runtime
		self.context = context
		self.context_owner = self.context is None
		self.allocated = False
		self.depth = 0
		self.accessor = None
		self.callbacks = None

	def allocate(self):
		if self.context_owner:
			if self.context is not None:
				raise Exception("Context already allocated. Do not call allocate/deallocate manually.")
			self.context = jscore.context_allocate(self.runtime.vm)
		self.loader = jscore_module_loader(self)
		self.accessor = javascript_context_accessor(self)
		self.callbacks = {}
		self.allocated = True
		
	def deallocate(self):
		if self.context is None:
			raise Exception("Context already deallocated. Do not call allocate/deallocate manually.")
		self.loader.release()
		self.loader = None
		self.accessor = None
		if self.context_owner:
			jscore.context_deallocate(self.context)
			self.context = None
		self.callbacks = None
		self.allocated = False

	def alloc(self):
		if self.allocated:
			return
		self.allocate()

	def destroy(self):
		if not self.allocated:
			return
		self.deallocate()

	def __enter__(self):
		if self.depth == 0:
			self.alloc()
		self.depth = self.depth + 1
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		self.depth = self.depth - 1
		if self.depth < 0:
			raise Exception("Exit must not be called before enter, use the with keyword.")
		if self.depth == 0:
			self.destroy()
		return self
		
	def __invert__(self):
		return self.context
		
	class javascript_eval_result(javascript_value):
		def __init__(self, jsvalue, exception):
			super().__init__(jsvalue)
			self._exception = exception
		
		@property
		def exception(self):
			return self._exception
			
		def __repr__(self):
			return str({"value":self.value, "exception": self.exception})
	
	def eval(self, script, sourceUrl=None):
		self.alloc()
		result, ex = jscore.context_eval(self.context, script, sourceUrl)
		result = self.javascript_eval_result(result, ex)
		return result
	
	def eval_jsscript(self, jsscript):
		if jsscript is None:
			raise ValueError("Null JSScript pointer")
		result = self.context.evaluateJSScript(jsscript) # crashes on null or invalid script ptr
		result = ObjCInstance(result)
		ex = self.context.exception()
		if ex is not None:
			self.context.setException(None) # clear exception if set
		result = self.javascript_eval_result(result, ex)
		return result
	
	def eval_script_source(self, source, scriptType = jscore.kJSScriptTypeProgram, modulePath = None):
		script = self.loader.load_source(source, scriptType, modulePath)
		return self.eval_jsscript(script)
		
	def eval_script_file(self, path, scriptType = jscore.kJSScriptTypeProgram):
		script = self.loader.load_file(path, scriptType)
		return self.eval_jsscript(script)
		
	def eval_source(self, source):
		return self.eval_script_source(source, jscore.kJSScriptTypeProgram)
	
	def eval_file(self, path):
		return self.eval_script_file(path, jscore.kJSScriptTypeProgram)
	
	@property
	def context_ref(self):
		self.alloc()
		return self.context.JSGlobalContextRef()
		
	def callback(self, func, name = None):
		if not javascript_callback.is_callable(func):
			raise Exception(f"'{func}' is not a python callable/function")
		key = func
		callback = self.callbacks.get(key, None)
		if callback is None:
			callback = javascript_callback(func, name)
			self.callbacks[key] = callback
		return callback
		
	@property
	def js(self):
		self.alloc()
		return self.accessor
	

class jscore_runtime:
	def __init__(self, vm = None, shared_context = None):
		self.vm = vm
		self.vm_owner = self.vm is None
		if self.vm_owner and shared_context is not None:
			raise Exception("A matching vm must be specified with a shared context. Contexts must not be shared from another virtual machine.")
		self.shared_context = shared_context # never owner when shared_context is not None
		self.depth = 0
		self.module_paths = {}
		self.scripts = []
		
	def allocate(self):
		if self.vm is not None:
			raise Exception("VM already allocated. Do not call allocate/deallocate manually")
		self.vm = jscore.vm_allocate()
		self.vm_owner = True
	
	def deallocate(self):
		if self.vm is None:
			raise Exception("VM already deallocated. Do not call allocate/deallocate manually")
		jscore.runtime_deallocate(self, self.vm_owner)
		self.vm = None
		self.scripts = []
		self.module_paths = {}

	def alloc(self):
		if self.vm is not None:
			return
		self.allocate()

	def destroy(self):
		if self.vm is None:
			return
		self.deallocate()

	def get_module_path(self, source = None, modulePath = None):
		if source is not None:
			path = self.module_paths.get(source)
			if path is not None:
				return path
		if modulePath is not None:
			modulePath = self.get_file_path(modulePath)
			path = str(modulePath)
		if path is None:
			path = tempfile.mktemp(dir = Path.cwd())
		self.module_paths[source] = path
		return path
		
	def get_file_path(self, path):
		path = str(path)
		if path.startswith("file://"):
			path = path[7:]
		p = Path(path)
		if not p.is_absolute():
			p = Path.cwd().joinpath(p)
		return p
		
	def get_source_url(self, source, modulePath):
		path = Path(self.get_module_path(source, modulePath))
		path = str(path.relative_to(Path.cwd()))
		return f"file://./{path}"
	
	def load_source(self, source, scriptType = jscore.kJSScriptTypeProgram, modulePath = None, sourceUrl = None):
		loader = jscore.JSScript.scriptOfType_withSource_andSourceURL_andBytecodeCache_inVirtualMachine_error_
		if sourceUrl is None:
			sourceUrl = self.get_source_url(source, modulePath)
		return self.load_script(loader, source, scriptType, sourceUrl)
	
	def load_file(self, path, scriptType = jscore.kJSScriptTypeProgram, sourceUrl = None):
		p = self.get_file_path(path)
		if not p.is_file() or not p.exists():
			raise FileNotFoundError(f"Script file not found '{path}' ({p})")
		path = str(p)
		path = nsurl(path)
		if sourceUrl is None:
			sourceUrl = self.get_source_url(None, p)
		loader = jscore.JSScript.scriptOfType_memoryMappedFromASCIIFile_withSourceURL_andBytecodeCache_inVirtualMachine_error_
		return self.load_script(loader, path, scriptType, sourceUrl)
		
	def load_script_ref(self, path = None, source = None, url = None):
		url = self.get_file_path(url)
		if source is None and path is not None:
			path = self.get_file_path(path)
			with open(path) as source_file:
				source = source_file.read()
		if source is None:
			raise ValueError("Source or source file path must be specified")
		url = self.get_module_path(source, url)
		url = f"file://{url}"
		script = jsscript_ref(self, url, source)
		self.scripts.append(script)
		return script

	def load_script(self, loader, context, scriptType = jscore.kJSScriptTypeProgram, sourceUrl = None):
		if sourceUrl is None:
			raise ValueError("A valid source url is required")
		sourceUrl = nsurl(sourceUrl)
		error = c_void_p(None)
		#bytecodeCache requires a data vault if specified, so we don't...
		script = loader(scriptType, context, sourceUrl, None, self.vm, byref(error))
		retain_global(script) # DO NOT release JSScripts this will cause a crash while vm is alive
		if error:
			error = ObjCInstance(error)
		else:
			error = None
		sourceUrl = str(sourceUrl)
		self.scripts.append(script)
		return script, sourceUrl, error

	def __enter__(self):
		if self.depth == 0:
			self.alloc()
		self.depth = self.depth + 1
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		self.depth = self.depth - 1
		if self.depth < 0:
			raise Exception("Exit must not be called before enter, use the with keyword.")
		if self.depth == 0:
			self.destroy()
		return self
		
	def __invert__(self):
		return self.vm

	def new_context(self, context):
		raise NotImplementedError() 

	def context(self, context = None):
		self.alloc()
		if context is None:
			context = self.shared_context
		return self.new_context(context)

# helper class to determine the minimum set of changes to build a jsvalue in terms of javascript statements
class jsvalue_evaluator:
	def __init__(self, context, parent = None):
		self.context = context
		self.parent = parent
	
	def object_equal(self, x, y):
		if isinstance(x, dict):
			for k,v in x.items():
				try:
					if not self.item_equal(v, y[k]):
						return False
				except:
					return False
			return True
		elif isinstance(x, list):
			for i in range(len(x)):
				v = x[i]
				try:
					if not self.item_equal(v, y[i]):
						return False
				except:
					return False
			return True
		return False
	
	def value_equal(self, x, y):
		if x is y or x == y:
			return True
		return str(x) == str(y) # repr compare
		
	def item_equal(self, x, y):
		if isinstance(x, list) or isinstance(x, dict):
			return self.object_equal(x, y)
		return self.value_equal(x, y)
	
	def eval_set(self, context, parent, key, value, current, equal = None):
		if isinstance(value, list):
			if (equal is None and self.object_equal(value, current)) or equal:
				return
			if javascript_value.is_null_or_undefined(current) or len(current) == 0:
				value = javascript_callback.wrap(self.context, value, key)
				jsvalue = jscore.py_to_jsvalue(context, value, parent)
				parent.setValue_forProperty_(jsvalue, key)
				return jsvalue
			jsvalue = parent.valueForProperty_(key)
			for i in range(len(value)):
				k = str(i)
				v = value[i]
				c = javascript_value.undefined
				try:
					c = current[i]
				except:
					pass
				if not self.item_equal(v, c):
					self.eval_set(context, jsvalue, k, v, c, False)
			return jsvalue
		elif isinstance(value, dict):
			if (equal is None and self.object_equal(value, current)) or equal:
				return
			if javascript_value.is_null_or_undefined(current) or len(current) == 0:
				value = javascript_callback.wrap(self.context, value, key)
				jsvalue = jscore.py_to_jsvalue(context, value, parent)
				return jsvalue
			jsvalue = parent.valueForProperty_(key)
			for k,v in value.items():
				c = javascript_value.undefined
				try:
					c = current[k]
				except:
					pass
				if not self.item_equal(v, c):
					self.eval_set(context, jsvalue, k, v, c, False)
			return jsvalue
		else:
			if (equal is None and self.value_equal(value, current)) or equal:
				return
			value = javascript_callback.wrap(self.context, value, key)
			jsvalue = jscore.py_to_jsvalue(context, value, parent)
			parent.setValue_forProperty_(jsvalue, key)
			return jsvalue

	def set(self, key, value, current):
		value = jsobject_accessor.unwrap(value)
		current = jsobject_accessor.unwrap(current)
		jsvalue = self.parent
		context = self.context.context
		if jsvalue is None:
			jsvalue = context.globalObject()
		val = self.eval_set(context, jsvalue, key, value, current)
		if val is not None:
			jsvalue.setValue_forProperty_(val, key)
		
	def set_self(self, value, current):
		value = jsobject_accessor.unwrap(value)
		current = jsobject_accessor.unwrap(current)
		jsvalue = self.parent
		context = self.context.context
		if isinstance(value, list):
			for i in range(len(value)):
				k = str(i)
				v = value[i]
				c = javascript_value.undefined
				try:
					c = current[i]
				except:
					pass
				self.eval_set(context, jsvalue, k, v, c)
		elif isinstance(value, dict):
			for k,v in value.items():
				c = javascript_value.undefined
				try:
					c = current[k]
				except:
					pass
				self.eval_set(context, jsvalue, k, v, c)


# metaclass to map jsobjects to appear analogous to regular python objects
class jsobject_accessor:
	def __init__(self, context, jsobject, path):
		self.___context___ = context
		self.___jsobject___ = jsobject
		self.___evaluator___ = jsvalue_evaluator(context, jsobject)
		self.___path___ = path
		self.___init___ = True
		
	def ___get___(self, key):
		key = str(key)
		if not self.___jsobject___.hasProperty_(key):
			return javascript_value.undefined
		value = self.___jsobject___.valueForProperty(key)
		if jscore.jsvalue_is_object(value):
			path = key
			if self.___jsobject___.isArray():
				path = "".join([self.___path___,'[', path,']'])
			else:
				path = ".".join([self.___path___, path])
			return jsobject_accessor(self.___context___, value, path)
		return jscore.jsvalue_to_py(value, self.___jsobject___)
		
	def ___set___(self, key, value):
		current = self.___get___(key)
		path = key
		if self.___jsobject___.isArray():
			path = "".join([self.___path___,'[', path,']'])
		else:
			path = ".".join([self.___path___, path])
		self.___evaluator___.set(key, value, current)

	def __len__(self):
		return len(jscore.jsobject_get_keys(self.___jsobject___))

	def __repr__(self):
		return str(jscore.jsvalue_to_py(self.___jsobject___))
	
	def __getattr__(self, key):
		return self.___get___(key)
	
	def __setattr__(self, key, value):
		if not self.__dict__.get("___init___", False):
			super().__setattr__(key, value)
		else:
			self.___set___(key, value)
			
	def __contains__(self, key):
		value = self.___get___(key)
		return not javascript_value.is_undefined(value)

	def __getitem__(self, key):
		value = self.___get___(key)
		if javascript_value.is_undefined(value):
			raise IndexError(f'{key} is undefined.')
		return value

	def __setitem__(self, key, value):
		self.___set___(k, value)

	def __invert__(self):
		return self.___jsobject___

	@classmethod
	def unwrap(cls, value):
		if isinstance(value, cls):
			return jscore.jsvalue_to_py(~value)
		return value


# metaclass to map the main global context to appear analogous to a regular python object
class javascript_context_accessor:
	def __init__(self, context):
		self.___context___ = context
		self.___globalObject___ = context.context.globalObject()
		self.___evaluator___ = jsvalue_evaluator(context, self.___globalObject___)
		self.___init___ = True
		
	def ___get___(self, key):
		value = javascript_value.undefined
		if not isinstance(key, str):
			return value
		if self.___globalObject___.hasProperty_(key):
			value = self.___globalObject___.valueForProperty(key)
		else:
			result = self.___context___.eval(f'{key};')
			value = result.jsvalue
		if jscore.jsvalue_is_object(value):
			return jsobject_accessor(self.___context___, value, key)
		return jscore.jsvalue_to_py(value)
		
	def ___set___(self, key, value):
		jsvalue = None
		if not self.___globalObject___.hasProperty_(key):
			result = self.___context___.eval(f'{key};')
			jsvalue = result.jsvalue
			if jscore.jsvalue_is_object(jsvalue) and (isinstance(value, list) or isinstance(value, dict)):
				evaluator = jsvalue_evaluator(self.___context___, jsvalue)
				current = jscore.jsvalue_to_py(jsvalue)
				evaluator.set_self(value, current)
				return
		else:
			jsvalue = self.___globalObject___.valueForProperty(key)
		current = javascript_value.undefined
		if jsvalue is not None:
			current = jscore.jsvalue_to_py(jsvalue)
		self.___evaluator___.set(key, value, current)
		

	def __getattr__(self, key):
		return self.___get___(key)

	def __setattr__(self, key, value):
		if not self.__dict__.get("___init___", False):
			super().__setattr__(key, value)
		else:
			self.___set___(key, value)
	
	def __contains__(self, key):
		value = self.___get___(key)
		return not javascript_value.is_undefined(value)
	
	def __getitem__(self, key):
		value = self.___get___(key)
		if javascript_value.is_undefined(value):
			raise IndexError(f"'{key}' is undefined.")
		return value
		
	def __setitem__(self, key, value):
		return self.___set___(key, value)
		
	def __invert__(self):
		return self.___globalObject___
# concrete runtimes and contexts

# javascript
class javascript_context(jscore_context):
	def __init__(self, runtime, context = None):
		super().__init__(runtime, context)

	def allocate(self):
		super().allocate()

	def deallocate(self):
		super().deallocate()


class javascript_runtime(jscore_runtime):
	def new_context(self, context):
		return javascript_context(self, context)

# wasm (WebAssembly)
class wasm_namespace:
	def __init__(self, imports = None):
		if imports is None:
			imports = {}
		self.___imports___ = imports
		self.___init___ = True
		
	def ___get___(self, key):
		value = self.___imports___.get(key, javascript_value.undefined)
		if javascript_value.is_undefined(value):
			value = {}
			self.___set___(key, value)
		if isinstance(value, dict):
			return wasm_namespace(value)
		return value
		
	def ___set___(self, key, value):
		self.___imports___[key] = value

	def __getattr__(self, key):
		return self.___get___(key)

	def __setattr__(self, key, value):
		if not self.__dict__.get("___init___", False):
			super().__setattr__(key, value)
		else:
			self.___set___(key, value)
	
	def __contains__(self, key):
		value = self.___get___(key)
		return not javascript_value.is_undefined(value)
	
	def __getitem__(self, key):
		value = self.___get___(key)
		if javascript_value.is_undefined(value):
			raise IndexError(f"'{key}' is undefined.")
		return value
		
	def __setitem__(self, key, value):
		return self.___set___(key, value)

	def __repr__(self):
		return str(self.___imports___)
	
class wasm_module:
	magic = b'\0asm'
	version = b'\1\0\0\0'
	header = magic + version
	
	@classmethod
	def has_header(cls, data):
		header = cls.header
		header_len = len(header)
		index = 0
		for byte in data:
			if byte != header[index]:
				return False
			index = index + 1
			if index == header_len:
				return True
		return False
	
	def __init__(self, data = None, name = None, imports = {}):
		self.name = name
		if self.name is not None:
			self.name = wasm_module.get_module_name(self.name)
		self.data = None
		self.nsdata = None
		self.context = None
		self.jsdata = None
		self._imports = imports
		self._namespace = wasm_namespace(self._imports)
		self.module = None
		self.instance = None
		if objc.ns_subclass_of(data, NSData):
			self.nsdata = data
		elif isinstance(data, list) or isinstance(data, bytes):
			self.data = []
			data = bytes(data)
			if not wasm_module.has_header(data):
				raise ArgumentError(f"Invalid wasm module. Modules must start with '{wasm_module.header}'.")
			self.data.append(data)
		elif isinstance(data, str) or isinstance(data, Path):
			self.nsdata = objc.nsdata_from_file(data)
		elif data is not None:
			raise ArgumentError("Unknown module data type "+type(data))
		else:
			self.data = []

	def append(self, data):
		if self.data is None or self.nsdata is not None:
			raise Exception("NSData is read only")
		self.data.append(b''.join(data))

	@property
	def bytes(self):
		if self.data is not None:
			bytes = b''.join(self.data)
			if not wasm_module.has_header(bytes):
				return wasm_module.header + bytes
			return bytes
		if self.nsdata is not None:
			return nsdata_to_bytes(self.nsdata)
		return b''
		
	def load(self, context):
		if self.module is not None:
			return self.instance
		if self.nsdata is None and self.data is not None:
			self.nsdata = ns(self.bytes)
			self.data = None
		if self.nsdata is None:
			raise ImportError("Assembly data not loaded.")
		self.context = context
		bytes_len = self.nsdata.length()
		# Work around for MakeTypedArray returning NaN floats when wrapped in a JSValue
		self.jsdata = self.context.eval(f"new Uint8Array({bytes_len});").jsvalue 
		context_ref, value_ref = jscore.jsvalue_get_refs(self.jsdata)
		ex = c_void_p(None)
		bytes_ptr = jscore.JSObjectGetTypedArrayBytesPtr(context_ref, value_ref, byref(ex))
		if bytes_ptr is None and ex.value is not None:
			raise ImportError(jscore.jsvalueref_to_py(context_ref, ex))
		# read nsdata directly into Uint8Array backing bytes
		self.nsdata.getBytes_length_(bytes_ptr, bytes_len)
		self.module, self.name = self.context._load_module_array(self.jsdata, self.name, self._imports)
		self.instance = self.module.instance
		return self.instance
		
	@property
	def loaded(self):
		return self.instance is not None
		
	@property
	def imports(self):
		return self._namespace
		
	@property
	def exports(self):
		if not self.loaded:
			return {}
		return self.instance.exports

	def free(self):
		self.data = None
		self.nsdata = None
		self.context = None
		self.jsdata = None
		self.module = None
		self.instance = None
	
	def save(self, path):
		path = Path(str(path))
		if not path.is_absolute():
			path = path.cwd().joinpath(path)
		with open(path, "w") as module_file:
			module_file.write(self.bytes)
	
	@classmethod
	def get_module_name(cls, path):
		path = str(path)
		if '/' not in path and '.' not in path:
			return path
		name = Path(str(path)).name.split('.wasm')[0]
		if '.' in name:
			name = name.split('.')[0]
		return name
	
	@classmethod
	def from_file_py(cls, path):
		path = Path(str(path))
		if not path.is_absolute():
			path = path.cwd().joinpath(path)
		with open(path) as module_file:
			data = module_file.read()
			name = cls.get_module_name(path)
			return cls(data, name)
			
	@classmethod
	def from_file(cls, path, fileManager = None):
		data = objc.nsdata_from_file(path, fileManager)
		name = cls.get_module_name(path)
		return cls(data, name)


class wasm_context(jscore_context):
	def __init__(self, runtime, context = None):
		super().__init__(runtime, context)
		self._modules = {}
		self._imports = {}
		self._namespace = wasm_namespace(self._imports)
		
	def allocate(self):
		super().allocate()
		self._load_module = self.eval("""
		const _jscore_wasm_modules = {}
		function _jscore_wasm_load(name, wasm_bin, namespace){
				if(namespace === null) { namespace = {}; }
				const wasm_module = new WebAssembly.Module(wasm_bin);
				const wasm_instance = new WebAssembly.Instance(wasm_module, namespace);
				const wasm_module_instance = {"instance": wasm_instance, "namespace": namespace, "module": wasm_module};
				_jscore_wasm_modules[name] = wasm_module_instance; // ensure module remains in scope
				return wasm_module_instance;
		};_jscore_wasm_load;""").value
		
	def deallocate(self):
		for name,module in self._modules.items():
			module.free()
		self._modules = None
		super().deallocate()
	
	@property
	def imports(self):
		return self._namespace
	
	@property
	def modules(self):
		return dict(self._modules)
	
	def module(self, name):
		name = wasm_module.get_module_name(name)
		return self._modules.get(name)
		
	def module_instance(self, name):
		module = self.module(name)
		if module is None:
			return None
		return module.instance
		
	def load_module(self, module):
		if isinstance(module, Path):
			module = wasm_module.from_file(module)
		if not isinstance(module, wasm_module):
			raise ArgumentError("Module must be wasm_module")
		result = self._modules.get(module.name)
		if result is not None:
			return result
		result = module.load(self)
		self._modules[module.name] = module
		return result
	
	def _create_imports_namespace(self, imports = None):
		namespace = {}
		for k, v in self._imports.items():
			namespace[k] = v
		if imports is None:
			imports = {}
		for k, v in imports.items():
			namespace[k] = v
		if len(namespace) == 0:
			return None
		namespace = javascript_callback.wrap(self, namespace)
		jsnamespace = jscore.py_to_jsvalue(self.context, namespace)
		return jsnamespace
		
	def _add_module_to_global_namespace(self, module, name): #?
		pass
	
	def _load_module_array(self, module_data, name = None, imports = None):
		if not jscore.jsvalue_is_array_type(module_data, jscore.kJSTypedArrayTypeUint8Array):
			raise ArgumentError("Module array must be JSValue of an Uint8Array instance type.")
		if name is None:
			name = "wasm_module_"+str(len(self._modules))
		namespace = self._create_imports_namespace(imports)
		result = self._load_module(name, module_data, namespace)
		self._add_module_to_global_namespace(result, name)
		return result, name


class wasm_runtime(jscore_runtime):
	def new_context(self, context):
		return wasm_context(self, context)


if __name__ == '__main__':
	import console
	
	console.clear()
	
	runtime = jscore.runtime()
	context = runtime.context()
	expected_unset = object()

	valueMatch = None
	arrayMatch = None
	objectMatch = None

	def valueMatch(expected, value, values = {}, repr = False):
		if expected is None:
			return value is None
		if expected is javascript_value.undefined:
			return value is javascript_value.undefined
		if isinstance(expected, dict):
			if not isinstance(value, dict):
				return False
			return objectMatch(expected, value)
		elif isinstance(expected, list):
			if not isinstance(value, list):
				return False
			return arrayMatch(expected, value)
		elif expected is not value and expected != value:
			if repr and not isinstance(value,str):
				return expected == str(value)
			if callable(expected):
				expected = expected()
				values["expected"] = expected
				return valueMatch(expected, value, repr, values)
			if callable(value):
				value = value()
				values["value"] = value
				return valueMatch(expected, value, repr, values)
			return False
		return True

	def arrayMatch(expected, value):
		if expected is None:
			return value is None
		if expected is javascript_value.undefined:
			return value is javascript_value.undefined
		if not isinstance(expected, list) or not isinstance(value, list):
			return False
		if len(expected) != len(value):
			return False
		for i in range(len(value)):
			e = expected[i]
			v = value[i]
			if not valueMatch(expected[i], value[i]):
				return False
		return True

	def objectMatch(expected, value):
		if expected is None:
			return value is None
		if expected is javascript_value.undefined:
			return value is javascript_value.undefined
		if not isinstance(expected, dict) or not isinstance(value, dict):
			return False
		for k, v in expected.items():
			if not k in value:
				return False
			vv = value[k]
			if not valueMatch(v, vv):
				return False
		return True

	def eval(script, expected=expected_unset, **kwargs):
		print(f'Execute:\n{script}\n')
		result = context.eval(script)
		value = result.value
		ex = result.exception
		print(f'Result:\n{value}\n')
		if not ex is None:
			print(f'Exception:\n{ex}')
		if expected is not expected_unset:
			values = {"expected":expected, "value":value}
			match = valueMatch(expected, value, values=values, **kwargs)
			expected = values["expected"]
			value = values["value"]
			print(f"Expected: {expected}\nActual: {value}\nPassed: {match}")
		print("-" * 35)
		return value
		
	def header(text, end_only = False):
		if not end_only:
			print("")
			print("-" * 35)
		print(text)
		print("-" * 35)
		print("")

	header("javascript runtime")
	print(runtime, context)
	header("primitives", True)
	eval("parseInt('1')", 1)
	
	eval("1+1", 2)
	
	eval("parseFloat('1.20')", 1.2)
	
	eval("1.1 + 1.1", 2.2)
	
	eval("1.02", 1.02)
	
	eval("false", False)
	
	eval("true", True)
	
	eval("'c'", 'c')

	header("strings")

	eval('"string"', "string")
	
	header("datetimes")
	
	eval("new Date()")
	
	header("exceptions")
	eval('throw "errooorrr";')
	
	header("arrays")
	eval("[]", [])
	
	eval("[ 1, 2 , 3 ]", [ 1, 2, 3 ])
	
	eval("[ true, false, true, false ]", [ True, False, True, False ])
	
	eval("[ 'a', 'b', 'c' ]", [ 'a', 'b', 'c' ])
	
	eval('[ "abc" , "def", "ghi" ]', [ "abc" , "def", "ghi" ])
	
	eval('[ [1,"2"], ["a"], [{"1":2, "obj":{}, "arr":[]}]]', [ [1,"2"], ["a"], [ {"1":2, "obj":{}, "arr":[] }]])
	
	header("objects")
	eval('const obj = { "str": "str", "int": 1, "float": 1.4, "obj":{ "hello": "world"} }; obj;', {"str":"str", "int":1, "float": 1.4, "obj": {"hello": "world"}})

	eval('const fn = function() { return 10; }; fn;', 10)
	
	eval('const fnobj = { "fn": function() { return 10; }}; fnobj;', {"fn": 10})

	header("wasm")
	#instantiate empty module
	eval('''(function(){
	const bin = new Uint8Array([0,97,115,109,1,0,0,0]);
	let result = null;
	try
	{
			const module = new WebAssembly.Module(bin);
			const instance = new WebAssembly.Instance(module);
			result = ''+module+' '+instance;
	}
	catch(ex)
	{
		result = ''+ex;
	}
	return result;
	})();
	//
	''')
	# A memset test as described:
	# https://developer.apple.com/forums/thread/121040
	inst = eval('''(function(){
	const bin = new Uint8Array([0,97,115,109,1,0,0,0,1,6,1,96,1,127,1,127,3,2,1,0,5,3,1,0,1,7,8,1,4,116,101,115,116,0,0,10,16,1,14,0,32,0,65,1,54,2,0,32,0,40,2,0,11]);
	let result = null;
	try
	{
			const module = new WebAssembly.Module(bin);
			const instance = new WebAssembly.Instance(module);
			result = ''+module+' '+instance;
			result += '\\n'+instance.exports.test(4);
			return instance;
	}
	catch(ex)
	{
		result = ''+ex;
	}
	return result;
	})();
	//
	''')
	
	print(inst.exports.test.is_native)
	
	header("context.js interop")
	header("Create new object", True)
	print("context.js.interop_obj = { 'test':{'object':[]}, 'int':1, 'double':2.45 }")
	context.js.interop_obj = { 'test':{'object':[]}, 'int':1, 'double':2.45 }
	print("Result:", context.js.interop_obj)
	
	header("Modify object")
	print("context.js.interop_obj = { 'test':{'object':[1,2,3]}, 'int':1, 'double':2.45 }")
	context.js.interop_obj = { 'test':{'object':[1,2,3]}, 'int':1, 'double':2.45 }
	print("Result:", context.js.interop_obj)
	
	header("Create new function")
	print('"interopfn" in context.js = ', "interopfn" in context.js)
	print('context.js.interopfn = javascript_function.from_body("function() { return 20; }")')
	context.js.interopfn = javascript_function.from_source("function() { return 20; }")
	print('"interopfn" in context.js = ', "interopfn" in context.js)
	print("Result:",context.js.interopfn, context.js.interopfn())
	
	header("Define/Load function")
	print('"fndeftest" in context.js = ', "fndeftest" in context.js)
	print('context.eval("function fndeftest() { return 123; }")')
	context.eval("function fndeftest() { return 123; }")
	print('"fndeftest" in context.js = ', "fndeftest" in context.js)
	print("Result:", context.js.fndeftest, context.js.fndeftest())
	
	header("Define python functions callable from js")
	context.js.pythonfn = lambda text: print(text)
	print("context.js.pythonfn = lambda text: print(text)")
	print(context.js.pythonfn)
	print("context.eval('pythonfn(\"Hello python\");')")
	context.eval('pythonfn("Hello python");')
	print()
	context.js.python_val = lambda: {"str": "Hello from python", "num":10, "list":[1,2,3]}
	print('context.js.python_val = lambda: {"str": "Hello from python", "num":10, "list":[1,2,3]}')
	print(context.js.python_val)
	print("context.eval('python_val();')")
	print(context.eval('python_val();'))
	
	header("Python objects")
	class MyObject:
		def __init__(self):
			self.hello = "world"
	
	context.js.my_object = MyObject()
	print(context.js.my_object)
	
	header("Promise")
	p = context.eval("""new Promise((resolve,reject) => { 
		resolve("promise then");
	});
	""")
	val = p.value.then(lambda v: print(v))
	
	header("Modules/scripts")
	if Path("./test.js").exists():
		context.js.print = lambda *v: print(*v)
		context.eval("""
		import('file://./test.js').then((x) => {
			print('mod then');
			print(x.filetest);
			return x;
			}).catch((e) => {
				print('mod catch');
				print(e.message);
			});
		""").value.then(lambda *v: print("loaded"))

	script_ref = runtime.load_script_ref(source="function script_ref(){ return 232; }; [1, '2', new Date(), script_ref, {'a':[]}];" , url="reftest.js")
	value, exception = script_ref.eval(context)
	print(value, exception, context.js.script_ref)
	context.destroy()
	runtime.destroy()
	print(jscore._runtimes)
	
	header("wasm runtime")
	runtime = jscore.runtime(wasm_runtime)
	context = runtime.context()
	print(runtime, context)
	
	module = wasm_module([0,97,115,109,1,0,0,0,1,6,1,96,1,127,1,127,3,2,1,0,5,3,1,0,1,7,8,1,4,116,101,115,116,0,0,10,16,1,14,0,32,0,65,1,54,2,0,32,0,40,2,0,11])
	context.load_module(module)
	print(module.exports)

	#https://developer.mozilla.org/en-US/docs/WebAssembly/Guides/Using_the_JavaScript_API
	simple_module_path = Path("./simple.wasm")
	if simple_module_path.exists():
		header("simple.wasm")
		simple_module = wasm_module.from_file("./simple.wasm")
		simple_module.imports.my_namespace.imported_func = lambda *v: print(*v)
		context.load_module(simple_module)
		print(simple_module.exports)
		simple_module.exports.exported_func()

	context.destroy()
	runtime.destroy()

	js_context = jscore.js()
	js_context.js.hello = "javascript"
	
	wasm_context = jscore.wasm()
	print(wasm_context.js.hello)
	wasm_context.js.hello = "wasm"
	
	print(js_context.js.hello)
	
	jscore.destroy()

