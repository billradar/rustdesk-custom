#!/usr/bin/env python3
"""Verify built 64-bit desktop library defaults through its existing FRB 1.x ABI.

No UI, core_main, server start, remote session, password output or password hash.
The parent runs this in a disposable process and never prints native output.
ABI sources: FRB v1.80.1 handler.rs and Dart 3.5.3 dart_native_api.h.
"""
import ctypes as C
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


class Object(C.Structure):
    pass


ObjectPtr = C.POINTER(Object)


class Array(C.Structure):
    _fields_ = [('length', C.c_ssize_t), ('values', C.POINTER(ObjectPtr))]


class Value(C.Union):
    # Largest Dart_CObject union member: external typed data (40 bytes on x64).
    _fields_ = [('boolean', C.c_bool), ('int32', C.c_int32),
                ('int64', C.c_int64), ('string', C.c_char_p),
                ('array', Array), ('abi_padding', C.c_uint64 * 5)]


Object._fields_ = [('type', C.c_int), ('value', Value)]


class WireBytes(C.Structure):
    _fields_ = [('ptr', C.POINTER(C.c_uint8)), ('length', C.c_int32)]


def decode(ptr, depth=0):
    if not ptr or depth > 4:
        raise ValueError('Invalid Bridge response')
    obj = ptr.contents
    if obj.type == 0:
        return None
    if obj.type == 1:
        return bool(obj.value.boolean)
    if obj.type == 2:
        return obj.value.int32
    if obj.type == 3:
        return obj.value.int64
    if obj.type == 5:
        if not obj.value.string:
            raise ValueError('Invalid Bridge string')
        return obj.value.string.decode('utf-8')
    if obj.type == 6:
        array = obj.value.array
        if not 0 <= array.length <= 16 or (array.length and not array.values):
            raise ValueError('Invalid Bridge array')
        return [decode(array.values[i], depth + 1) for i in range(array.length)]
    raise ValueError('Unsupported Bridge response type')


def check_values(read_option, expected):
    if not expected or read_option('password') != expected:
        raise ValueError('Built password initialization mismatch (value withheld)')
    if read_option('verification-method') != 'use-permanent-password':
        raise ValueError('Built verification method mismatch')


def inspect_library(library, app_dir, check_api=False):
    dll = C.CDLL(str(Path(library).resolve()))
    alloc = dll.new_uint_8_list_0
    alloc.argtypes, alloc.restype = [C.c_int32], C.POINTER(WireBytes)
    get = dll.wire_main_get_hard_option
    get.argtypes, get.restype = [C.POINTER(WireBytes)], ObjectPtr
    free = dll.free_WireSyncReturn
    free.argtypes, free.restype = [ObjectPtr], None
    init = dll.wire_main_init
    init.argtypes, init.restype = [C.c_int64, C.POINTER(WireBytes), C.POINTER(WireBytes)], None
    post_type = C.CFUNCTYPE(C.c_bool, C.c_int64, ObjectPtr)
    register = dll.store_dart_post_cobject
    register.argtypes, register.restype = [post_type], None

    def wire(text):
        raw = text.encode('utf-8')
        result = alloc(len(raw))
        if not result or result.contents.length != len(raw):
            raise ValueError('Bridge allocation failed')
        if raw:
            if not result.contents.ptr:
                raise ValueError('Bridge allocation failed')
            C.memmove(result.contents.ptr, raw, len(raw))
        return result  # Ownership passes to the generated Rust bridge.

    done = threading.Event()
    success = []

    @post_type
    def posted(port, message):
        if port not in (1, 2):
            return False
        try:
            result = decode(message)
            # Rust2Dart.success sends [0, data]; init returns unit/null.
            success.append(result == [0, None] if port == 1 else result)
        except Exception:
            success.append(False)
        done.set()
        return True

    register(posted)
    init(1, wire(str(app_dir)), wire(''))
    if not done.wait(20) or success != [True]:
        raise ValueError('Bridge configuration initialization failed')

    def read_option(key):
        result = get(wire(key))
        try:
            value = decode(result)
            if not isinstance(value, list) or len(value) != 2 or value[1] is not True or not isinstance(value[0], str):
                raise ValueError('Bridge configuration query failed')
            return value[0]
        finally:
            if result:
                free(result)

    check_values(read_option, os.environ.get('RUSTDESK_PASSWORD', ''))
    if check_api:
        query = dll.wire_main_get_api_server
        query.argtypes, query.restype = [C.c_int64], None
        success.clear(); done.clear(); query(2)
        expected = os.environ.get('RUSTDESK_API_SERVER', '').rstrip('/')
        if not expected or not done.wait(20) or success != [[0, expected]]:
            raise ValueError('Built API server query mismatch (value withheld)')


def verify(library, check_api=False):
    library = Path(library).resolve()
    if C.sizeof(C.c_void_p) != 8 or sys.platform not in ('win32', 'linux', 'darwin'):
        raise ValueError('Native configuration probe requires a supported 64-bit desktop host')
    if not library.is_file():
        raise ValueError('Built library missing')
    # Never publish native logs, a crash dump, or the expected password digest.
    with tempfile.TemporaryDirectory(prefix='rustdesk-config-check-') as app_dir:
        env = dict(os.environ, APPDATA=app_dir, LOCALAPPDATA=app_dir,
                   USERPROFILE=app_dir, HOME=app_dir, XDG_CONFIG_HOME=app_dir, XDG_DATA_HOME=app_dir)
        env['RUSTDESK_PROBE_API'] = '1' if check_api else '0'
        if sys.platform == 'linux':
            env['LD_LIBRARY_PATH'] = str(library.parent) + ':' + env.get('LD_LIBRARY_PATH', '')
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                     '--child', str(library), app_dir],
                                    env=env, cwd=app_dir, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=35)
        except subprocess.TimeoutExpired:
            raise ValueError('Built DLL configuration probe timed out') from None
        if result.returncode != 0:
            stages = {10: 'dynamic-library-load', 11: 'bridge-symbol',
                      12: 'bridge-initialization', 13: 'password-or-verification', 14: 'api-query'}
            stage = stages.get(result.returncode, 'native-process')
            if sys.platform == 'linux' and stage == 'dynamic-library-load':
                # Fixed library names only; never publish arbitrary loader exception text.
                output = subprocess.run(['ldd', str(library)], stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, universal_newlines=True).stdout
                import re
                missing = re.findall(r'^\s*([A-Za-z0-9_.+-]+) => not found$', output, re.M)
                if missing: print('DEPENDENCY: missing native libraries: ' + ', '.join(missing))
            raise ValueError('PLATFORM_API: native configuration probe failed at ' + stage +
                             ' (exit ' + str(result.returncode) + '; values withheld)')
    print('Built DLL password and verification method: PASS (values withheld)')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--verify-library':
        verify(sys.argv[2]);sys.exit(0)
    if len(sys.argv) != 4 or sys.argv[1] != '--child':
        raise SystemExit('Internal configuration probe invocation required')
    try:
        if os.name == 'nt':
            directory = os.add_dll_directory(str(Path(sys.argv[2]).resolve().parent))
        inspect_library(sys.argv[2], sys.argv[3], os.environ.get('RUSTDESK_PROBE_API') == '1')
    except OSError:
        os._exit(10)
    except AttributeError:
        os._exit(11)
    except ValueError as error:
        message = str(error)
        os._exit(14 if 'API server' in message else 13 if 'password' in message or 'verification' in message else 12)
    except BaseException:
        os._exit(1)
    # Terminate initialized library worker threads before deleting disposable files.
    os._exit(0)
