"""Read-only Windows RAM and per-PID WDDM PDH GPU counters."""
import ctypes as c,json,time,re
from ctypes import wintypes as w
class PMC(c.Structure):
    _fields_=[('cb',w.DWORD),('PageFaultCount',w.DWORD)]+[(n,c.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage']]
class MEMSTAT(c.Structure):
    _fields_=[('dwLength',w.DWORD),('dwMemoryLoad',w.DWORD)]+[(n,c.c_ulonglong) for n in ['ullTotalPhys','ullAvailPhys','ullTotalPageFile','ullAvailPageFile','ullTotalVirtual','ullAvailVirtual','ullAvailExtendedVirtual']]
class VALUEUNION(c.Union):
    _fields_=[('longValue',c.c_long),('doubleValue',c.c_double),('largeValue',c.c_longlong),('AnsiStringValue',c.c_char_p),('WideStringValue',w.LPWSTR)]
class VALUE(c.Structure):
    _anonymous_=['u'];_fields_=[('CStatus',w.DWORD),('u',VALUEUNION)]
class ITEM(c.Structure):
    _fields_=[('szName',w.LPWSTR),('FmtValue',VALUE)]
class Probe:
    def __init__(self,pid):
        self.pid=pid;self.k=c.WinDLL('kernel32',use_last_error=True);self.ps=c.WinDLL('psapi',use_last_error=True);self.pdh=c.WinDLL('pdh',use_last_error=True)
        self.k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];self.k.OpenProcess.restype=w.HANDLE
        self.k.CloseHandle.argtypes=[w.HANDLE]
        self.ps.GetProcessMemoryInfo.argtypes=[w.HANDLE,c.POINTER(PMC),w.DWORD];self.ps.GetProcessMemoryInfo.restype=w.BOOL
        self.k.GetProcessTimes.argtypes=[w.HANDLE,c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME)]
        self.k.GlobalMemoryStatusEx.argtypes=[c.POINTER(MEMSTAT)]
        self.handle=self.k.OpenProcess(0x0400|0x0010,False,pid)
        if not self.handle:raise OSError(c.get_last_error(),'OpenProcess')
        self.q=w.HANDLE();self.counters={};self.errors=[]
        self.pdh.PdhOpenQueryW.argtypes=[w.LPCWSTR,c.c_size_t,c.POINTER(w.HANDLE)]
        self.pdh.PdhAddEnglishCounterW.argtypes=[w.HANDLE,w.LPCWSTR,c.c_size_t,c.POINTER(w.HANDLE)]
        self.pdh.PdhCollectQueryData.argtypes=[w.HANDLE]
        self.pdh.PdhGetFormattedCounterArrayW.argtypes=[w.HANDLE,w.DWORD,c.POINTER(w.DWORD),c.POINTER(w.DWORD),c.POINTER(ITEM)]
        self.pdh.PdhCloseQuery.argtypes=[w.HANDLE]
        status=self.pdh.PdhOpenQueryW(None,0,c.byref(self.q))
        if status:raise OSError(status,'PdhOpenQuery')
        for key,field in [('dedicated_bytes','Dedicated Usage'),('shared_gpu_ram_bytes','Shared Usage')]:
            h=w.HANDLE();status=self.pdh.PdhAddEnglishCounterW(self.q,'\\GPU Process Memory(*)\\'+field,0,c.byref(h))
            if status:self.errors.append({'counter':key,'status':hex(status&0xffffffff)})
            else:self.counters[key]=h
        self.pdh.PdhCollectQueryData(self.q)
    def array(self,h):
        needed=w.DWORD(0);count=w.DWORD(0)
        initial=self.pdh.PdhGetFormattedCounterArrayW(h,0x400,c.byref(needed),c.byref(count),None)&0xffffffff
        if initial not in (0,0x800007D2):return [],hex(initial)
        if not needed.value:return [],None
        buf=c.create_string_buffer(needed.value)
        rows=c.cast(buf,c.POINTER(ITEM))
        status=self.pdh.PdhGetFormattedCounterArrayW(h,0x400,c.byref(needed),c.byref(count),rows)
        if status:return [],hex(status&0xffffffff)
        out={}
        for i in range(count.value):
            name=rows[i].szName
            if name and re.match(r'^pid_'+str(self.pid)+r'_',name) and rows[i].FmtValue.CStatus in (0,1):
                out[name]=int(rows[i].FmtValue.largeValue)
        return [{'instance':n,'bytes':v} for n,v in sorted(out.items())],None
    def sample(self):
        p=PMC();p.cb=c.sizeof(p)
        if not self.ps.GetProcessMemoryInfo(self.handle,c.byref(p),p.cb):raise OSError(c.get_last_error(),'GetProcessMemoryInfo')
        create=w.FILETIME();exit=w.FILETIME();kernel=w.FILETIME();user=w.FILETIME()
        self.k.GetProcessTimes(self.handle,c.byref(create),c.byref(exit),c.byref(kernel),c.byref(user))
        ticks=lambda f:(f.dwHighDateTime<<32)|f.dwLowDateTime
        mem=MEMSTAT();mem.dwLength=c.sizeof(mem);self.k.GlobalMemoryStatusEx(c.byref(mem))
        row={'time_ns':time.time_ns(),'perf_counter':time.perf_counter(),'working_set_bytes':int(p.WorkingSetSize),'private_commit_bytes':int(p.PrivateUsage),'lifetime_peak_working_set_bytes':int(p.PeakWorkingSetSize),'process_cpu_seconds':(ticks(kernel)+ticks(user))/1e7,'system_ram_total_bytes':int(mem.ullTotalPhys),'system_ram_available_bytes':int(mem.ullAvailPhys)}
        collect=self.pdh.PdhCollectQueryData(self.q)
        row['gpu_counter_errors']=list(self.errors)
        if collect:row['gpu_counter_errors'].append({'counter':'collect','status':hex(collect&0xffffffff)})
        for key,h in self.counters.items():
            values,error=self.array(h)
            row[key]=sum(v['bytes'] for v in values) if values else None
            row[key+'_instances']=values
            if error:row['gpu_counter_errors'].append({'counter':key,'status':error})
        row['gpu_process_counter_observed']=bool(row.get('dedicated_bytes_instances'))
        return row
    def close(self):
        self.pdh.PdhCloseQuery(self.q);self.k.CloseHandle(self.handle)
if __name__=='__main__':
    import sys
    q=Probe(int(sys.argv[1]))
    try:
        time.sleep(.2);print(json.dumps(q.sample(),ensure_ascii=True))
    finally:q.close()
