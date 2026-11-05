"""Offline direct-call measurements on this host, not the center's hardware."""
import ctypes,json,platform,socket,statistics,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from jeju_agent.discovery import discovery_recommend
def blocked(*args,**kwargs):raise AssertionError('External network is not used by local discovery')
socket.socket.connect=blocked;socket.getaddrinfo=blocked
def memory():
    if sys.platform!='win32':return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
    info=Counters();info.cb=ctypes.sizeof(info)
    get_memory=ctypes.WinDLL('psapi').GetProcessMemoryInfo
    get_memory.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD];get_memory.restype=wintypes.BOOL
    if get_memory(kernel.GetCurrentProcess(),ctypes.byref(info),info.cb):return {'working_set_bytes':info.WorkingSetSize,'peak_working_set_bytes':info.PeakWorkingSetSize}
    return None
results=[]
for food in ['흑돼지','갈치','고기국수','해산물','카페']:
    body={'query':food,'location':{'latitude':33.506,'longitude':126.492},'radius_km':20,'limit':6}
    discovery_recommend(ROOT,body);timings=[]
    for _ in range(3):
        start=time.perf_counter();result=discovery_recommend(ROOT,body);timings.append((time.perf_counter()-start)*1000)
    results.append({'query':food,'iterations':3,'median_ms':round(statistics.median(timings),3),'max_ms':round(max(timings),3),'mapped_restaurants':len(result['restaurants']),'unmapped_reference_rows_shown':len(result['unmapped_restaurants'])})
report={'checked_on_kst':'2026-10-28','python':platform.python_version(),'platform':platform.platform(),'scope':'warm direct function calls; browser/HTTP memory and target center hardware not measured','requires_gpu':False,'external_network_blocked':True,'memory':memory(),'results':results}
(ROOT/'examples'/'discovery_benchmark_v4.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))
