"""Local compute diagnostics; no third-party service or location access."""
import os,sys,time
from pathlib import Path
_PRELOAD={'status':'not_preloaded','provider':'not_loaded'}

def _gpu_platform():
    return os.name=='nt'

def configure_compute(root,semantic_device='cpu',road_gpu=False,no_road_gpu=False,preload=True):
    if semantic_device not in {'auto','cpu','dml'}:raise ValueError('invalid semantic device')
    if road_gpu and no_road_gpu:raise ValueError('conflicting road GPU options')
    gpu_platform=_gpu_platform()
    os.environ['JEJU_SEMANTIC_DEVICE']=semantic_device if gpu_platform else 'cpu'
    os.environ['JEJU_ROAD_GPU']='1' if gpu_platform and (road_gpu or (semantic_device!='cpu' and not no_road_gpu)) else '0'
    return preload_models(root) if preload else dict(_PRELOAD)

def _linux_process_memory():
    """Current process RSS/high-water RSS only; do not mislabel virtual size as commit."""
    try:
        fields={}
        for line in Path('/proc/self/status').read_text(encoding='ascii').splitlines():
            key,_,value=line.partition(':')
            if key in {'VmRSS','VmHWM'}:
                number,unit=value.split()
                if unit!='kB':raise ValueError('unexpected memory unit')
                fields[key]=int(number)*1024
        if not fields.get('VmRSS') or not fields.get('VmHWM'):raise ValueError('missing RSS')
        return {'available':True,'working_set_bytes':fields['VmRSS'],'peak_working_set_bytes':fields['VmHWM'],
                'scope':'server_process_only_browser_and_OS_excluded','measurement_source':'Linux_proc_self_status_RSS',
                'private_commit_available':False,'private_commit_is_not_physical_RAM':True}
    except (OSError,ValueError):
        try:
            import resource
            peak=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)*1024
            return {'available':True,'working_set_bytes':None,'peak_working_set_bytes':peak,
                    'scope':'server_process_only_browser_and_OS_excluded','measurement_source':'Linux_getrusage_peak_RSS_only',
                    'private_commit_available':False,'private_commit_is_not_physical_RAM':True}
        except (ImportError,OSError,ValueError,AttributeError):return {'available':False}

def process_memory():
    if sys.platform.startswith('linux'):return _linux_process_memory()
    if os.name!='nt':return {'available':False}
    try:
        import ctypes as ct
        from ctypes import wintypes as w
        class Counters(ct.Structure):
            _fields_=[('cb',w.DWORD),('PageFaultCount',w.DWORD)]+[(name,ct.c_size_t) for name in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage']]
        k=ct.WinDLL('kernel32',use_last_error=True);p=ct.WinDLL('psapi',use_last_error=True)
        k.GetCurrentProcess.restype=w.HANDLE
        p.GetProcessMemoryInfo.argtypes=[w.HANDLE,ct.POINTER(Counters),w.DWORD];p.GetProcessMemoryInfo.restype=w.BOOL
        data=Counters();data.cb=ct.sizeof(data)
        if not p.GetProcessMemoryInfo(k.GetCurrentProcess(),ct.byref(data),data.cb):raise OSError()
        return {'available':True,'working_set_bytes':data.WorkingSetSize,'peak_working_set_bytes':data.PeakWorkingSetSize,'private_commit_bytes':data.PrivateUsage,'scope':'server_process_only_browser_and_OS_excluded','private_commit_is_not_physical_RAM':True}
    except (OSError,ValueError,AttributeError):return {'available':False}

def preload_models(root):
    global _PRELOAD
    started=time.perf_counter()
    try:
        from .semantic_search import _configuration,_encode
        cfg,_=_configuration(Path(root))
        vector=_encode(Path(root),cfg,'바다와 화산의 풍경')
        if len(vector)!=cfg['embedding_dimension']:raise ValueError('embedding shape')
        from .semantic_gpu import compute_status
        gpu=compute_status()
        _PRELOAD={'status':'ready','provider':'DmlExecutionProvider' if gpu.get('gpu_ready') else 'CPUExecutionProvider','seconds':round(time.perf_counter()-started,4)}
    except Exception:
        # An optional model failure must not disable maps, verified guides or chat.
        _PRELOAD={'status':'optional_model_unavailable','provider':'not_loaded','seconds':round(time.perf_counter()-started,4)}
    return dict(_PRELOAD)

def runtime_status(root):
    from .semantic_gpu import compute_status
    from . import roads
    road={'requested':os.environ.get('JEJU_ROAD_GPU')=='1','graph_loaded':roads._load.cache_info().currsize>0,'gpu_ready':False,'scope':'dense_nearest_road_nodes_only_Astar_and_schedule_on_CPU'}
    if road['graph_loaded']:
        graph=roads._graph(Path(root));wrapper=graph[2].gpu if graph else None
        if wrapper is not None:
            road.update(gpu_ready=wrapper.gpu is not None,initialization_attempted=wrapper.attempted)
    return {'deployment_target':{'profile':'center','minimum_cpu':'Intel Core i7-8700','minimum_gpu':'GTX 1060','minimum_ram_gb':32,'target_hardware_benchmarked':False},'requested_semantic_device':os.environ.get('JEJU_SEMANTIC_DEVICE','cpu'),'semantic':compute_status(),'preload':dict(_PRELOAD,scope='startup_result_not_current_state'),'road':road,'server_process_id':os.getpid(),'process_memory':process_memory(),'small_tabular_models':'CPU_stdlib','retired_features':['regional_consumption_comparison'],'llm_used':False,'network_inference':False}
