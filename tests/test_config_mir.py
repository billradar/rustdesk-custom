import os,sys,tempfile,unittest,shutil,subprocess
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import config_mir

VALUES={'RUSTDESK_PASSWORD':'aaaa','RUSTDESK_RELAY_SERVER':'relay.example.com','RUSTDESK_API_SERVER':'https://api.example.com'}
MIR='''fn common::apply_custom_build_defaults() -> () {
    _1 = const "password";
    _2 = const "aaaa";
    _3 = const "verification-method";
    _4 = const "use-permanent-password";
    _5 = const "relay-server";
    _6 = const "relay.example.com";
}
fn common::get_api_server_(_1: String, _2: String) -> String {
    _3 = const "https://api.example.com";
}
'''
class CompilerConfigTests(unittest.TestCase):
    def test_short_password_checked_in_compiled_function(self):config_mir.verify(MIR,VALUES)
    def test_wrong_or_missing_config_blocks_without_disclosure(self):
        for before,after in [('aaaa','bbbb'),('password','wrong-option'),('https://api.example.com','https://bad.example.com'),('relay.example.com','other.example.com')]:
            with self.assertRaises(ValueError) as error:config_mir.verify(MIR.replace(before,after),VALUES)
            self.assertNotIn(VALUES['RUSTDESK_PASSWORD'],str(error.exception))
    def test_unrelated_constants_do_not_prove_customization(self):
        with self.assertRaises(ValueError):config_mir.verify(MIR.replace('common::apply_custom_build_defaults','unrelated'),VALUES)
    def test_unicode_mir_literal(self):
        self.assertEqual(config_mir.literals('const "\\u{4e2d}文";'),{'中文'})
        self.assertEqual(config_mir.literals('const Option::<&str>::Some("relay.example.com");'),{'relay.example.com'})
    def test_wrapper_augments_actual_link_invocation(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,CONFIG_MIR_DIR=tmp,PLATFORM_ARCH='armv7'),patch('production_config.configured',return_value=VALUES):
            def compile(command):
                self.assertIn('--emit=dep-info,link,mir='+str(Path(tmp)/'client.mir'),command)
                (Path(tmp)/'client.mir').write_text(MIR);return 0
            with patch.object(config_mir.subprocess,'call',side_effect=compile):
                self.assertEqual(config_mir.wrapper(['rustc','--crate-name','librustdesk','--emit=dep-info,link']),0)
            self.assertNotIn('aaaa',(Path(tmp)/'validated.json').read_text())
    def test_dependency_compiler_unchanged(self):
        args=['rustc','--crate-name','dependency','--emit=dep-info,link']
        with patch.object(config_mir.subprocess,'call',return_value=0) as run:
            self.assertEqual(config_mir.wrapper(args),0);run.assert_called_once_with(args)

    def test_real_rust_compiler_mir_when_toolchain_available(self):
        compiler=shutil.which('rustc')
        if not compiler:self.skipTest('Rust compiler not installed on this local host; CI runs this with the reviewed toolchain')
        source='''mod common {
pub fn apply_custom_build_defaults() -> std::collections::HashMap<String,String> {
let mut options=std::collections::HashMap::new();
options.insert("password".to_owned(),env!("RUSTDESK_PASSWORD").to_owned());
options.insert("verification-method".to_owned(),"use-permanent-password".to_owned());
options.insert("relay-server".to_owned(),env!("RUSTDESK_RELAY_SERVER").to_owned());options
}
pub fn get_api_server_() -> String {env!("RUSTDESK_API_SERVER").to_owned()}
}
#[no_mangle] pub extern "C" fn keep_config() -> usize {
common::apply_custom_build_defaults().len()+common::get_api_server_().len()
}
'''
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{**VALUES,'CONFIG_MIR_DIR':tmp,'PLATFORM_ARCH':'armv7'}):
            path=Path(tmp)/'lib.rs';path.write_text(source)
            config_mir.wrapper([compiler,'--crate-name','librustdesk','--crate-type','cdylib','--emit=link','-O','--out-dir',tmp,str(path)])
            self.assertTrue((Path(tmp)/'validated.json').exists())
