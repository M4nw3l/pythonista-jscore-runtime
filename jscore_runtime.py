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
from pathlib import Path
import enum, io, json, os, re, secrets, shutil, struct, sys, tempfile, types
import threading
import logging
log = logging.getLogger(__name__)

NSDate = ObjCClass("NSDate")
NSFileManager = ObjCClass("NSFileManager")

#objective c helpers
class objc:
	# load_library from rubicon 
	#https://github.com/beeware/rubicon-objc/blob/1a97f483fdd83f4fc31050ee863535e3ed962944/src/rubicon/objc/runtime.py#L77
	_lib_path = ["/usr/lib"]
	_framework_path = ["/System/Library/Frameworks"]
	@classmethod
	def load_library(cls, name):
		path = find_library(name)
		if path is not None:
			return CDLL(path)

		for loc in cls._lib_path:
			try:
				return CDLL(os.path.join(loc, "lib" + name + ".dylib"))
			except OSError:
				pass

		for loc in cls._framework_path:
			try:
				return CDLL(os.path.join(loc, name + ".framework", name))
			except OSError:
				pass
		raise ImportError(f"Library {name} not found")
	
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
		#property = property.strip()
		#parts = re.match("(\+|\-)\s+(@property)?\s*(\([A-z0-9=,]*\))?\s*([\(\)\*A-z0-9]+)\s+([A-z0-9]+);", property)
		#attribs = []
		#attribs_count = len(attribs)
		#attribs = objc.c_array_p(attribs)
		#objc.objc_protocol_addProperty(protocol, name, attribs, attribs_count, required, instance)
		raise NotImplementedError()

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
			parent = objc.getProtocol(id)
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
			elif ":" not in method or method.startswith("@property"):
				objc.protocol_addProperty(p, method, required, methodTypes)
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
	version = __version__
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
	# a lock to ensure synchronised access to runtimes
	_lock = threading.Lock() 
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
		with cls._lock:
			if runtime_class is None:
				runtime_class = javascript_runtime
			runtime = cls._runtimes.get(runtime_class)
			if runtime is None:
				if cls._runtime_vm is None:
					cls._runtime_vm = cls.vm_allocate()
					cls._runtime_context = cls.context_allocate(cls._runtime_vm)
				runtime = cls.new_runtime(runtime_class, cls._runtime_vm, cls._runtime_context)
				cls._runtimes[runtime_class] = runtime
				cls._runtimes_contexts[runtime_class] = runtime.context()
			return runtime

	@classmethod
	def _runtimes_cleanup(cls):
		with cls._lock:
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
		runtime = cls.runtime(runtime_class)
		return cls._runtimes_contexts.get(runtime_class)

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
		runtimes_count = -1
		key = runtime.__class__
		rt = cls._runtimes.get(key)
		if runtime is rt: # remove destroyed runtime if its a tracked singleton instance
			with cls._lock:
				del cls._runtimes[key]
				del cls._runtimes_contexts[key]
				runtimes_count = len(cls._runtimes) == 0
		if runtimes_count == 0:
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
		def __init__(self, context, context_ref, prototypes):
			self.context = context
			self.context_ref = context_ref
			self.jsvalueref_to_jsvalue_object = jscore.JSValue.valueWithNewObjectInContext_(context)
			self.jsvalueref_to_jsvalue_object_ref = self.jsvalueref_to_jsvalue_object.JSValueRef()
			self.undefined_jsvalue = jscore.JSValue.valueWithUndefinedInContext_(context)
			get_prototypes,ex = jscore.context_eval(self.context, """(function(){
				return function(prototypes) {
					const wrappers = {};
					for(const [name, metadata] of Object.entries(prototypes)) {
						const _ctor = this[name];
						const _prototype = _ctor.prototype;
						const wrapper = {
							"_ctor_": _ctor,
							"_prototype_": _prototype
						};
						for(const field of metadata.layout) {
							try { wrapper[field] = _prototype[field]; } catch { }
							if(wrapper[field] === undefined) {
								wrapper[field] = null; // force a wrapper definition if not defined so we know the key
							}
						}
						wrappers[name] = wrapper;
					}
					return wrappers;
				};
			})();""")
			js_get_prototypes = jscore.jsvalue_to_py(get_prototypes)
			js_prototypes = js_get_prototypes.call(prototypes)
			self.prototypes = {}
			self.classes = {}
			self.ctors = {}
			self.prototypes_metadata = {}
			for key,prototype in js_prototypes.jsobject:
				_ctor = (~prototype._ctor_).JSValueRef()
				_prototype = (~prototype._prototype_).JSValueRef()
				self.ctors[_prototype.value] = _ctor
				self.prototypes[_ctor.value] = prototype
				self.prototypes[_prototype.value] = prototype
				metadata = prototypes[key]
				metadata.ctor = ~prototype._ctor_
				metadata.prototype = ~prototype._prototype_
				metadata.prototype_object = prototype
				self.prototypes_metadata[_prototype.value] = metadata
				self.prototypes_metadata[_ctor.value] = metadata
		
		_context_lookup = None
		_lock = None
		@classmethod
		def init(cls, lookup, lock):
			cls._context_lookup = lookup
			cls._lock = lock
		
		@classmethod
		def get(cls, id):
			if isinstance(id, c_void_p):
				return cls._context_lookup[id.value]
			return cls._context_lookup[id]
	
	_context_metadata.init(_context_lookup, None)
	
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
	def jsstringref_release(cls, str_ref):
		if str_ref is None or not isinstance(str_ref, c_void_p):
			raise ValueError("Invalid str_ref")
		cls.JSStringRelease(str_ref)
		return None

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
	def jsvalueref_get_prototype_from_metadata(cls, context_ref, value_ref, prototype_ref = None):
		if prototype_ref is None:
			prototype_ref = cls.JSObjectGetPrototype(context_ref, value_ref)
		metadata = cls._context_metadata.get(context_ref)
		metadata_prototype = metadata.prototypes.get(prototype_ref)	
		if metadata_prototype is not None:
			return metadata_prototype
		for key,p in dict(metadata.classes).items():
			class_ref = c_void_p(key)
			if jscore.JSValueIsObjectOfClass(context_ref, value_ref, class_ref):
				return p
		return None
	
	@classmethod
	def jsvalueref_get_prototype(cls, context_ref, value_ref):
		prototype_ref = cls.JSObjectGetPrototype(context_ref, value_ref)
		metadata_prototype = cls.jsvalueref_get_prototype_from_metadata(context_ref, value_ref, prototype_ref)
		if metadata_prototype is not None:
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
		keys = set(keys + list(obj.keys()))
		for key in keys:
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

		obj = None
		if cls.JSValueIsArray(context_ref, value_ref):
			names_ref = cls.JSObjectCopyPropertyNames(context_ref, value_ref)
			count = cls.JSPropertyNameArrayGetCount(names_ref)
			obj = []
			for i in range(count):
				key_ref = cls.JSPropertyNameArrayGetNameAtIndex(names_ref, i)
				jsvalue_ref = cls.JSObjectGetProperty(context_ref, value_ref, key_ref, byref(ex))
				obj.append(cls.jsvalueref_to_py(context_ref, jsvalue_ref, value_ref))
			cls.JSPropertyNameArrayRelease(names_ref)
		else:
			prototype_ref = cls.jsvalueref_get_prototype(context_ref, value_ref)
			obj = cls.jsvalueref_to_py(context_ref, prototype_ref, value_ref if parent_ref is None else parent_ref)
			if javascript_value.is_null_or_undefined(obj):
				obj = {}
			keys = cls.jsobjectref_keys(context_ref, value_ref)
			keys = set(keys+list(obj.keys()))
			for key in keys:
				key_ref = cls.str_to_jsstringref(key)
				jsvalue_ref = cls.JSObjectGetProperty(context_ref, value_ref, key_ref, byref(ex))
				key = cls.jsstringref_to_py(key_ref)
				cls.jsstringref_release(key_ref)
				value = cls.jsvalueref_to_py(context_ref, jsvalue_ref, value_ref if parent_ref is None else parent_ref)
				if not javascript_value.is_undefined(value):
					obj[key] = value
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
			ctx_ref, value_ref = cls.jsvalue_get_refs(value)
			#if context_ref != ctx_ref:
			#	raise Exception("Context mismatch")
			return value_ref # return refs from existing JSValues
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
		if isinstance(value, javascript_value_base):
			jsvalue = ~value
			ctx_ref, value_ref = cls.jsvalue_get_refs(jsvalue)
			#if context_ref != ctx_ref:
				#raise Exception("Context mismatch")
			return value_ref
		if isinstance(value, javascript_promise):
			value_ref = value.get_jsvalue_ref(context_ref)
			return value_ref
		if isinstance(value, javascript_function):
			if value.compiled:
				ctx_ref, value_ref = cls.jsvalue_get_refs(~value)
				return value_ref
			if value.is_native:
				raise ValueError("Cannot compile native functions (this shouldn't be reachable!')")
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
			cls.jsstringref_release(key_ref)
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
		if isinstance(value, javascript_value_base):
			jsvalue = ~value
			return jsvalue
		if isinstance(value, javascript_promise):
			jsvalue = value.get_jsvalue(context)
			return jsvalue
		if isinstance(value, javascript_function):
			if value.compiled:
				return ~value
			if value.is_native:
				raise ValueError("Cannot compile native functions (this shouldn't be reachable!')")
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
		cls.prototype_register("AggregateError", ["errors", "name", "message", "toString"])
		#cls.prototype_register("SuppressedError", ["error", "suppressed", "name", "message", "toString"])
		#cls.prototype_register("InternalError", ["name", "message", "toString"])
		cls.prototype_register("Promise", ["then", "catch", "finally"])
		cls.prototype_register("ArrayBuffer", [
			"byteLength", "detached", "maxByteLength", "resizable", "resize", "transfer", "transferToFixedLength"
		])
		cls.prototype_register("DataView", [
			"buffer", "byteLength", "byteOffset", 
			"getBigInt64", "getBigUint64", 
			"setBigInt64", "setBigUint64",
			"getFloat16", "getFloat32", "getFloat64",
			"setFloat16", "setFloat32", "setFloat64",
			"getInt8", "getInt16", "getInt32",
			"setInt8", "setInt16", "setInt32",
			"getUint8", "getUint16", "getUint32",
			"setUint8", "setUint16", "setUint32",
		])
		typedArrayMembers = [
			"buffer", "byteLength", "byteOffset", "length", "BYTES_PER_ELEMENT",
			"at", "copyWithin", "entries", "every", "fill", "filter", "find", "findIndex", 
			"findLast", "findLastIndex", "forEach", "includes", "indexOf", "join",
			"keys", "lastIndexOf", "map", "reduce", "reduceRight", "reverse", "set", "slice", "some", 
			"sort", "subarray", "toLocaleString", "toReversed", "toSorted", "toString", "values", "with"
		]
		typedArrayTypes = [ 
			"Int8Array", "Uint8ClampedArray", "Int16Array", "Uint16Array", "Int32Array", "Uint32Array",
			"Float16Array", "Float32Array", "Float64Array", "BigInt64Array", "BigUint64Array",
		]
		cls.prototype_register("Uint8Array", typedArrayMembers + [ "setFromBase64", "setFromHex", "toBase64", "toHex" ])
		for arrayType in typedArrayTypes:
			cls.prototype_register(arrayType, typedArrayMembers)
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
		
class javascript_value_base:
	def __init__(self, jsvalue = None, context_ref = None, value_ref = None):
		if jsvalue is None and context_ref is None and value_ref is None:
			raise ValueError("Either jsvalue or context_ref and value_ref must be specified")
		if isinstance(jsvalue, javascript_value_base):
			self.___jsvalue___ = ~jsvalue
		elif jsvalue is not None:
			self.___jsvalue___ = jsvalue
		else:
			self.___jsvalue___ = jscore.jsvalueref_to_jsvalue(context_ref, value_ref)
			
	def __repr__(self):
		return str(jscore.jsvalue_to_py(self.___jsvalue___))

	def __invert__(self):
		return self.___jsvalue___
		

class jsvalue_accessor(javascript_value_base):
	def __iter__(self):
		self.___keys___ = jscore.jsobject_get_keys(~self)
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
		jsvalue = ~self
		if not jsvalue.hasProperty_(name):
			return None
		v = jsvalue.valueForProperty_(name)
		if not jscore.jsvalue_is_object(v):
			return javascript_value(v)
		return jsvalue_accessor(v)


class javascript_value(javascript_value_base):
	undefined = javascript_undefined_value()
	
	@classmethod
	def is_undefined(cls, value):
		return value is cls.undefined

	@classmethod
	def is_defined(cls, value):
		return value is not cls.undefined
	
	@classmethod
	def is_null(cls, value):
		return value is None
	
	@classmethod
	def is_null_or_undefined(cls,value):
		return cls.is_null(value) or cls.is_undefined(value)
		
	@classmethod
	def is_not_null(cls, value):
		return not cls.is_null_or_undefined(value)

	def __init__(self, jsvalue = None, context_ref = None, value_ref = None):
		super().__init__(jsvalue, context_ref, value_ref)
		self._jsvalue = self.___jsvalue___
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
			elif isinstance(self._val, list):
				self._val = javascript_list(self._val)
			self._cached = True
		return self._val
		
	def __repr__(self):
		return str(self.value)
		
	def __invert__(self):
		return self.jsvalue

class javascript_list(list):
	def __getitem__(self, index):
		item = super().__getitem__(index)
		if isinstance(item, dict):
			item = javascript_object(item)
		elif isinstance(item, list):
			item = javascript_list(item)
		return item
		
	def __iter__(self):
		self.index = -1
		return self
	
	def __next__(self):
		self.index += 1
		if self.index < len(self):
			return self[self.index]
		raise StopIteration

class javascript_object(dict):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.___init___ = True
		
	def __getattr__(self, key):
		value = self.get(key, javascript_value.undefined)
		if isinstance(value, dict):
			value = javascript_object(value)
		elif isinstance(value, list):
			value = javascript_list(value)
		return value
		
	def __setattr__(self, key, value):
		if not self.__dict__.get("___init___", False):
			super().__setattr__(key, value)
		else:
			self[key] = value

class javascript_error(javascript_value):
	def __repr__(self):
		#return str(self.value)
		if isinstance(self.value, str):
			return self.value
		return self.value.toString()

# not sure what this is...
class javascript_symbol:
	def __init__(self, symbol):
		self.symbol = symbol
		#print(f"javascript_symbol {symbol}")

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
		params_count = 0
		params_refs = []
		for p in params:
			param = p.strip()
			if param != "":
				param_ref = jscore.str_to_jsstringref(param)
				params_refs.append(param_ref)
				params_count += 1
		params_refs = objc.c_array_p(params_refs)
		name_ref = jscore.str_to_jsstringref(fn_name)
		body = self.source
		body = body[body.index('{'):body.rindex('}')]
		body_ref = jscore.str_to_jsstringref(body)
		ex_ref = c_void_p(None)
		self.value_ref = jscore.JSObjectMakeFunction(context_ref, name_ref, params_count, params_refs, body_ref, None, 0, byref(ex_ref))
		jscore.jsstringref_release(name_ref)
		jscore.jsstringref_release(body_ref)
		for param_ref in params_refs:
			jscore.jsstringref_release(param_ref)
		self.context_ref = context_ref
		if ex_ref.value is not None:
			exception = jscore.jsvalueref_to_py(context_ref, ex_ref)
			raise ImportError(f"Exception compiling function: {exception}")
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
				args_ref = objc.c_array_p(count, lambda i: jscore.py_to_jsvalueref(self.context_ref, args[i]))
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
	def name(self):
		src = str(self)
		m = re.match("function([^\(]*)\(", repr)
		return m.group().strip()
		
	@property
	def is_native(self):
		repr = str(self).strip()
		return re.fullmatch("function[^\{]+\{[^\[]+\[native code\][^\}]+}", repr) is not None
		
	@property
	def compiled(self):
		return self.jsvalue is not None or self.value_ref is not None
	
	def __call__(self, *args, **kwargs):
		return self.call(*args, **kwargs).value

	def __repr__(self):
		if self.source is not None:
			return self.source
		try:
			jsvalue = ~self
			return str(self.jsvalue)
		except Exception:
			pass
		return "function() {}"
			
	def __invert__(self):
		if self.jsvalue is not None:
			return self.jsvalue
		elif self.context_ref and self.value_ref is not None:
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
		jscore.jsstringref_release(name_ref)
	
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
		try:
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
		except Exception as e:
			log.exception(f"javascript_callback exception '{self.name}' '{self.callback}' {e}")
			# set an error / exception back in context ?
		
	def __invert__(self):
		if self._jsvalue is not None:
			return self._jsvalue
		elif self.context_ref and self.value_ref is not None:
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

class javascript_promise:
	def __init__(self, value = None, context_ref = None):
		self.jsvalue = None
		self._promise = None
		self.context_ref = None
		self.value_ref = None
		self.resolve_ref = None
		self.reject_ref = None
		self.jsresolve = None
		self.jsreject = None
		self._resolve = None
		self._reject = None
		self._callback = None
		if callable(value):
			self._callback = value
		elif objc.ns_subclass_of(value, jscore.JSValue):
			self.jsvalue = value
		if self.jsvalue is not None:
			self.context_ref, self.value_ref = jscore.jsvalue_get_refs(self.jsvalue)
			self._promise = jscore.jsvalue_to_py(self.jsvalue)
		elif context_ref is not None:
			if objc.ns_subclass_of(context_ref, jscore.JSContext):
				self.context_ref = context_ref.JSGlobalContextRef()
			else:
				self.context_ref = context_ref

	def compile(self, context_ref = None):
		if objc.ns_subclass_of(context_ref, jscore.JSContext):
			context_ref = context_ref.JSGlobalContextRef()
		if context_ref is None:
			context_ref = self.context_ref
		if context_ref is None:
			raise Exception("Context ref is required to compile promise")
		if self.value_ref is not None:
			raise Exception("Promise already compiled")
		resolve_ref = c_void_p(None)
		reject_ref = c_void_p(None)
		ex_ref = c_void_p(None)
		value_ref = jscore.JSObjectMakeDeferredPromise(context_ref, byref(resolve_ref), byref(reject_ref), byref(ex_ref))
		self.context_ref = context_ref
		self.value_ref = value_ref
		self.resolve_ref = resolve_ref
		self.reject_ref = reject_ref
		self.jsvalue = jscore.jsvalueref_to_jsvalue(self.context_ref, self.value_ref)
		self.jsresolve = jscore.jsvalueref_to_jsvalue(self.context_ref, self.resolve_ref)
		self.jsreject = jscore.jsvalueref_to_jsvalue(self.context_ref, self.reject_ref)
		self._promise = jsvalue_acessor(self.jsvalue)
		self._resolve = javascript_function(self.jsresolve)
		self._reject = javascript_function(self.jsreject)
	
	def call(self):
		if self._callback is None:
			return
		if self._resolve is None or self._reject is None:
			raise Exception("Promise call requires resolve and reject refs.")
		result = self._callback(self.resolve, self.reject) # TODO: make async?
		if isinstance(result, javascript_promise):
			return result # TODO: this might not work... 
		return self

	def get_jsvalue_ref(self, context_ref = None):
		if self.value_ref is None:
			self.compile(context_ref)
		return self.value_ref
	
	def get_jsvalue(self, context):
		if self.jsvalue is None:
			self.compile(context)
		return self.jsvalue
		
	def resolve(self, *args):
		if self._resolve is None:
			if self.jsvalue is None:
				raise Exception("Promise must be compiled")
			else:
				raise Exception("Promise resolve is only available in root promise.")
		return self._resolve.call(*args)
		
	def reject(self, *args):
		if self._reject is None:
			if self.jsvalue is None:
				raise Exception("Promise must be compiled")
			else:
				raise Exception("Promise reject is only available in root promise.")
		return self._reject.call(*args)
	
	def then(self, callback):
		if self._promise is None:
			raise Exception("Promise must be compiled")
		return javascript_promise(~(self._promise.then(callback)))
		
	def catch(self, callback):
		if self._promise is None:
			raise Exception("Promise must be compiled")
		return javascript_promise(~(self._promise.catch(callback)))
		
	def final(self, callback):
		if self._promise is None:
			raise Exception("Promise must be compiled")
		return javascript_promise(~(self._promise["finally"](callback)))


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
		jscore.jsstringref_release(self.source_ref)
		jscore.jsstringref_release(self.url_ref)
		
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

#async module loader implementation of JSCoreModuleLoaderDelegate
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
		self.load_script(script, scriptType, sourceUrl, sourceUrl, source)
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
			if self._exception is not None:
				self._exception = javascript_error(self._exception)
		
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

# runtime base for all javascriptcore runtimes and shared/singleton context
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
		path = None
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
		value = self.___jsobject___.valueForProperty_(key)
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
		self.___set___(key, value)

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
			value = self.___globalObject___.valueForProperty_(key)
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
			jsvalue = self.___globalObject___.valueForProperty_(key)
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
	
	def __init__(self, data = None, name = None, path = None, imports = {}):
		self.name = name
		if self.name is not None:
			self.name = wasm_module.get_module_name(self.name)
		self.path = path
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
				raise ImportError(f"Invalid wasm module. Modules must start with '{wasm_module.header}'.")
			self.data.append(data)
		elif isinstance(data, str) or isinstance(data, Path):
			self.nsdata = objc.nsdata_from_file(data)
		elif data is not None:
			raise ImportError("Unknown module data type "+type(data))
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
		
	def load(self, context, env = None):
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
		self.module, self.name = self.context._load_module_array(self.jsdata, self.name, self._imports, env)
		self.instance = self.module.instance
		_start = self.exports._start
		_initialize = self.exports._initialize
		if javascript_value.is_not_null(_start) and javascript_value.is_not_null(_initialize):
			raise ImportError("Invalid wasm_module has _start and _initialize exports, modules are commands or reactors mutually exclusively.")
		if not javascript_value.is_null_or_undefined(_initialize):
			_initialize() # call initialize for reactors
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
		with open(path, "wb") as module_file:
			module_file.write(self.bytes)

	@classmethod
	def get_module_version(cls, name):
		version_index = name.rfind('@')
		version = ''
		if version_index > -1:
			version = name[version_index+1:]
		return version

	@classmethod
	def get_module_id(cls, name):
		module = name.split('@')[0]
		module = module.split('/')[0]
		version = cls.get_module_version(name)
		if len(version) > 0:
			return f"{module}@{version}"
		return module

	@classmethod
	def get_module_name(cls, path):
		path = str(path)
		version_index = path.rfind('@')
		if version_index > -1:
			path = path[:version_index]
			path = path.split('/')[0]
			path = path.replace(':','_')
		if version_index > -1 or '/' not in path or path.find(':') > 1:
			return path
		name = Path(str(path)).name.split('.component.wasm')[0]
		name = name.split('.wasm')[0]
		return name
		
	@classmethod
	def get_module_path(cls, name):
		id = cls.get_module_id(name)
		version = cls.get_module_version(id)
		name = cls.get_module_name(id)
		if len(version) > 0:
			return f"{version}/{name}"
		return name
	
	@classmethod
	def get_file_path(cls, path):
		path = Path(str(path))
		if not path.is_absolute():
			path = path.cwd().joinpath(path)
		return path
		
	@classmethod
	def get_module_file_path(cls, module):
		if isinstance(module, cls):
			return module.path
		return cls.get_file_path(module)
	
	@classmethod
	def from_file_py(cls, path):
		path = cls.get_file_path(path)
		with open(path) as module_file:
			data = module_file.read()
			name = cls.get_module_name(path)
			return cls(data, name, path)
			
	@classmethod
	def from_file(cls, path, fileManager = None):
		path = cls.get_file_path(path)
		data = objc.nsdata_from_file(str(path), fileManager)
		name = cls.get_module_name(path)
		return cls(data, name, path)

class wasm_process_thread(threading.Thread):
	def __init__(self, process, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.process = process
		self.lock = threading.RLock()
		self.awaiter = threading.Condition(self.lock)
		self.exit_code = None
		
	def run(self):
		self.exit_code = self.process.run()
		with self.awaiter:
			self.awaiter.notify_all()
			
	def wait(self, timeout = None, join = False):
		with self.awaiter:
			self.awaiter.wait(timeout = timeout)
		if join:
			self.join(timeout = timeout)

# represents a lightweight wasm_process which may run as a thread or another execution unit
# it aims to replicate an interface like subprocess and act as a similar replacement
# for python code which would interact with a system process which isnt otherwise supported by ios
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
		# c style _start entry point
		exit_code = None
		_start = self.module.exports._start
		if not javascript_value.is_null_or_undefined(_start):
			try:
				self.running = True
				exit_code = _start()
				if javascript_value.is_null_or_undefined(exit_code):
					exit_code = None
				return self._terminated(exit_code)
			except Exception as e:
				self.exception = None
				if self.exit_code is None:
					exit_code = -1 # exited with exception
				if not (self.killing or self.killed):
					self.exception = e
				if self.exit_code is None:
					if self.exception is not None:
						log.exception(f"wasm_process terminated unexpectedly, exception: {e}")
		else:
			exit_code = -2 # no entry point
			try:
				raise ImportError(f"wasm_process execution failed, entry point _start not found in module {self.module.path}.")
			except ImportError as e:
				log.exception(f"{e}")
		return self._terminated(exit_code)
	
	def run_async(self):
		if self.thread is not None:
			raise Exception("Process thread is already running.")
		self.thread = wasm_process_thread(self)
		self.thread.start()
		return self

	def communicate(self, stdin = None, timeout = None):
		if isinstance(stdin, str):
			self.stdin.write(input)
		self.wait_until_exit(timeout = timeout)
		return self.stdout.getvalue(), self.stderr.getvalue()
		
	def notify(self):
		with self.awaiter:
			self.awaiter.notify()
			
	def notify_all(self):
		with self.awaiter:
			self.awaiter.notify_all()

	def kill(self, *args, **kwargs):
		self.killing = True
		self.killed = True
		# this needs to actually kill the thread
	
	def _terminated(self, exit_code = None):
		self.running = False
		self.thread = None
		if exit_code is not None:
			self.exit_code = exit_code
		if self.callback is not None:
			self.callback(self)
		return self.exit_code
		
	def wait(self, timeout = None, join = False):
		if self.thread is not None:
			self.thread.wait(timeout = timeout, join = join)
		
	def wait_until_exit(self, timeout = None):
		self.wait(timeout = timeout, join = True)
		
	def send_signal(self, sig):
		print(sig)

class wasm_io(io.StringIO):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.awaiter = threading.Condition(threading.Lock())
		self.read_count = 0
		self.write_count = 0
		
	def read(self, *args, **kwargs):
		count = self.write_count
		with self.awaiter:
			while count == self.write_count:
				self.awaiter.wait()
			data = super().read(*args, **kwargs)
			self.read_count += 1
			return data
		
	def write(self, *args, **kwargs):
		with self.awaiter:
			cookie = self.tell()
			written = super().write(*args, **kwargs)
			self.seek(cookie)
			self.write_count += 1
			self.awaiter.notify()
			return written

class wasm_component:
	def __init__(self, wasi, env):
		self._wrap_handlers()
		self.wasi = wasi
		self.env = env
	
	@property
	def memory(self):
		return self.env.memory
		
	@property
	def memory_view(self):
		return self.env.memory_view
	
	def _error_handler(self, func, func_name, component_type):
		def error_handler(*args, **kwargs):
			try:
				log.debug(f"call wasm_component {component_type}.{func_name}: {args} {kwargs}")
				err = func(*args, **kwargs)
				if err is None:
					err = wasi_err.success
				else:
					err = wasi_err(err)
				log.debug(f"return wasm_component {component_type}.{func_name}: {err.name}, {err}")
				return err
			except Exception as e:
				err = wasi_err.fault
				if isinstance(e, wasi_error):
					err = e.err
					e = e.ex
				log.exception(f"Exception in wasm_component {component_type}.{func_name}: {err.name}, {err} {e}")
				return err # we need to return a failure code to wasm if an error or exception is not otherwise handled
		return error_handler
	
	def _wrap_handlers(self):
		class _exclude_members(wasm_component):
			def __init__(self):
				pass
		attr_names = set(dir(self)) - set(dir(_exclude_members()))
		component_type = type(self)
		for attr_name in attr_names:
			attr = getattr(self, attr_name)
			if callable(attr):
				setattr(self, attr_name, self._error_handler(attr, attr_name, component_type))

# common
class wasi_err(enum.IntEnum):
	success = 0 #;;; No error occurred. System call completed successfully.
	toobig = enum.auto() #;;; Argument list too long.
	acces = enum.auto()  #;;; Permission denied.
	addrinuse = enum.auto() #;;; Address in use.
	addrnotavail = enum.auto() #;;; Address not available.
	afnosupport = enum.auto() #;;; Address family not supported.
	again = enum.auto() #;;; Resource unavailable, or operation would block.
	already = enum.auto() #;;; Connection already in progress.
	badf = enum.auto() #;;; Bad file descriptor.
	badmsg = enum.auto() #;;; Bad message.
	busy = enum.auto() #;;; Device or resource busy.
	canceled = enum.auto() #;;; Operation canceled.
	child = enum.auto() #;;; No child processes.
	connaborted = enum.auto() #;;; Connection aborted.
	connrefused = enum.auto() #;;; Connection refused.
	connreset = enum.auto() #;;; Connection reset.
	deadlk = enum.auto() #;;; Resource deadlock would occur.
	destaddrreq = enum.auto() #;;; Destination address required.
	dom = enum.auto() #;;; Mathematics argument out of domain of function.
	dquot = enum.auto() #;;; Reserved.
	exist = enum.auto() #;;; File exists.
	fault = enum.auto() #;;; Bad address.
	fbig = enum.auto() #;;; File too large.
	hostunreach = enum.auto() #;;; Host is unreachable.
	idrm = enum.auto() #;;; Identifier removed.
	ilseq = enum.auto() #;;; Illegal byte sequence.
	inprogress = enum.auto() #;;; Operation in progress.
	intr = enum.auto() #;;; Interrupted function.
	inval = enum.auto() #;;; Invalid argument.
	io = enum.auto() #;;; I/O error.
	isconn = enum.auto() #;;; Socket is connected.
	isdir = enum.auto() #;;; Is a directory.
	loop = enum.auto() #;;; Too many levels of symbolic links.
	mfile = enum.auto() #;;; File descriptor value too large.
	mlink = enum.auto() #;;; Too many links.
	msgsize = enum.auto() #;;; Message too large.
	multihop = enum.auto() #;;; Reserved.
	nametoolong = enum.auto() #;;; Filename too long.
	netdown = enum.auto() #;;; Network is down.
	netreset = enum.auto() #;;; Connection aborted by network.
	netunreach = enum.auto() #;;; Network unreachable.
	nfile = enum.auto() #;;; Too many files open in system.
	nobufs = enum.auto() #;;; No buffer space available.
	nodev = enum.auto() #;;; No such device.
	noent = enum.auto() #;;; No such file or directory.
	noexec = enum.auto() #;;; Executable file format error.
	nolck = enum.auto() #;;; No locks available.
	nolink = enum.auto() #;;; Reserved.
	nomem = enum.auto() #;;; Not enough space.
	nomsg = enum.auto() #;;; No message of the desired type.
	noprotoopt = enum.auto() #;;; Protocol not available.
	nospc = enum.auto() #;;; No space left on device.
	nosys = enum.auto() #;;; Function not supported.
	notconn = enum.auto() #;;; The socket is not connected.
	notdir = enum.auto() #;;; Not a directory or a symbolic link to a directory.
	notempty = enum.auto() #;;; Directory not empty.
	notrecoverable = enum.auto() #;;; State not recoverable.
	notsock = enum.auto() #;;; Not a socket.
	notsup = enum.auto() #;;; Not supported, or operation not supported on socket.
	notty = enum.auto() #;;; Inappropriate I/O control operation.
	nxio = enum.auto() #;;; No such device or address.
	overflow = enum.auto() #;;; Value too large to be stored in data type.
	ownerdead = enum.auto() #;;; Previous owner died.
	perm = enum.auto() #;;; Operation not permitted.
	pipe = enum.auto() #;;; Broken pipe.
	proto = enum.auto() #;;; Protocol error.
	protonosupport = enum.auto() #;;; Protocol not supported.
	prototype = enum.auto() #;;; Protocol wrong type for socket.
	range = enum.auto() #;;; Result too large.
	rofs = enum.auto() #;;; Read-only file system.
	spipe = enum.auto() #;;; Invalid seek.
	srch = enum.auto() #;;; No such process.
	stale = enum.auto() #;;; Reserved.
	timedout = enum.auto() #;;; Connection timed out.
	txtbsy = enum.auto() #;;; Text file busy.
	xdev = enum.auto() #;;; Cross-device link.
	notcapable = enum.auto() # ;;; Extension: Capabilities insufficient.
	
class wasi_error(Exception):
	def __init__(self, ex, err = None):
		self.ex = ex
		self.err = err
		if self.err is None:
			self.err = wasi_err.notrecoverable

# https://github.com/WebAssembly/WASI/blob/v0.2.11/docs/Preview2.md
class wasi_io(wasm_component):
	pass

class wasi_clocks(wasm_component):
	pass

class wasi_random(wasm_component):
	pass

class wasi_filesystem(wasm_component):
	pass

class wasi_sockets(wasm_component):
	pass

class wasi_cli(wasm_component):
	pass

class wasi_http(wasm_component):
	pass

#https://github.com/WebAssembly/WASI/blob/wasi-0.1/preview1/witx/wasi_snapshot_preview1.witx
#https://github.com/WebAssembly/WASI/blob/wasi-0.1/tools/witx/src/abi.rs
# preview1: wasi_snapshot_preview1
# preview0: wasi_unstable, snapshot_0
class wasi_snapshot_preview1(wasm_component):

	def args_get(self, argv, argv_buf):
		offset = argv_buf
		for i in range(len(self.env.args)):
			self.memory_view.setUint32(argv + 4 * i, offset)
			offset = self.memory_view.setString(offset, self.env.args[i])

	def args_sizes_get(self, count, size):
		self.memory_view.setUint32(count, len(self.env.args))
		self.memory_view.setUint32(size, len("".join(self.env.args))+len(self.env.args))

	def environ_get(self, environ, environ_buf):
		offset = environ_buf
		i = 0
		for k, v in self.env.vars.items():
			self.memory_view.setUint32(environ + 4 * i, offset)
			offset = self.memory_view.setString(offset, f"{k}={v}")
			i += 1

	def environ_sizes_get(self, count, size):
		self.memory_view.setUint32(count, len(self.env.vars))
		sz = 0
		for k,v in self.env.vars.items():
			sz += len(k) + len(v) + 2 # 2 bytes for = and zero terminator
		self.memory_view.setUint32(size, sz)

	def clock_res_get(self, id):
		return wasi_err.notcapable

	def clock_time_get(self, id, precision):
		return wasi_err.notcapable

	def fd_advise(self, fd, offset, len, advice):
		return wasi_err.notcapable

	def fd_allocate(self, fd, offset, len):
		return wasi_err.notcapable

	def fd_close(self, fd):
		return wasi_err.notcapable

	def fd_datasync(self, fd):
		return wasi_err.notcapable

	def fd_fdstat_get(self, fd):
		return wasi_err.notcapable

	def fd_fdstat_set_flags(self, fd, flags):
		return wasi_err.notcapable

	def fd_fdstat_set_rights(self, fd, fs_rights_base, fs_rights_inheriting):
		return wasi_err.notcapable

	def fd_filestat_get(self, fd):
		return wasi_err.notcapable

	def fd_filestat_set_size(self, fd, size):
		return wasi_err.notcapable

	def fd_filestat_set_times(self, fd, atim, mtim, fst_flags):
		return wasi_err.notcapable

	def fd_pread(self, fd, iovs, offset):
		return wasi_err.notcapable

	def fd_prestat_get(self, fd):
		return wasi_err.notcapable

	def fd_prestat_dir_name(self, fd, path, pathlen):
		return wasi_err.notcapable

	def fd_pwrite(self, fd, iovs, offset):
		return wasi_err.notcapable

	def fd_read(self, fd, iovs):
		return wasi_err.notcapable

	def fd_readdir(self, fd, buf, buf_len, cookie):
		return wasi_err.notcapable

	def fd_renumber(self, fd, to):
		return wasi_err.notcapable

	def fd_seek(self, fd, offset, whence):
		return wasi_err.notcapable

	def fd_sync(self, fd):
		return wasi_err.notcapable

	def fd_tell(self, fd):
		return wasi_err.notcapable

	def fd_write(self, fd, ciovs_buf, ciovs_count, ciov_size):
		stream = self.env.get_stream(fd)
		if stream is None:
			return wasi_err.badf
		written = 0
		iov = fd != 2 and ciovs_count == 1
		for i in range(int(ciovs_count)):
			ciov = ciovs_buf + (i * 8)
			ptr = self.memory_view.getUint32(ciov)
			size = self.memory_view.getUint32(ciov+4)
			text = self.memory_view.getString(ptr, size)
			stream.write(text)
			written += size
		self.memory_view.setUint32(ciov_size, written)

	def path_create_directory(self, fd, path):
		return wasi_err.notcapable

	def path_filestat_get(self, fd, flags, path):
		return wasi_err.notcapable

	def path_filestat_set_times(self, fd, flags, path, atim, mtim, fst_flags):
		return wasi_err.notcapable

	def path_link(self, old_fd, old_flags, old_path, new_fd, new_path):
		return wasi_err.notcapable

	def path_open(self, fd, dirflags, path, oflags, fs_rights_base, fs_rights_inheriting, fdflags):
		return wasi_err.notcapable

	def path_readlink(self, fd, path, buf, buf_len):
		return wasi_err.notcapable

	def path_remove_directory(self, fd, path):
		return wasi_err.notcapable

	def path_rename(self, fd, old_path, new_fd, new_path):
		return wasi_err.notcapable

	def path_symlink(self, old_path, fd, new_path):
		return wasi_err.notcapable

	def path_unlink_file(self, fd, path):
		return wasi_err.notcapable
		
	def poll_oneoff(self, events_in, events_out, nsubscriptions):
		return wasi_err.notcapable

	def proc_exit(self, rval):
		self.env.exit_code = int(rval)

	def proc_raise(self, sig):
		return wasi_err.notcapable

	def sched_yield(self):
		return wasi_err.notcapable

	def random_get(self, buf, buf_len):
		buf_len = int(buf_len)
		if buf_len < 0:
			return wasi_err.inval
		if buf_len == 0:
			return wasi_err.success
		data = secrets.token_bytes(buf_len)
		for i in range(buf_len):
			self.memory_view.setUint8(buf+i, data[i])

	def sock_accept(self, fd, flags):
		return wasi_err.notcapable

	def sock_recv(self, fd, ri_data, ri_flags):
		return wasi_err.notcapable

	def sock_send(self, fd, si_data, si_flags):
		return wasi_err.notcapable

	def sock_shutdown(self, fd, how):
		return wasi_err.notcapable

class wasm_wasi:
	def __init__(self, context, env):
		self.context = context
		self.env = env
		self.preview1 = wasi_snapshot_preview1
		self.context.imports.wasi_snapshot_preview1 = self.preview1

class wasm_memory(javascript_value_base):
	pass

class wasm_memory_view:
	def __init__(self, memory, view, getter_littleEndian = None, setter_littleEndian = None):
		self.memory = memory
		self._view = view
		self._view_obj = view.jsobject
		self.system_littleEndian = sys.byteorder == "little"
		if getter_littleEndian is None:
			getter_littleEndian = self.system_littleEndian
		if setter_littleEndian is None:
			setter_littleEndian = self.system_littleEndian
		self.getter_littleEndian = getter_littleEndian
		self.setter_littleEndian = setter_littleEndian
	
	@property
	def view(self):
		return self._view.value
	
	@property
	def buffer(self):
		return self._view_obj.buffer.value
		
	@property
	def byteLength(self):
		return self._view_obj.byteLength.value
		
	@property
	def byteOffset(self):
		return self._view_obj.byteOffset.value
		
	def getter_endianess(self, littleEndian = None):
		if littleEndian is not None:
			return littleEndian
		return self.getter_littleEndian
		
	def setter_endianess(self, littleEndian = None):
		if littleEndian is not None:
			return littleEndian
		return self.setter_littleEndian
	
	def getBigInt64(self, offset, littleEndian = None):
		return self.view.getBigInt64(offset, self.getter_endianess(littleEndian))

	def setBigInt64(self, offset, value, littleEndian = None):
		self.view.setBigInt64(offset, value, self.setter_endianess(littleEndian))

	def getBigUint64(self, offset, littleEndian = None):
		return self.view.getBigUint64(offset, self.getter_endianess(littleEndian))

	def setBigUint64(self, offset, value, littleEndian = None):
		return self.view.setBigUint64(offset, value, self.setter_endianess(littleEndian))

	def getFloat16(self, offset, littleEndian = None):
		return self.view.getFloat16(offset, self.getter_endianess(littleEndian))

	def setFloat16(self, offset, value, littleEndian = None):
		return self.view.setFloat16(offset, value, self.setter_endianess(littleEndian))

	def getFloat32(self, offset, littleEndian = None):
		return self.view.getFloat32(offset, self.getter_endianess(littleEndian))

	def setFloat32(self, offset, value, littleEndian = None):
		return self.view.setFloat32(offset, value, self.setter_endianess(littleEndian))

	def getFloat64(self, offset, littleEndian = None):
		return self.view.getFloat64(offset, self.getter_endianess(littleEndian))

	def setFloat64(self, offset, value, littleEndian = None):
		return self.view.setFloat64(offset, value, self.setter_endianess(littleEndian))

	def getInt8(self, offset):
		return self.view.getInt8(offset)

	def setInt8(self, offset, value):
		return self.view.setInt8(offset, value)

	def getInt16(self, offset, littleEndian = None):
		return self.view.getInt16(offset, self.getter_endianess(littleEndian))

	def setInt16(self, offset, value, littleEndian = None):
		return self.view.setInt16(offset, value, self.setter_endianess(littleEndian))
		
	def getInt32(self, offset, littleEndian = None):
		return self.view.getInt32(offset, self.getter_endianess(littleEndian))

	def setInt32(self, offset, value, littleEndian = None):
		return self.view.setInt32(offset, value, self.setter_endianess(littleEndian))
		
	def getUint8(self, offset):
		return self.view.getUint8(offset)

	def setUint8(self, offset, value):
		return self.view.setUint8(offset, value)
		
	def getUint16(self, offset, littleEndian = None):
		return self.view.getUint16(offset, self.getter_endianess(littleEndian))

	def setUint16(self, offset, value, littleEndian = None):
		return self.view.setUint16(offset, value, self.setter_endianess(littleEndian))

	def getUint32(self, offset, littleEndian = None):
		return self.view.getUint32(offset, self.getter_endianess(littleEndian))

	def setUint32(self, offset, value, littleEndian = None):
		return self.view.setUint32(offset, value, self.setter_endianess(littleEndian))
	
	max_string = 2048
	def getString(self, offset, length, littleEndian = None):
		buffer = []
		max_string = wasm_memory_view.max_string
		try:
			for i in range(min(length, max_string)):
				b = self.getUint8(offset + i)
				if b == 0 and length > max_string:
					break # zero termination?
				buffer.append(b)
		except Exception as e:
			log.warning(f"wasm_memory_view.getString failed. {e}\ptr: {offset}, size: {length}, read: {len(buffer)}, buffer: {bytes(buffer)}")
			raise wasi_error(e, wasi_err.fault)
		try:
			buffer = bytes(buffer)
			return buffer.decode('utf8')
		except Exception as e:
			log.warning(f"wasm_memory_view.getString failed. {e}\ptr: {offset}, size: {length}, read: {len(buffer)}, buffer: {bytes(buffer)}")
			raise wasi_error(e, wasi_err.ilseq)

	def setString(self, offset, value, littleEndian = None):
		data = value.encode('utf8') + b'\0'
		data_len = len(data)
		for i in range(data_len):
			self.setUint8(offset + i, data[i])
		return offset + data_len

class wasm_env:
	def __init__(self, parent = None, args = [], kwargs = {}, memory_factory = None, memory_view_factory = None):
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
		self._memory_factory = memory_factory
		self._memory_view_factory = memory_view_factory
		self._memory = None
		self._memory_view = None
		self._components = None
		self._fds = {}
		self._streams = {}
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
	def components(self):
		if self._components is None:
			self._components = {}
		return self._components
		
	@property
	def process(self):
		return self._process
		
	@process.setter
	def process(self, value):
		self._process = value
		
	def notify(self):
		self.process.notify()
	
	def _ensure_memory(self):
		if self._memory_factory is None or self._memory is not None:
			return
		self._memory = wasm_memory(self._memory_factory())
		
	def _ensure_memory_view(self):
		if self._memory_view_factory is None or (self._memory_view is not None and self._memory_view.byteLength != 0):
			return
		self._memory_view = wasm_memory_view(self.memory, self._memory_view_factory(self.memory))
	
	@property
	def memory(self):
		self._ensure_memory()
		return self._memory
		
	@memory.setter
	def memory(self, value):
		if value is None:
			self._memory = None
		else:
			self._memory = wasm_memory(value)
		self._memory_view = None
		
	@property
	def memory_view(self):
		self._ensure_memory_view()
		return self._memory_view
	
	def preopen(self, dir):
		pass
	
	def get_fd(self, fd):
		return int(fd)
	
	def get_stream(self, fd):
		fd = self.get_fd(fd)
		if fd == 0:
			return self.stdin
		elif fd == 1:
			return self.stdout
		elif fd == 2:
			return self.stderr
		return self._streams.get(fd)
	

class wasm_context(jscore_context):
	def __init__(self, runtime, context = None):
		super().__init__(runtime, context)
		self._modules = {}
		self._imports = {}
		self._namespace = wasm_namespace(self._imports)
		self._env = wasm_env()
		self._wasi = wasm_wasi(self, self._env)
		self._lock = threading.RLock()
		self._processes = {}
		
	def allocate(self):
		super().allocate()
		self._loader = self.eval("""(function() {
		const _jscore_wasm_modules = {};
		return {
			"module_load": function (name, wasm_bin){
				const wasm_module = new WebAssembly.Module(wasm_bin);
				const wasm_module_imports = WebAssembly.Module.imports(wasm_module);
				const wasm_module_exports = WebAssembly.Module.exports(wasm_module);
				const wasm_module_info = {"module": wasm_module, "imports": wasm_module_imports, "exports": wasm_module_exports };
				_jscore_wasm_modules[name] = wasm_module_info; // ensure module remains in scope
				return wasm_module_info;
			},
			"module_instantiate": function (name, namespace){
				const wasm_module = _jscore_wasm_modules[name].module
				const wasm_instance = new WebAssembly.Instance(wasm_module, namespace);
				return {"instance": wasm_instance, "namespace": namespace, "module": wasm_module};
			},
			"memory_create": function(opts) {
				return new WebAssembly.Memory(opts);
			},
			"memory_view_create": function(wasm_memory) {
				return new DataView(wasm_memory.buffer);
			},
			};})();""").value

	def deallocate(self):
		while len(self._processes) > 0:
			with self._lock:
				processes = list(self._processes.keys())
			for process in processes:
				process.wait_until_exit()
		deallocating = True
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
		
	def find_module(self, name):
		module_path = wasm_module.get_module_path(name)
		module_name = wasm_module.get_module_name(name)
		paths = ["./", "./lib/", "./wasm/"]
		for path in paths:
			filenames = [
				f"{path}/{module_path}.wasm",
				f"{path}/{module_name}.wasm",
			]
			for filename in filenames:
				path = Path(filename)
				if path.exists():
					return path
		return None
		
	def load_module(self, module, env = None):
		print(f"load: {module}")
		if isinstance(module, str):
			if module.startswith("/") or module.startswith("./") or module.endswith(".wasm"):
				module = Path(module)
			else:
				name = module
				module = self.find_module(name)
				if module is None:
					raise ImportError(f"Module '{name}' not found.")
		if isinstance(module, Path):
			module_name = wasm_module.get_module_name(module)
			existing_module = self._modules.get(module_name)
			if existing_module is not None:
				return existing_module
			module = wasm_module.from_file(module)
		if not isinstance(module, wasm_module):
			raise ImportError("Module must be wasm_module")
		result = module.load(self, env)
		self._modules[module.name] = module
		return result
		
	def _resolve_module_imports(self, module, imports, env):
		if imports is None:
			imports = {}
		namespace = {}
		print("imports:", module.imports)
		print("exports:", module.exports)
		for module_import in module.imports:
			module_name = module_import.module
			import_name = module_import.name
			resolved_import = None
			if module_name == "js" and import_name == "memory":
				resolved_import = env.memory
			else:
				imports_module = imports.get(module_name)
				if imports_module is None:
					imports_module = self._imports.get(module_name)
				if imports_module is None:
					imports_module = {}
					imports[module_name] = imports_module
				if isinstance(imports_module, types.ModuleType):
					imports_module = getattr(imports_module, module_name)
				if isinstance(imports_module, type):
					if issubclass(imports_module, wasm_component):
						component_class = imports_module
						component = env.components.get(component_class)
						if component is None:
							component = component_class(self._wasi, env)
							env.components[component_class] = component
						if not hasattr(component, import_name):
							raise ImportError(f'Component "{component_class}" for module "{module_name}" missing expected import "{import_name}"')
						resolved_import = getattr(component, import_name)
				elif isinstance(imports_module, dict):
					resolved_import = imports_module.get(import_name)
				elif isinstance(imports_module, wasm_module):
					# if we have a module attempt to get export
					resolved_import = imports_module.exports[import_name]
				elif hasattr(imports_module, import_name):
					# if we have a class instance / wasm_component shim resolve from attributes
					resolved_import = getattr(imports_module, import_name)
				if javascript_value.is_null_or_undefined(resolved_import):
					# might need to check more for loading
					resolved_module = self.module_instance(module_name) 
					# above may be wrong for memory handling!
					# might need to create a new instance... settings for shared-everything vs shared-nothing abi?
					if resolved_module is None:
						resolved_module = self.load_module(module_name, env)
					resolved_import = resolved_module.exports[import_name]
			# wire up resolved import to module namespace
			if javascript_value.is_null_or_undefined(resolved_import):
				raise ImportError(f"Import '{module_name}.{import_name}' not found.")
			ns = namespace.get(module_name)
			if ns is None:
				ns = {}
				namespace[module_name] = ns
			ns[import_name] = resolved_import
		namespace = javascript_callback.wrap(self, namespace)
		return namespace
	
	def _load_module_array(self, module_data, name = None, imports = None, env = None):
		if not jscore.jsvalue_is_array_type(module_data, jscore.kJSTypedArrayTypeUint8Array):
			raise ImportError("Module array must be JSValue of an Uint8Array instance type.")
		if name is None:
			name = "wasm_module_"+str(len(self._modules))
		module = self._loader.module_load(name, module_data)
		namespace = self._resolve_module_imports(module, imports, env)
		module_instance = self._loader.module_instantiate.call(name, namespace)
		instance = module_instance.jsobject.instance
		memory = instance.exports.memory
		if javascript_value.is_not_null(memory) and env is not None:
			env.memory = memory
		return module_instance.value, name
	
	# creates a wasm_process which runs with this context, 
	# module: path to .wasm file or wasm_module, args: command line args
	# kwargs defaults:
	#	env = {}, dirs = [], world = None, version = None, 
	# stdin = io.StringIO(), stdout = io.StringIO(), stderr = io.StringIO()
	def new_process(self, module, *args, **kwargs):
		module_path = str(wasm_module.get_module_file_path(module))
		args = ( module_path, ) + args
		memory_factory = lambda: self._loader.memory_create.call({ "initial": 1 })
		memory_view_factory = lambda memory: self._loader.memory_view_create.call(memory)
		module_env = wasm_env(self._env, args, kwargs, memory_factory, memory_view_factory)
		module = self.load_module(module, env = module_env)
		def _cleanup(p):
			del self._processes[p]
		process = wasm_process(module_env, module, args, kwargs, _cleanup)
		module_env.process = process
		self._processes[process] = process
		return process, module_path
	
	def run(self, module, *args, **kwargs):
		# wasm/wasi synchronous run, this runs the given module/program on the current thread until termination
		process, module_path = self.new_process(module, *args, **kwargs)
		return process.run()

	def run_async(self, module, *args, **kwargs):
		# wasm/wasi asynchronous run, this runs the given module/program on a new thread until termination
		process, module_path = self.new_process(module, *args, **kwargs)
		return process.run_async()
		
	def serve(self, path, *args, **kwargs):
		# wasm/wasi serve placeholder
		# server needs handling as running a standard http server
		# this should run synchronously / block until termination
		pass
		
	def serve_async(self, path, *args, **kwargs):
		# async serve variant as background thread?
		pass


class wasm_runtime(jscore_runtime):
	def new_context(self, context):
		return wasm_context(self, context)


if __name__ == '__main__':
	import console
	console.clear()

	run_tests = False
	run_wasi_tests = True
	log.setLevel(logging.DEBUG)
	logging.basicConfig(level = logging.DEBUG)
	if run_tests:

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
		eval('throw new Error("Error message");');
		eval('throw new EvalError("EvalError message");')
		eval('throw new RangeError("RangeError message");')
		eval('throw new ReferenceError("ReferenceError message");')
		eval('throw new SyntaxError("SyntaxError message");')
		eval('throw new TypeError("TypeError message");')
		eval('throw new URIError("URIError message");')
		eval('throw new AggregateError([new Error("AggregatedError")], "AggregateError message");')
		
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
			resolve("resolve");
		});
		""").value.then(lambda v: print("then:", v)).catch(lambda e: print("catch:", e))
		
		p = context.eval("""new Promise((resolve,reject) => { 
			reject("reject");
		});
		""").value.then(lambda v: print("then:", v)).catch(lambda e: print("catch:", e))
		
		p = context.eval("""new Promise((resolve,reject) => { 
			throw new Error("exception");
		});
		""").value.then(lambda v: print("then:", v)).catch(lambda e: print("catch:", e))
		
		p = context.eval("""new Promise((resolve,reject) => { 
			resolve("resolve")
		});
		""").value.then(lambda v: print("then:", v)).catch(lambda e: print("catch:", e))["finally"](lambda: print("finally"))
		
		p = context.eval("""new Promise((resolve,reject) => { 
			reject("reject");
		});
		""").value.then(lambda v: print("then:", v)).catch(lambda e: print("catch:", e))["finally"](lambda: print("finally"))
		
		p = context.eval("""new Promise((resolve,reject) => { 
			throw new Error("exception");
		});
		""").value.then(lambda v: print("then:", v)).catch(lambda e: print("catch:", e))["finally"](lambda: print("finally"))
		
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

	if run_wasi_tests:
		test_suite_path = Path("./wasi_testsuite/wasm32-wasip").absolute()
		test_suite_path = str(test_suite_path)
		test_adapter_path = Path("./wasi_testsuite/jscore_runtime_adapter.py").absolute()
		test_adapter_path = str(test_adapter_path)
	
		from wasi_testsuite import wasi_test_runner_main
		wasi_test_runner_main("-t", test_suite_path + "1", test_suite_path + "3", "-r", test_adapter_path)
		

