"""
Pythonista JSCore Runtime Framework - Execute JavaScript and WebAssembly with seamless interop support natively in Pythonista 3.
Develop apps with Python, JavaScript and WebAssembly libraries, components and code. 
[Compile and run WebAssembly from sources with a Binaryen.js toolchain, including Python packages with C extensions.]
"""
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
		return func
	
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
			return cast(c_void_p(0), ptr) # NULL
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
	
	JSGlobalContextCreate = objc.c_func(lib.JSGlobalContextCreate, c_void_p, c_void_p)
	JSGlobalContextCreateInGroup = objc.c_func(lib.JSGlobalContextCreateInGroup, c_void_p, c_void_p, c_void_p)
	JSGlobalContextRetain = objc.c_func(lib.JSGlobalContextRetain, c_void_p, c_void_p)
	JSGlobalContextRelease = objc.c_func(lib.JSGlobalContextRelease, None, c_void_p)
	JSGlobalContextCopyName = objc.c_func(lib.JSGlobalContextCopyName, c_void_p, c_void_p)
	JSGlobalContextSetName = objc.c_func(lib.JSGlobalContextSetName, None, c_void_p, c_void_p)
	JSGlobalContextIsInspectable = objc.c_func(lib.JSGlobalContextIsInspectable, c_bool, c_void_p)
	JSGlobalContextSetInspectable = objc.c_func(lib.JSGlobalContextSetInspectable, None, c_void_p, c_bool)
	
	JSChar_p = POINTER(c_ushort)
	JSStringCreateWithCharacters = objc.c_func(lib.JSStringCreateWithCharacters, c_void_p, JSChar_p, c_size_t)
	JSStringCreateWithUTF8CString = objc.c_func(lib.JSStringCreateWithUTF8CString, c_void_p, c_char_p)
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
	JSValueGetTypedArrayType = objc.c_func(lib.JSValueGetTypedArrayType, c_void_p, c_void_p, c_void_p, c_void_p)
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
	
	JSObjectMakeTypedArray = objc.c_func(lib.JSObjectMakeTypedArray, c_void_p, c_void_p, c_uint, c_size_t, c_void_p)
	JSObjectMakeTypedArrayWithBytesNoCopy = objc.c_func(lib.JSObjectMakeTypedArrayWithBytesNoCopy, c_void_p, c_void_p, c_uint, c_void_p, c_size_t, c_void_p, c_void_p, c_void_p)
	JSObjectMakeTypedArrayWithArrayBuffer = objc.c_func(lib.JSObjectMakeTypedArrayWithArrayBuffer, c_void_p, c_void_p, c_uint, c_void_p, c_void_p)
	JSObjectMakeTypedArrayWithArrayBufferAndOffset = objc.c_func(lib.JSObjectMakeTypedArrayWithArrayBufferAndOffset, c_void_p, c_void_p, c_uint, c_void_p, c_size_t, c_size_t, c_void_p)
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
	
	_runtimes = {}
	@classmethod
	def new_runtime(cls, runtime_class):
		if runtime_class is None:
			raise ValueError("runtime_class must be specified")
		return runtime_class()
	
	# runtime singleton access
	@classmethod
	def runtime(cls, runtime_class = None):
		if runtime_class is None:
			runtime_class = javascript_runtime
		runtime = jscore._runtimes.get(runtime_class)
		if runtime is None:
			runtime = cls.new_runtime(runtime_class)
			jscore._runtimes[runtime_class] = runtime
		return runtime

	@classmethod
	def runtime_destroy(cls, runtime):
		key = runtime.__class__
		rt = jscore._runtimes.get(key)
		if runtime is rt: # remove destroyed runtime if its a tracked singleton instance
			del jscore._runtimes[key]
	
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
		str_bytes = str_py.encode("utf-16")
		str_utf16 = objc.c_array(str_bytes, ptr=cls.JSChar_p)
		str_ref = jscore.JSStringCreateWithCharacters(str_utf16, str_len)
		return jscore.JSStringRetain(str_ref)
	
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
	def jsvalue_jsobject_to_py(cls, value):
		context_ref, value_ref = cls.jsvalue_get_refs(value)
		if jscore.JSObjectIsFunction(context_ref, value_ref):
			return javascript_function(value, context_ref, value_ref)
		keys = cls.jsobjectref_keys(context_ref, value_ref)
		obj = None
		if value.isArray():
			obj = []
			for key in keys:
				jsvalue = value.valueForProperty_(key)
				obj.append(cls.jsvalue_to_py(jsvalue))
		else:
			prototype_ref = cls.JSObjectGetPrototype(context_ref, value_ref)
			obj = cls.jsvalueref_to_py(context_ref, prototype_ref)
			if javascript_value.is_null_or_undefined(obj):
				obj = {}
			for key in keys:
				jsvalue = value.valueForProperty_(key)
				obj[key] = cls.jsvalue_to_py(jsvalue)
		return obj

	@classmethod
	def jsvalue_to_py(cls, value):
		if value is None or value.isNull():
			return None

		if javascript_value.is_undefined(value) or value.isUndefined():
			return javascript_value.undefined
			
		if value.isBoolean():
			return value.toBool()
		
		if value.isNumber() or value.isString() or value.isDate():
			return objc.ns_to_py(value.toObject())
		
		if value.isSymbol():
			return javascript_symbol(value)
		
		return cls.jsvalue_jsobject_to_py(value)

	@classmethod
	def jsvalue_is_object(cls, value):
		if javascript_value.is_undefined(value) or not value.isObject():
			return False
		context_ref, value_ref = cls.jsvalue_get_refs(value)
		if jscore.JSObjectIsFunction(context_ref, value_ref):
			return False
		return True
	
	@classmethod
	def jsobject_get_keys(cls, value):
		if javascript_value.is_undefined(value) or not value.isObject():
			return []
		context_ref, value_ref = cls.jsvalue_get_refs(value)
		if jscore.JSObjectIsFunction(context_ref, value_ref):
			return []
		return cls.jsobjectref_keys(context_ref, value_ref)
	
	@classmethod
	def jsobjectref_to_py(cls, context_ref, value_ref):
		ex = c_void_p(0)
		value_ref = cls.JSValueToObject(context_ref, value_ref, byref(ex))
		if cls.JSObjectIsFunction(context_ref, value_ref):
			str_ref = cls.JSValueToStringCopy(context_ref, value_ref, byref(ex))
			source = None
			if str_ref:
				source = cls.jsstringref_to_py(str_ref)
			return javascript_function(None, context_ref, value_ref, source)
		names_ref = cls.JSObjectCopyPropertyNames(context_ref, value_ref)
		count = cls.JSPropertyNameArrayGetCount(names_ref)
		obj = None
		if cls.JSValueIsArray(context_ref, value_ref):
			obj = []
			for i in range(count):
				key_ref = cls.JSPropertyNameArrayGetNameAtIndex(names_ref, i)
				jsvalue_ref = cls.JSObjectGetProperty(context_ref, value_ref, key_ref, byref(ex))
				obj.append(cls.jsvalueref_to_py(context_ref, jsvalue_ref))
		else:
			prototype_ref = cls.JSObjectGetPrototype(context_ref, value_ref)
			obj = cls.jsvalueref_to_py(context_ref, prototype_ref)
			if javascript_value.is_null_or_undefined(obj):
				obj = {}
			for i in range(count):
				key_ref = cls.JSPropertyNameArrayGetNameAtIndex(names_ref, i)
				jsvalue_ref = cls.JSObjectGetProperty(context_ref, value_ref, key_ref, byref(ex))
				key = cls.jsstringref_to_py(key_ref)
				obj[key] = cls.jsvalueref_to_py(context_ref, jsvalue_ref)
		cls.JSPropertyNameArrayRelease(names_ref)
		return obj
	
	@classmethod
	def jsvalueref_to_py(cls, context_ref, value_ref):
		if value_ref is None:
			return None
		if cls.JSValueIsUndefined(context_ref, value_ref):
			return javascript_value.undefined
		if cls.JSValueIsNull(context_ref, value_ref):
			return None
		if cls.JSValueIsBoolean(context_ref, value_ref):
			return cls.JSValueToBoolean(context_ref, value_ref)
		if cls.JSValueIsNumber(context_ref, value_ref):
			ex = c_void_p(0)
			return cls.JSValueToNumber(context_ref, value_ref, byref(ex))
		if cls.JSValueIsString(context_ref, value_ref):
			ex = c_void_p(0)
			str_ref = cls.JSValueToStringCopy(context_ref, value_ref, byref(ex))
			if str_ref:
				return cls.jsstringref_to_py(str_ref)
			return ""
		if cls.JSValueIsDate(context_ref, value_ref):
			ex = c_void_p(0)
			str_ref = cls.JSValueCreateJSONString(context_ref, value_ref, 0, byref(ex))
			json_date = cls.jsstringref_to_py(str_ref)
			return datetime.strptime(json_date, '"%Y-%m-%dT%H:%M:%S.%fZ"').replace(tzinfo=timezone.utc)
		if cls.JSValueIsSymbol(context_ref, value_ref):
			ex = c_void_p(0)
			str_ref = cls.JSValueToStringCopy(context_ref, value_ref, byref(ex))
			symbol = cls.jsstringref_to_py(str_ref)
			return javascript_symbol(symbol)
		if cls.JSValueIsObject(context_ref, value_ref):
			return cls.jsobjectref_to_py(context_ref, value_ref)
		raise NotImplementedError("Unknown value_ref type")

	@classmethod
	def py_to_jsvalueref(cls, context_ref, value):
		if value is None:
			return cls.JSValueMakeNull(context_ref)
		if javascript_value.is_undefined(value):
			return cls.JSValueMakeUndefined(context_ref)
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
		if isinstance(value, bytes) or isinstance(value, list):
			count = len(value)
			items = objc.c_array(count, lambda i: cls.py_to_jsvalueref(context_ref, value[i]))
			ex_ref = c_void_p(0)
			return cls.JSObjectMakeArray(context_ref, count, items, byref(ex_ref))
		if isinstance(value, dict):
			json_value = cls.py_to_js(value)
			str_ref = cls.str_to_jsstringref(json_value)
			return cls.JSValueMakeFromJSONString(context_ref, str_ref)
		if isinstance(value, javascript_function):
			source = str(value)
			value_ref = javascript_function.from_source(source, context_ref).compile()
			return value_ref
		typ = type(value)
		raise NotImplementedError(f"Type '{typ}' for value '{value}' not supported.")

	@classmethod
	def py_to_js(cls, value):
		value = jsobject_accessor.unwrap(value)
		return json.dumps(value, cls=javascript_encoder)


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
	def __init__(self, jsvalue = None, context_ref = None, value_ref = None, source = None):
		self.jsvalue = jsvalue
		self.context_ref = context_ref
		self.value_ref = value_ref
		self.source = source

	def compile(self):
		if self.context_ref is None:
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
		ex_ref = c_void_p(0)
		self.value_ref = jscore.JSObjectMakeFunction(self.context_ref, name_ref, params_count, params_refs, body_ref, None, 0, by_ref(ex_ref))
		if ex_ref is not None:
			exception = jscore.jsvalueref_to_py(context_ref, ex_ref)
			raise ImportError("Exception compiling function: {exception}")
		return self.value_ref

	def call(self, *args):
		if self.jsvalue is not None:
			nsargs = ns(list(args))
			value = self.jsvalue.callWithArguments_(nsargs)
			return javascript_value(value)
		
		if self.source is not None and self.value_ref is None:
			if self.context_ref is not None:
				self.compile()
			else:
				raise NotImplementedError("Cannot call source only functions without a context_ref")
		
		if self.context_ref is not None and self.value_ref is not None:
			count = len(args)
			args_ref = None
			if count > 0:
				args_ref = objc.c_array(count, lambda i: jscore.py_to_jsvalueref(self.context_ref, args[i]))
			this_ref = None
			exception_ref = c_void_p(0)
			value_ref = jscore.JSObjectCallAsFunction(self.context_ref, self.value_ref, this_ref, count, args_ref, byref(exception_ref))
			return javascript_value(None, context_ref, value_ref)

		raise NotImplementedError("Cannot call this type of javascript_function")

	@property
	def is_native(self):
		repr = str(self).strip()
		return re.fullmatch("function[^\{]+\{[^\[]+\[native code\][^\}]+}", repr) is not None
	
	def __call__(self, *args):
		return self.call(*args).value

	def __repr__(self):
		if self.source is not None:
			return self.source
		if self.jsvalue is not None:
			return str(self.jsvalue)
		
	@classmethod
	def from_source(cls, source, context = None):
		context_ref = None
		if isinstance(context, c_void_p):
			context_ref = context
		elif context is not None:
			if isinstance(context, jscore_context):
				context = context.context
			if objc.ns_subclass_of(context, jscore.JSContext):
				context_ref = context.JSGlobalContextRef()
		return cls(source=source, context_ref=context_ref)

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
		self.jsvalue = jsvalue
		self.context_ref = context_ref
		self.value_ref = value_ref
		self._val = None
		self._cached = False

	@property
	def value(self):
		if not self._cached:
			if self.jsvalue is not None:
				self._val = jscore.jsvalue_to_py(self.jsvalue)
			elif self.context_ref is not None and self.value_ref is not None:
				self._val = jscore.jsvalueref_to_py(self.context_ref, self.value_ref)
			else:
				self._val = javascript_value.undefined
			if isinstance(self._val, dict):
				self._val = javascript_object(self._val)
			self._cached = True
		return self._val
		
	def __repr__(self):
		return str(self.value)

# base runtime framework
class jsscript_ref:
	def __init__(self, runtime, url, source):
		self.runtime = runtime
		self.vm = runtime.vm
		self.context_group_ref = self.vm.JSContextGroupRef()
		self.url = url
		self.source = source
		self.url_ref = jscore.str_to_jsstringref(url)
		self.source_ref = jscore.str_to_jsstringref(source)
		error_ref = c_void_p(0)
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
		exception_ref = c_void_p(0)
		value_ref = jscore.JSScriptEvaluate(context_ref, self.script_ref, this_ref, byref(exception_ref))
		value = jscore.jsvalueref_to_py(context_ref, value_ref)
		exception = jscore.jsvalueref_to_py(context_ref, exception_ref)
		return value, exception

class jscore_module_loader:
	def __init__(self, context):
		self.runtime = context.runtime
		self.pycontext = context
		self.context = context.context
		self.scripts = {}
		self.modules = {}
		self.sources = {}
		self.delegate = jscore.JSCoreModuleLoaderDelegate.alloc().init().autorelease()
		retain_global(self.delegate)
		self.delegate._pyinstance = weakref.ref(self)
		self.context.setModuleLoaderDelegate_(self.delegate)
		self.evaluated = {}
		
	def release(self):
		self.context.setModuleLoaderDelegate_(None)
		release_global(self.delegate)
		self.delegate = None
		
	def fetch_module(self, module, resolve, reject):
		evaluated = self.evaluated.get(module)
		if evaluated is not None:
			if evaluated.exception is None:
				resolve(evaluated.jsvalue)
			else:
				reject(evaluated.exception)
			return
		script = self.modules.get(module)
		if script is None:
			script = self.load_file(module, jscore.kJSScriptTypeModule)
		source = self.sources.get(module)
		if script is not None and source is not None:
			result = self.pycontext.eval(source)
			exception = result.exception
			if exception is not None:
				reject(exception)
				print(f"Module load failed {module} {exception}")
			else:
				resolve(result.jsvalue)
				print(f"Module load success {module}")
			self.evaluated[module] = result
		else:
			reject(f"Module load failed {module}")
			print(f"Module load failed {module}")
			
	def will_eval_module(self, url):
		print(f"will eval {url}")
		
	def did_eval_module(self, url):
		print(f"did eval {url}")
		
	def preprocess_source(self, scriptType, path, source):
		return source
		
	def load_script_source(self, script, scriptType, path, sourceUrl, source = None):
		# we have to use lookups until we can decode strings directly from either:
		# WTF::String on script.source()
		# JSC:JSSourceCode* on script.jsSourceCode()
		# JSC::SourceCode on script.sourceCode()
		file_path = self.runtime.get_file_path(path)
		path_no_ext = str(file_path.with_suffix(''))
		if source is None:
			with open(file_path) as script_file:
				source = script_file.read()
		source = self.preprocess_source(scriptType, file_path, source)
		sources = self.sources
		sources[path] = source
		sources[path_no_ext] = source
		sources[f"file://{path_no_ext}"] = source
		sources[sourceUrl] = source

		lookup = self.modules if scriptType == jscore.kJSScriptTypeModule else self.scripts
		lookup[source] = script
		lookup[path] = script
		lookup[path_no_ext] = script
		lookup[f"file://{path_no_ext}"] = script
		lookup[sourceUrl] = script
	
	def load_source(self, source, scriptType, modulePath = None):
		lookup = self.modules if scriptType == jscore.kJSScriptTypeModule else self.scripts
		script = lookup.get(source)
		path = None
		if script is None:
			path = self.runtime.get_module_path(source, modulePath)
			script = lookup.get(f"file://{path}")
		if script is not None:
			return script
		script, sourceUrl, exception = self.runtime.load_source(source, scriptType, path)
		if exception is not None: 
			 raise ImportError(exception)
		self.load_script_source(script, scriptType, path, sourceUrl, source)
		return script
		
	def load_file(self, path, scriptType):
		lookup = self.modules if scriptType == jscore.kJSScriptTypeModule else self.scripts
		script = lookup.get(path)
		if script is None:
			path = self.runtime.get_file_path(path)
			path = str(path)
		script = lookup.get(path)
		if script is not None:
			return script
		script, sourceUrl, exception = self.runtime.load_file(path, scriptType)
		if exception is not None: 
			 raise ImportError(exception)
		self.load_script_source(script, scriptType, path, sourceUrl)
		return script


class jscore_context:
	def __init__(self, runtime):
		self.runtime = runtime
		self.context = None
		self.depth = 0

	def allocate(self):
		if self.context is not None:
			raise Exception("Context already allocated. Do not call allocate/deallocate manually.")
		self.context = jscore.JSContext.alloc().initWithVirtualMachine_(self.runtime.vm)
		retain_global(self.context)
		self.context.setInspectable(True)
		self.loader = jscore_module_loader(self)
		
	def deallocate(self):
		if self.context is None:
			raise Exception("Context already deallocated. Do not call allocate/deallocate manually.")
		self.loader.release()
		self.loader = None
		release_global(self.context)
		self.context = None

	def alloc(self):
		if self.context is not None:
			return
		self.allocate()

	def destroy(self):
		if self.context is None:
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
		
	class eval_result:
		def __init__(self, wrapper, exception):
			self.wrapper = wrapper
			self.jsvalue = wrapper.jsvalue
			self.exception = exception
		
		@property
		def value(self):
			return self.wrapper.value
			
		def __repr__(self):
			return str({"value":self.value, "exception":self.exception})
	
	def eval(self, script, sourceUrl=None):
		self.alloc()
		result = None
		if sourceUrl is None or sourceUrl.strip() == '':
			result = self.context.evaluateScript_(script)
		else:
			result = self.context.evaluateScript_withSourceUrl_(script, sourceUrl)
		result = ObjCInstance(result)
		ex = self.context.exception()
		if ex is not None:
			self.context.setException(None) # clear exception if set
		result = self.eval_result(javascript_value(result), ex)
		return result
	
	def eval_jsscript(self, jsscript):
		if jsscript is None:
			raise ValueError("Null JSScript pointer")
		result = self.context.evaluateJSScript(jsscript) # crashes on null or invalid script ptr
		result = ObjCInstance(result)
		ex = self.context.exception()
		if ex is not None:
			self.context.setException(None) # clear exception if set
		result = self.eval_result(javascript_value(result), ex)
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
	
	def eval_module_source(self, source, modulePath = None):
		return self.eval_script_source(source, jscore.kJSScriptTypeModule, modulePath)

	def eval_module_file(self, path):
		return self.eval_script_file(path, jscore.kJSScriptTypeModule)
	

class jscore_runtime:
	def __init__(self):
		self.vm = None
		self.depth = 0
		self.module_paths = {}
		self.scripts = []
		
	def allocate(self):
		if self.vm is not None:
			raise Exception("VM already allocated. Do not call allocate/deallocate manually")
		self.vm = jscore.JSVirtualMachine.alloc().init()
		retain_global(self.vm)
	
	def deallocate(self):
		if self.vm is None:
			raise Exception("VM already deallocated. Do not call allocate/deallocate manually")
		release_global(self.vm)
		self.vm = None
		released = [] # avoid releasing more than once
		for script in self.scripts:
			if not script in released:
				if isinstance(script, jsscript_ref):
					script.release()
				else:
					release_global(script)
				released.append(script)
		self.scripts = []
		self.module_paths = {}
		jscore.runtime_destroy(self)
	
	def alloc(self):
		if self.vm is not None:
			return
		self.allocate()

	def destroy(self):
		if self.vm is None:
			return
		self.deallocate()
	
	def get_module_path(self, source, modulePath = None):
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
	
	def load_source(self, source, scriptType = jscore.kJSScriptTypeProgram, modulePath = None):
		loader = jscore.JSScript.scriptOfType_withSource_andSourceURL_andBytecodeCache_inVirtualMachine_error_
		sourceUrl = self.get_module_path(source, modulePath)
		return self.load_script(loader, source, scriptType, sourceUrl)
	
	def load_file(self, path, scriptType = jscore.kJSScriptTypeProgram):
		p = self.get_file_path(path)
		sourceUrl = None
		if not p.is_file() or not p.exists():
			raise FileNotFoundError(f"Script file not found '{path}' ({p})")
		path = str(p)
		path = nsurl(path)
		sourceUrl = str(p)
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
		error = c_void_p(0)
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

	def new_context(self):
		raise NotImplementedError() 

	def context(self):
		self.alloc()
		return self.new_context()

# helper class to determine the minimum set of changes to build a jsvalue in terms of javascript statements
class jsvalue_accessor:
	def __init__(self, context, key, current = javascript_value.undefined, define = True):
		self.context = context
		self.key = key
		self.current = jsobject_accessor.unwrap(current)
		self.define = define
	
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
	
	def build(self, key, value, current, equal = None):
		if isinstance(value, list):
			if (equal is None and self.object_equal(value, current)) or equal:
				return None
			if javascript_value.is_null_or_undefined(current) or len(current) == 0:
				value = jscore.py_to_js(value)
				return f'{key} = {value};'
			statements = []
			for i in range(len(value)):
				k = str(i)
				v = value[i]
				c = javascript_value.undefined
				try:
					c = current[i]
				except:
					pass
				if not self.item_equal(v, c):
					k = "".join([key, '[', k, ']'])
					s = self.build(k, v, c, False)
					if s is not None:
						statements.append(s)
			if len(statements) > 0:
				return "\n".join(statements)
			return statement
		elif isinstance(value, dict):
			if (equal is None and self.object_equal(value, current)) or equal:
				return None
			if javascript_value.is_null_or_undefined(current) or len(current) == 0:
				value = jscore.py_to_js(value)
				return f'{key} = {value};'
			statements = []
			for k,v in value.items():
				c = javascript_value.undefined
				try:
					c = current[k]
				except:
					pass
				if not self.item_equal(v, c):
					k = "".join([key, '.', k])
					s = self.build(k, v, c, False)
					if s is not None:
						statements.append(s)
			if len(statements) > 0:
				return "\n".join(statements)
			return statement
		else:
			if (equal is None and self.value_equal(value, current)) or equal:
				return None
			value = jscore.py_to_js(value)
			return f'{key} = {value};'

	def set(self, value):
		value = jsobject_accessor.unwrap(value)
		current = self.current
		key = self.key
		define = self.define
		statement = None
		if define and javascript_value.is_undefined(current):
			key = f'let {key}'
			value = jscore.py_to_js(value)
			statement = f'{key} = {value};'
		else:
			statement = self.build(key, value, current)
		if statement is None:
			return
		#print(statement)
		result = self.context.eval(statement)
		exception = result.exception
		if exception is not None:
			raise ValueError(exception)


# metaclass to map jsobjects to appear analogous to regular python objects
class jsobject_accessor:
	def __init__(self, context, jsobject, key):
		self.___context___ = context
		self.___jsobject___ = jsobject
		self.___key___ = key
		self.___init___ = True
		
	def ___get___(self, key):
		key = str(key)
		if not self.___jsobject___.hasProperty_(key):
			return javascript_value.undefined
		value = self.___jsobject___.valueForProperty(key)
		if jscore.jsvalue_is_object(value):
			if self.___jsobject___.isArray():
				key = "".join([self.___key___,'[', key,']'])
			else:
				key = ".".join([self.___key___, key])
			return jsobject_accessor(self.___context___, value, key)
		return jscore.jsvalue_to_py(value)
		
	def ___set___(self, key, value):
		current = self.___get___(key)
		context = self.___context___
		if self.___jsobject___.isArray():
			key = "".join([self.___key___,'[', key,']'])
		else:
			key = ".".join([self.___key___, key])
		accessor = jsvalue_accessor(context, key, current, define=False)
		accessor.set(value)
			
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
		
	@classmethod
	def unwrap(cls, value):
		if isinstance(value, cls):
			return jscore.jsvalue_to_py(value.___jsobject___)
		return value


# metaclass to map the main global context to appear analogous to a regular python object
class javascript_context_accessor:
	def __init__(self, context):
		self.___context___ = context
		self.___globalObject___ = context.context.globalObject()
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
		current = self.___get___(key)
		context = self.___context___
		accessor = jsvalue_accessor(context, key, current, define=True)
		accessor.set(value)

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

# concrete runtimes and contexts

# javascript
class javascript_context(jscore_context):
	def __init__(self, runtime):
		super().__init__(runtime)
		self.accessor = None

	def allocate(self):
		super().allocate()
		self.accessor = javascript_context_accessor(self)

	def deallocate(self):
		self.accessor = None
		super().deallocate()
	
	@property
	def js(self):
		self.alloc()
		return self.accessor


class javascript_runtime(jscore_runtime):
	def new_context(self):
		return javascript_context(self)

# wasm (WebAssembly)

class wasm_context(jscore_context):
	pass


class wasm_runtime(jscore_runtime):
	def new_context(self):
		return wasm_context(self)


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

	context.eval_module_source("function bob() { return 10; }", "sourcetest.js")
	print(context.js.bob)
	#context.eval_module_file("./test.js")
	#print(context.js.filetest)
	#str_ref = jscore.str_to_jsstringref("test test")
	#print(str_ref)
	#py_str = jscore.jsstringref_to_py(str_ref)
	#print(py_str)
	script_ref = runtime.load_script_ref(source="function bill(){ return 232; }; [1, '2', new Date(), bill, {'a':[]}];" , url="reftest.js")
	value, exception = script_ref.eval(context)
	print(value, exception, context.js.bill)
	context.destroy()
	runtime.destroy()
	print(jscore._runtimes)
	
	header("wasm runtime")
	runtime = jscore.runtime(wasm_runtime)
	context = runtime.context()
	print(runtime, context)
	
	context.destroy()
	runtime.destroy()
	print(jscore._runtimes)
