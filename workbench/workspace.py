"""Verified edits and read-only inspection for the local baseline."""
from pathlib import Path
import difflib,hashlib,json,os,subprocess,tempfile
from .runtime import execute
def digest(data):return hashlib.sha256(data).hexdigest()
class Workspace:
    def __init__(self,repo,venv,evidence,package):
        self.repo=Path(repo).resolve();self.venv=Path(venv).resolve();self.evidence=Path(evidence).resolve()
        self.package=package;self.reads={};self.root=Path(tempfile.mkdtemp(prefix='reliable-baseline-'))
    def path(self,path,edit=False):
        path=str(path)
        if path.startswith('/work/'):path=path[6:]
        if path.startswith('/evidence/') and not edit:base=self.evidence;rel=path[10:]
        elif path.startswith('/env/') and not edit:base=self.venv;rel=path[5:]
        else:base=self.repo;rel=path
        p=(base/rel).resolve()
        if not p.is_relative_to(base) or p==base:raise ValueError('Path must remain inside the allowed directory.')
        if edit:
            r=p.relative_to(self.repo)
            if r.parts[0]!=self.package or p.suffix not in ('.py','.pyi') or any(x in ('tests','test') for x in r.parts) or p.name.startswith('test_') or p.name.endswith('_test.py') or p.name in ('conftest.py','setup.py'):
                raise ValueError('Only production Python files in the application package may be edited. Tests and manifests are protected.')
        return p
    def read_file(self,path,start_line=1,end_line=None):
        p=self.path(path);data=p.read_bytes();lines=data.decode().splitlines()
        start_line=max(1,int(start_line))
        end_line=start_line+199 if end_line is None else int(end_line)
        if end_line<start_line:raise ValueError('end_line must be at least start_line.')
        end_line=min(end_line,start_line+249,len(lines))
        version=digest(data);self.reads[str(p)]=version
        return {'status':'ok','path':path,'sha256':version,'total_lines':len(lines),'start_line':start_line,'end_line':end_line,
                'eof':start_line>len(lines),
                'content':'\n'.join(f'{i+1}: {lines[i]}' for i in range(start_line-1,end_line))}
    def edit_file(self,path,expected_sha256,old_text,new_text):
        p=self.path(path,edit=True);before=p.read_bytes();sha=digest(before)
        if self.reads.get(str(p))!=expected_sha256 or sha!=expected_sha256:
            raise ValueError('Fresh read required: file hash does not match the latest read. File unchanged.')
        source=before.decode()
        if not old_text or source.count(old_text)!=1:raise ValueError(f'Expected exactly one match, found {source.count(old_text) if old_text else 0}. File unchanged; read the exact source again.')
        if old_text==new_text:raise ValueError('No-op edit rejected. File unchanged.')
        after=source.replace(old_text,new_text,1).encode()
        check=subprocess.run([str(self.venv/'bin/python'),'-I','-c',"import sys;compile(sys.stdin.buffer.read(),sys.argv[1],'exec',dont_inherit=True)",str(p.relative_to(self.repo))],input=after,capture_output=True,timeout=10)
        if check.returncode:raise ValueError('Syntax rejected; file unchanged. '+check.stderr.decode()[-2000:])
        fd,name=tempfile.mkstemp(prefix='.verified-edit-',dir=p.parent)
        try:
            with os.fdopen(fd,'wb') as f:f.write(after);f.flush();os.fsync(f.fileno())
            os.chmod(name,p.stat().st_mode & 0o777)
            if digest(p.read_bytes())!=sha:raise ValueError('Concurrent modification; edit not applied.')
            os.replace(name,p)
        finally:
            if os.path.exists(name):os.unlink(name)
        self.reads.pop(str(p),None)
        return {'status':'applied','path':path,'before_sha256':sha,'after_sha256':digest(after),'syntax_check':'passed',
                'diff':''.join(difflib.unified_diff(source.splitlines(True),after.decode().splitlines(True),fromfile='a/'+path,tofile='b/'+path)),
                'note':'Applied and syntax-valid; behavior remains unverified. Run tests.'}
    def command(self,command,timeout=120):return execute(self.repo,self.venv,self.evidence,self.root,command,timeout)
    def source_hash(self):
        h=hashlib.sha256()
        for p in sorted((self.repo/self.package).rglob('*.py')):
            h.update(str(p.relative_to(self.repo)).encode()+b'\0'+p.read_bytes())
        return h.hexdigest()
