"""Declared stress and CPU-budget sensitivity; never a GTX1060 emulator."""
import ctypes as c,json,time
from ctypes import wintypes as w
from pathlib import Path
import load_benchmark as b
BASE=Path(__file__).resolve().parent
protocol={'scope':'Additional current-device tests; not center emulation','defined_ns':time.time_ns(),'steps':['max8stop route requests at1/4/8/16 outstanding','12logicalCPU affinity sensitivity, shortGPU and mixed at4/8/16','mixed eight outstanding2048requests','15seconds no requests withGPUstillresident'],'restrictions':'Only owned test service affinity changes, always restored; no system setting/model changes','fixed_gpu':'same RTX4090Laptop; this does not emulateGTX1060','memory_limits':'same6GiBWS/2GiBdedicated safety stops'}
(BASE/'results'/'extended_protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
for n in [1,4,8,16]:
    r=b.stage('route_stress',n,minimum=32,label_suffix='_max8stops')
    if not r['pass']:raise SystemExit('Route stress failed; review raw results')
k=c.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
k.GetProcessAffinityMask.argtypes=[w.HANDLE,c.POINTER(c.c_size_t),c.POINTER(c.c_size_t)]
k.SetProcessAffinityMask.argtypes=[w.HANDLE,c.c_size_t];k.CloseHandle.argtypes=[w.HANDLE]
h=k.OpenProcess(0x0400|0x0200,False,b.PID)
old=c.c_size_t();system=c.c_size_t()
if not h or not k.GetProcessAffinityMask(h,c.byref(old),c.byref(system)):raise OSError(c.get_last_error(),'affinity query')
bits=[i for i in range(8*c.sizeof(c.c_size_t)) if old.value&(1<<i)]
mask=sum(1<<i for i in bits[:12])
assert len(bits)>=12
affinity={'pid':b.PID,'original_mask':old.value,'limited_mask':mask,'logical_processors_selected':bits[:12],'not_center_cpu_emulation':True}
try:
    if not k.SetProcessAffinityMask(h,mask):raise OSError(c.get_last_error(),'affinity set')
    for kind in ['semantic_short','mixed']:
        for n in [4,8,16]:b.stage(kind,n,minimum=64,label_suffix='_12logical_budget')
finally:
    affinity['restored']=bool(k.SetProcessAffinityMask(h,old.value));k.CloseHandle(h)
    (BASE/'results'/'cpu_affinity_sensitivity.json').write_text(json.dumps(affinity,ensure_ascii=False,indent=2),encoding='utf-8')
assert affinity['restored']
b.stage('mixed',8,waves=256,label_suffix='_sustained2048')
before=b.status();monitor=b.Monitor('idle_after_all_load').start()
time.sleep(15)
measure=monitor.finish();after=b.status()
assert after['semantic']['gpu_ready'] and after['semantic']['gpu_resident']
out={'duration_seconds':15,'no_requests_during_window':True,'before':before,'after':after,'memory':measure}
(BASE/'results'/'idle_after_all_load.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'extended_complete':True,'idle_gpu_resident':True,'affinity_restored':True}),flush=True)
