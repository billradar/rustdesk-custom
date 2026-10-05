"""Exercise the real ctypes ABI against a compiled, fictional C bridge fixture."""
import contextlib
import ctypes as C
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import scripts.validation.native_config_probe as probe
import scripts.signing.production_config as config

FIXTURE = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
typedef struct Obj Obj;
struct Obj {int type; union {bool boolean; int64_t integer; const char *string;
    struct {intptr_t length; Obj **values;} array; uint64_t padding[5];} value;};
typedef struct {uint8_t *ptr; int32_t length;} Bytes;
static bool (*posted)(int64_t, Obj*);
void store_dart_post_cobject(bool (*p)(int64_t, Obj*)) {posted=p;}
Bytes *new_uint_8_list_0(int32_t n) {Bytes *b=malloc(sizeof(Bytes)); b->length=n;
    b->ptr=malloc(n+1); b->ptr[n]=0; return b;}
void discard(Bytes *b) {free(b->ptr);free(b);}
Obj *pair(Obj *a, Obj *b) {Obj *o=calloc(1,sizeof(Obj));o->type=6;
    o->value.array.length=2;o->value.array.values=malloc(2*sizeof(Obj*));
    o->value.array.values[0]=a;o->value.array.values[1]=b;return o;}
void free_WireSyncReturn(Obj *o) {if(o->type==6){free(o->value.array.values[0]);
    free(o->value.array.values[1]);free(o->value.array.values);}free(o);}
void wire_main_init(int64_t port, Bytes *a, Bytes *b) {
    discard(a);discard(b);
    const char *mode=getenv("BRIDGE_TEST_MODE");
    if(mode && strcmp(mode,"timeout")==0)return;
    Obj *code=calloc(1,sizeof(Obj)),*data=calloc(1,sizeof(Obj));
    code->type=3;code->value.integer=(mode && strcmp(mode,"init-error")==0)?1:0;
    Obj *o=pair(code,data);posted(port,o);free_WireSyncReturn(o);
}
Obj *wire_main_get_hard_option(Bytes *key) {
    Obj *data=calloc(1,sizeof(Obj)),*success=calloc(1,sizeof(Obj));
    data->type=5;success->type=1;success->value.boolean=true;
    const char *mode=getenv("BRIDGE_TEST_MODE");
    data->value.string=strcmp((char*)key->ptr,"password")==0 ? "tst" : "use-permanent-password";
    if(mode && strcmp(mode,"wrong-method")==0 && strcmp((char*)key->ptr,"verification-method")==0)
        data->value.string="use-temporary-password";
    if(mode && strcmp(mode,"query-error")==0)success->value.boolean=false;
    if(mode && strcmp(mode,"wrong-type")==0)data->type=0;
    discard(key);return pair(data,success);
}
void wire_main_get_api_server(int64_t port) {
    Obj *code=calloc(1,sizeof(Obj)),*data=calloc(1,sizeof(Obj));
    code->type=3;data->type=5;data->value.string="https://api.example.com";
    Obj *o=pair(code,data);posted(port,o);free_WireSyncReturn(o);
}
'''


class NativeBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler or os.name == 'nt':
            raise unittest.SkipTest('C ABI fixture uses the local Unix C compiler')
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        (cls.root / 'fixture.c').write_text(FIXTURE)
        cls.library = cls.root / 'fixture.so'
        subprocess.run([compiler, '-shared', '-fPIC', '-O3', str(cls.root/'fixture.c'),
                        '-o', str(cls.library)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def inspect(self, password='tst', mode=''):
        with patch.dict(os.environ, RUSTDESK_PASSWORD=password, BRIDGE_TEST_MODE=mode):
            probe.inspect_library(self.library, self.root)

    def test_short_password_through_compiled_native_bridge(self):
        self.inspect()

    def test_native_api_query_and_mismatch(self):
        with patch.dict(os.environ,RUSTDESK_PASSWORD='tst',BRIDGE_TEST_MODE='',RUSTDESK_API_SERVER='https://api.example.com'):
            probe.inspect_library(self.library,self.root,check_api=True)
        with patch.dict(os.environ,RUSTDESK_PASSWORD='tst',BRIDGE_TEST_MODE='',RUSTDESK_API_SERVER='https://wrong.example.com'):
            with self.assertRaisesRegex(ValueError,'API server'):probe.inspect_library(self.library,self.root,check_api=True)

    def test_wrong_password_blocks_without_disclosure(self):
        for expected in ('bad', 'a-long-fictional-password', '虚构密码'):
            with self.assertRaises(ValueError) as err:
                self.inspect(expected)
            self.assertNotIn(expected, str(err.exception))

    def test_wrong_verification_method_blocks(self):
        with self.assertRaisesRegex(ValueError, 'verification method'):
            self.inspect(mode='wrong-method')

    def test_initialization_and_query_errors_block(self):
        for mode in ('init-error', 'query-error', 'wrong-type'):
            with self.assertRaises(ValueError):self.inspect(mode=mode)

    def test_init_timeout_blocks(self):
        with patch.object(probe.threading.Event, 'wait', return_value=False):
            with self.assertRaisesRegex(ValueError, 'initialization'):
                self.inspect(mode='timeout')

    def test_decoder_rejects_null_and_invalid_array(self):
        with self.assertRaises(ValueError):probe.decode(probe.ObjectPtr())
        obj=probe.Object();obj.type=6;obj.value.array.length=999
        with self.assertRaises(ValueError):probe.decode(C.pointer(obj))

    def test_unicode_and_long_password_contract(self):
        for expected in ('虚构密码', 'fictional-long-password'):
            options={'password':expected,'verification-method':'use-permanent-password'}
            probe.check_values(options.get, expected)

    def test_binary_scan_requires_native_probe_even_without_password_bytes(self):
        values={'RUSTDESK_ID_SERVER':'id.example.com','RUSTDESK_RELAY_SERVER':'',
                'RUSTDESK_API_SERVER':'https://api.example.com',
                'RUSTDESK_KEY':'AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=',
                'RUSTDESK_PASSWORD':'tst'}
        dll=self.root/'scan-fixture.dll'
        dll.write_bytes(b'|'.join(v.encode() for k,v in values.items() if k!='RUSTDESK_PASSWORD'))
        self.assertNotIn(b'tst',dll.read_bytes())
        with patch.dict(os.environ,values), patch.object(probe,'verify') as native, contextlib.redirect_stdout(io.StringIO()):
            config.compiled(dll)
            native.assert_called_once_with(dll)
        with patch.dict(os.environ,values), patch.object(probe,'verify',side_effect=ValueError('probe failed')), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):config.compiled(dll)


if __name__ == '__main__':
    unittest.main()
