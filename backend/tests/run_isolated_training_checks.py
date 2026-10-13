"""Isolated destination checks; original guard and recovered descriptor adapter.

Run from backend with the validated interpreter, dotenv disabled, SQLite-only,
CUDA hidden and pytest plugin autoload disabled. This is an application audit
guard, not an OS sandbox; native writes, races and hard links are not covered.
No launcher, historical receipts, datasets or checkpoints are loaded.
"""
import sys,os,json,tempfile,traceback,faulthandler,stat
from pathlib import Path
def install_descriptor_adapter(root):
    root=Path(root).resolve(strict=True)
    original=os.open
    write_flags=os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND
    def descriptor_open(path,flags,mode=0o777,*,dir_fd=None):
        decoded=os.fsdecode(os.fspath(path))
        if not decoded or dir_fd is None or Path(decoded).is_absolute() or not flags & write_flags:
            return original(path,flags,mode,dir_fd=dir_fd)
        try:
            descriptor_stat=os.fstat(dir_fd)
            base=Path(os.readlink(f'/proc/self/fd/{dir_fd}'))
            base_stat=base.stat()
            if not stat.S_ISDIR(descriptor_stat.st_mode) or (descriptor_stat.st_dev,descriptor_stat.st_ino)!=(base_stat.st_dev,base_stat.st_ino):
                raise RuntimeError('Directory descriptor identity unavailable')
            absolute=base/decoded
            target=absolute.resolve()
        except OSError as error:
            raise RuntimeError('Directory descriptor identity unavailable') from error
        if not target.is_relative_to(root):
            raise RuntimeError('Descriptor mutation outside private runtime')
        forwarded=os.fsencode(absolute) if isinstance(os.fspath(path),bytes) else str(absolute)
        return original(forwarded,flags,mode)
    os.open=descriptor_open
    return original

import hashlib, importlib.util
BACKEND=Path(__file__).resolve().parents[1]
AUTHORIZED_ROOT=BACKEND.parent
assert BACKEND == Path('/home/kevin/Work/fama/backend')
assert Path.cwd()==BACKEND
sys.path.insert(0,str(BACKEND))
guard_path=Path('/home/kevin/Work/fama-review-new-model-flow/backend/scripts/training_host_guard.py')
spec=importlib.util.spec_from_file_location('original_training_host_guard',guard_path)
guard_module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard_module)
install_guard=guard_module.install_guard
def _sha256(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def prepare_private_runtime(runtime):
    """Create one exclusive runtime and pin writable caches before ML imports."""
    runtime = Path(runtime)
    runtime.mkdir(mode=0o700)  # Never adopt a directory from another attempt.
    temporary = runtime / 'tmp'
    temporary.mkdir(mode=0o700)
    numba_cache = runtime / 'numba-cache'
    numba_cache.mkdir(mode=0o700)
    pinned_cache = runtime / 'hf-hub'
    os.environ.update({
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHON_DOTENV_DISABLED': '1',
        'NUMBA_DISABLE_JIT': '1', 'NUMBA_CACHE_DIR': str(numba_cache),
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'HF_HUB_DISABLE_TELEMETRY': '1', 'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1',
        'HF_HUB_CACHE': str(pinned_cache), 'TORCH_HOME': str(runtime / 'torch'),
        'TMPDIR': str(temporary), 'TMP': str(temporary), 'TEMP': str(temporary),
    })
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(temporary)
    return pinned_cache

baseline=json.loads((AUTHORIZED_ROOT/'docs/receipts/training-integration-baseline.json').read_text())
paths=[AUTHORIZED_ROOT/name for name in baseline['hashes']]
paths += [Path(__file__),guard_path]
before={str(path):_sha256(path) for path in paths}
code=1; scratch_path=None; guard_installed=False; reports=[]; summary={}
trace_fd=os.dup(2); original_open=os.open; sqlite_connects=[]
excluded=set()
deselected=[]
ambient_probe = sys.argv[1:] == ['--ambient-import-probe']
selectors=sys.argv[1:] or ['tests/test_training_flow.py','tests/test_training_persistence.py','tests/test_training_service.py','tests/test_api_training.py']
try:
    with tempfile.TemporaryDirectory(prefix='.training-consumer-suite-',dir=BACKEND) as directory:
        scratch_path=Path(directory); runtime=scratch_path/'runtime'; prepare_private_runtime(runtime)
        private_dirs={name:runtime/name for name in ('matplotlib','home','xdg-cache','xdg-config','hf-home')}
        for path in private_dirs.values(): path.mkdir(mode=0o700)
        os.environ.update({'MPLCONFIGDIR':str(private_dirs['matplotlib']),'MPLBACKEND':'Agg','HOME':str(private_dirs['home']),'XDG_CACHE_HOME':str(private_dirs['xdg-cache']),'XDG_CONFIG_HOME':str(private_dirs['xdg-config']),'HF_HOME':str(private_dirs['hf-home'])})
        font_commands={('fc-list','--help'),('fc-list','--format=%{file}'+chr(92)+'n')}
        def isolation_limits(event,args):
            if event=='open' and not isinstance(args[0],int) and Path(os.fsdecode(args[0])).name in ('.env','.pgpass','token'):
                raise RuntimeError('Credential read forbidden.')
            if event=='socket.connect': raise RuntimeError('Network/live DB connections forbidden throughout isolated consumer suite.')
            if event=='sqlite3.connect':
                if args[0]!=':memory:': raise RuntimeError('Only SQLite in-memory connections authorized.')
                sqlite_connects.append(':memory:')
            if event=='subprocess.Popen' and (Path(os.fsdecode(args[0])).name!='fc-list' or tuple(os.fsdecode(arg) for arg in args[1]) not in font_commands):
                raise RuntimeError('Only Matplotlib font discovery allowed before original guard.')
        sys.addaudithook(isolation_limits)
        import matplotlib.pyplot
        import pytest
        sys.path.insert(0,str(BACKEND))
        for variable in ('FAMA_TRAINING_AVESCHILENAS_RAW_READ_ROOT','FAMA_TRAINING_AVESCHILENAS_PREPARED_READ_DIR'):
            os.environ.pop(variable,None)
        print('PRIVATE_SCRATCH '+str(scratch_path),flush=True)
        faulthandler.dump_traceback_later(30,file=trace_fd,exit=True)
        install_guard([scratch_path]); guard_installed=True
        install_descriptor_adapter(scratch_path)
        class SuiteProof:
            @pytest.hookimpl(tryfirst=True)
            def pytest_runtest_setup(self,item):
                assert item.originalname not in excluded
                faulthandler.dump_traceback_later(30,file=trace_fd,exit=True)
            @pytest.hookimpl(tryfirst=True)
            def pytest_runtest_call(self,item):
                assert guard_installed
                root=item.funcargs.get('tmp_path')
                if root is not None:
                    assert root.resolve(strict=True).is_relative_to(scratch_path.resolve(strict=True))
                if 'training_env' in item.funcargs:
                    _,sessions,actual_root,_=item.funcargs['training_env']
                    assert root is not None and actual_root.resolve(strict=True)==root.resolve(strict=True)
                    url=sessions.kw['bind'].url
                    assert url.get_backend_name()=='sqlite' and url.database==':memory:'
                faulthandler.dump_traceback_later(30,file=trace_fd,exit=True)
            @pytest.hookimpl(tryfirst=True)
            def pytest_runtest_teardown(self,item,nextitem):
                faulthandler.dump_traceback_later(30,file=trace_fd,exit=True)
            def pytest_runtest_logreport(self,report):
                reports.append({'nodeid':report.nodeid,'phase':report.when,'outcome':report.outcome,'duration_seconds':round(report.duration,3)})
            def pytest_deselected(self,items):
                deselected.extend(item.nodeid for item in items)
            def pytest_sessionfinish(self,session,exitstatus):
                faulthandler.cancel_dump_traceback_later()
                for name,module in tuple(sys.modules.items()):
                    if name == 'app' or name.startswith(('app.','training.','poc.')):
                        location=getattr(module,'__file__',None)
                        if location: assert Path(location).resolve().is_relative_to(BACKEND)
        if ambient_probe:
            # Execute the exact existing subprocess-test payload in this fresh,
            # already guarded process; never launch a child from inside the guard.
            import ast, textwrap
            probe_file=BACKEND/'tests/test_model_reevaluation.py'
            tree=ast.parse(probe_file.read_text())
            test=next(node for node in tree.body if isinstance(node,ast.FunctionDef)
                      and node.name=='test_cli_and_reevaluation_imports_do_not_initialize_ambient_database_runtime')
            payloads=[node.value for node in ast.walk(test) if isinstance(node,ast.Constant)
                      and isinstance(node.value,str) and 'import scripts.reevaluate_model' in node.value]
            assert len(payloads)==1
            assert 'app' not in sys.modules and 'scripts.reevaluate_model' not in sys.modules
            exec(compile(textwrap.dedent(payloads[0]),str(probe_file),'exec'),{'__name__':'__main__'})
            for name,module in tuple(sys.modules.items()):
                if name=='app' or name.startswith(('app.','training.','poc.','scripts.')):
                    location=getattr(module,'__file__',None)
                    if location: assert Path(location).resolve().is_relative_to(BACKEND)
            assert not sqlite_connects
            summary['ambient_import_probe']='passed'
            summary['probe_payload_sha256']=hashlib.sha256(payloads[0].encode()).hexdigest()
            code=0
        else:
            code=int(pytest.main(['-q','-s','-x','-p','no:cacheprovider','--log-file',str(scratch_path/'pytest.log'),'--basetemp',str(scratch_path/'pytest'),*selectors],plugins=[SuiteProof()]))
        if code==0 and not ambient_probe:
            calls=[r for r in reports if r['phase']=='call']
            assert calls and all(r['outcome']=='passed' for r in calls)
            assert all(r['outcome']=='passed' for r in reports)
            assert guard_installed
except Exception as error:
    code=1  # A failed proof must never inherit pytest's successful exit code.
    traceback.print_exc(); summary.update(error_type=type(error).__name__)
finally:
    faulthandler.cancel_dump_traceback_later(); os.close(trace_fd); os.open=original_open
    assert {str(path):_sha256(path) for path in paths}==before
    cleaned=scratch_path is not None and not scratch_path.exists(); assert cleaned
    summary.update(phase='isolated_ambient_import_probe' if ambient_probe else 'isolated_training_fixture_consumer_suite',process_exit_code=code,pytest_exit_code=None if ambient_probe else code,deselected_cases=deselected,status='passed' if code==0 else 'failed',guard_before_collection_fixtures_and_body=guard_installed,phase_deadline_seconds=30,call_reports=[r for r in reports if r['phase']=='call'],nonpassing_reports=[r for r in reports if r['outcome']!='passed'],sqlite_memory_connection_count=len(sqlite_connects),excluded_completed_cases=sorted(excluded),private_scratch_cleanup=cleaned,code_guard_and_documentation_preserved=True,only_sqlite_synthetic_cpu=True,network_live_db_forbidden=True,no_further_environment_recovery=True)
    print('CHECK_SUMMARY '+json.dumps(summary),flush=True)
raise SystemExit(code)
