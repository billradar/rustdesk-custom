#!/usr/bin/env python3
"""Private compiler-side config validation; MIR contains secrets and is never uploaded."""
import json,os,re,subprocess,sys
from pathlib import Path

_REPO_ROOT=Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:sys.path.insert(0,str(_REPO_ROOT))

def function(text,name):
    # rustc 1.75 trims module paths when a function name is unambiguous.
    # Accept its qualified or trimmed spelling, but never choose among duplicates.
    matches=list(re.finditer(r'^fn (?:'+re.escape(name)+'|'+re.escape(name.rsplit('::',1)[-1])+r')\([^\n]*',text,re.M))
    if len(matches)!=1:raise ValueError('PLATFORM_API: configuration function missing or ambiguous in compiled MIR')
    match=matches[0]
    end=re.search(r'^}',text[match.end():],re.M)
    if not end:raise ValueError('PLATFORM_API: incomplete compiled MIR')
    return text[match.start():match.end()+end.end()]

def literals(text):
    # Rust MIR uses Rust escapes, including Unicode scalars rather than JSON surrogates.
    def decode(s):
        s=re.sub(r'\\u\{([0-9a-fA-F]+)\}',lambda m:chr(int(m[1],16)),s)
        return json.loads('"'+s+'"')
    # Also handles aggregate constants such as const Option::<&str>::Some("relay").
    return {decode(m[1]) for m in re.finditer(r'"((?:\\.|[^"\\])*)"',text)}

def verify(text,values):
    defaults=literals(function(text,'common::apply_custom_build_defaults'))
    if not {'password','verification-method','use-permanent-password',values['RUSTDESK_PASSWORD']}<=defaults:
        raise ValueError('PLATFORM_API: compiled password/defaults MIR mismatch (values withheld)')
    relay=values.get('RUSTDESK_RELAY_SERVER')
    if relay and not {'relay-server',relay}<=defaults:
        raise ValueError('PLATFORM_API: compiled relay MIR mismatch (values withheld)')
    if values['RUSTDESK_API_SERVER'] not in literals(function(text,'common::get_api_server_')):
        raise ValueError('PLATFORM_API: compiled API MIR mismatch (values withheld)')

def wrapper(args):
    compiler,*flags=args
    crate=flags[flags.index('--crate-name')+1] if '--crate-name' in flags else ''
    if crate!='librustdesk':return subprocess.call([compiler,*flags])
    folder=Path(os.environ['CONFIG_MIR_DIR']);folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    mir=folder/'client.mir';mir.unlink(missing_ok=True)
    for n,flag in enumerate(flags):
        if flag.startswith('--emit='):
            flags[n]=flag+',mir='+str(mir);break
    else:raise ValueError('BUILD_COMPAT: root rustc emit interface missing')
    code=subprocess.call([compiler,*flags])
    if code:return code
    mir.chmod(0o600)
    from scripts.signing.production_config import configured
    verify(mir.read_text(),configured())
    (folder/'validated.json').write_text(json.dumps({'result':'PASS','target':os.environ['PLATFORM_ARCH'],'method':'compiler-mir'})+'\n')
    return 0

if __name__=='__main__':
    try:sys.exit(wrapper(sys.argv[1:]))
    except Exception as error:
        # No MIR snippets, configured values or arbitrary compiler exception text.
        print('PLATFORM_API: compiler configuration validation failed ('+type(error).__name__+')',file=sys.stderr)
        sys.exit(1)
