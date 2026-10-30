"""Create immutable Stable Git tags only after the caller's artifact gates pass."""
import re
import subprocess
from scripts.upstream.resolve import api
from scripts.release.github import request


def commit_of(repo, reference):
    obj=reference.get('object',{})
    for _ in range(6):
        if not re.fullmatch('[0-9a-f]{40}',str(obj.get('sha',''))):
            raise ValueError('Invalid Stable Git tag object')
        if obj.get('type')=='commit':return obj['sha']
        if obj.get('type')!='tag':break
        obj=api(f'repos/{repo}/git/tags/{obj["sha"]}').get('object',{})
    raise ValueError('Stable tag does not resolve to a commit')


def ensure(repo,tag,sha):
    if (not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo)
            or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+-custom\.v[1-9][0-9]*\.[1-9][0-9]{0,5}',tag)
            or not re.fullmatch('[0-9a-f]{40}',sha)):
        raise ValueError('Invalid immutable Stable tag identity')
    path=f'repos/{repo}/git/ref/tags/{tag}'
    def verify(reference):
        if reference.get('ref')!='refs/tags/'+tag or commit_of(repo,reference)!=sha:
            raise ValueError('Stable tag already points to a different commit; never overwrite')
        return reference
    existing=api(path,missing=True)
    if existing:return verify(existing)
    commit=api(f'repos/{repo}/git/commits/{sha}')
    if commit.get('sha')!=sha:raise ValueError('Stable tag target commit mismatch')
    try:
        created=request('POST',f'repos/{repo}/git/refs',{'ref':'refs/tags/'+tag,'sha':sha})
    except subprocess.CalledProcessError:
        # Another writer may have created the exact same immutable ref. Never move it.
        concurrent=api(path,missing=True)
        if concurrent:return verify(concurrent)
        raise
    verify(created)
    return verify(api(path))
