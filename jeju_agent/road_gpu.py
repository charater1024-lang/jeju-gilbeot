"""Optional OpenCL batch for the road graph's nearest-node scan (Windows)."""
from array import array
from contextlib import ExitStack
import ctypes as ct
import logging
import math
from threading import Lock, Thread
import weakref


BLOCK_SIZE = 64
MAX_LOCATIONS = 10  # Eight stops and two optional endpoints.
MAX_SCANS = MAX_LOCATIONS * 25  # One workgroup per nonempty cell and location.
# Haversine values closer than this are resolved on the CPU with the original
# (distance, node ID) comparison. This margin exceeds double rounding error
# over the local cell extents and also catches exact ties.
TIE_MARGIN = 1e-14
LOGGER = logging.getLogger(__name__)

GPU_DEVICE = 4
DEVICE_DOUBLE_FP_CONFIG = 0x1032
MEM_WRITE_ONLY = 2
MEM_READ_ONLY = 4
MEM_COPY_HOST_PTR = 32

SOURCE = rb"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable

__kernel void closest_in_cells(__global const double *nodes,
                               __global const double *locations,
                               __global const int *scans,
                               __global double *results) {
    int scan = get_group_id(0);
    int thread = get_local_id(0);
    int start = scans[3 * scan];
    int stop = scans[3 * scan + 1];
    int location = scans[3 * scan + 2];
    double latitude = locations[3 * location];
    double longitude = locations[3 * location + 1];
    double cos_latitude = locations[3 * location + 2];
    __local double distances[64];
    __local double runners_up[64];
    __local int winners[64];
    double best = INFINITY;
    double second = INFINITY;
    int winner = -1;
    for (int index = start + thread; index < stop; index += 64) {
        double lat_half = sin((nodes[3 * index] - latitude) * 0.5);
        double lon_half = sin((nodes[3 * index + 1] - longitude) * 0.5);
        double distance = lat_half * lat_half +
            cos_latitude * nodes[3 * index + 2] * lon_half * lon_half;
        if (distance < best) {
            second = best;
            best = distance;
            winner = index;
        } else {
            second = fmin(second, distance);
        }
    }
    distances[thread] = best;
    runners_up[thread] = second;
    winners[thread] = winner;
    barrier(CLK_LOCAL_MEM_FENCE);
    for (int width = 32; width > 0; width >>= 1) {
        if (thread < width) {
            int other = thread + width;
            if (distances[other] < distances[thread]) {
                runners_up[thread] = fmin(distances[thread], runners_up[other]);
                distances[thread] = distances[other];
                winners[thread] = winners[other];
            } else {
                runners_up[thread] = fmin(runners_up[thread], distances[other]);
            }
        }
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (thread == 0) {
        results[3 * scan] = (double)winners[0];
        results[3 * scan + 1] = distances[0];
        results[3 * scan + 2] = runners_up[0];
    }
}
"""


class OpenCLError(RuntimeError):
    pass


handle = ct.c_void_p
uint = ct.c_uint32
flags = ct.c_uint64
size = ct.c_size_t
integer = ct.c_int32


def _check(operation, status):
    if status:
        raise OpenCLError(f'{operation} returned OpenCL status {status}')


def _buffer(value):
    return (ct.c_char * (len(value) * value.itemsize)).from_buffer(value)


def _xyz(point):
    lat, lon = map(math.radians, point)
    return lat, lon, math.cos(lat)


class RoadGPU:
    def __init__(self, points, cells):
        # Use the system OpenCL loader provided with the display driver.
        self.library = ct.WinDLL('OpenCL.dll', winmode=0x800)
        self.lock = Lock()
        self.clear_locations = (ct.c_char * (MAX_LOCATIONS * 24))()
        self.nodes = []
        self.ranges = {}
        packed = array('d')
        for cell, ids in cells.items():
            start = len(self.nodes)
            self.nodes.extend(ids)
            self.ranges[cell] = (start, len(self.nodes))
            for node in ids:
                packed.extend(_xyz(points[node]))

        gpu = self._device()
        status = integer()
        with ExitStack() as resources:
            context = self._bind('clCreateContext', handle, handle, uint, ct.POINTER(handle),
                                 handle, handle, ct.POINTER(integer))(None, 1, ct.byref(gpu), None, None, ct.byref(status))
            _check('clCreateContext', status.value)
            resources.callback(self._bind('clReleaseContext', integer, handle), context)
            self.queue = self._bind('clCreateCommandQueue', handle, handle, handle, flags,
                                    ct.POINTER(integer))(context, gpu, 0, ct.byref(status))
            _check('clCreateCommandQueue', status.value)
            resources.callback(self._bind('clReleaseCommandQueue', integer, handle), self.queue)
            source = ct.c_char_p(SOURCE)
            program = self._bind('clCreateProgramWithSource', handle, handle, uint, ct.POINTER(ct.c_char_p),
                                 ct.POINTER(size), ct.POINTER(integer))(context, 1, ct.byref(source), None, ct.byref(status))
            _check('clCreateProgramWithSource', status.value)
            resources.callback(self._bind('clReleaseProgram', integer, handle), program)
            build = self._bind('clBuildProgram', integer, handle, uint, ct.POINTER(handle), ct.c_char_p, handle, handle)
            _check('clBuildProgram', build(program, 1, ct.byref(gpu), b'-cl-std=CL1.2', None, None))
            self.kernel = self._bind('clCreateKernel', handle, handle, ct.c_char_p,
                                     ct.POINTER(integer))(program, b'closest_in_cells', ct.byref(status))
            _check('clCreateKernel', status.value)
            resources.callback(self._bind('clReleaseKernel', integer, handle), self.kernel)
            create = self._bind('clCreateBuffer', handle, handle, flags, size, handle, ct.POINTER(integer))
            release = self._bind('clReleaseMemObject', integer, handle)
            set_arg = self._bind('clSetKernelArg', integer, handle, uint, size, handle)
            inputs = ((MEM_READ_ONLY | MEM_COPY_HOST_PTR, len(packed)*packed.itemsize, _buffer(packed)),
                      (MEM_READ_ONLY, MAX_LOCATIONS*24, None), (MEM_READ_ONLY, MAX_SCANS*12, None),
                      (MEM_WRITE_ONLY, MAX_SCANS*24, None))
            buffers = []
            for index, (mode, length, data) in enumerate(inputs):
                mem = handle(create(context, mode, length, data, ct.byref(status)))
                _check('clCreateBuffer', status.value)
                resources.callback(release, mem)
                _check('clSetKernelArg', set_arg(self.kernel, index, ct.sizeof(mem), ct.byref(mem)))
                buffers.append(mem)
            _, self.location_buffer, self.scan_buffer, self.output_buffer = buffers
            transfer_args = (handle, handle, uint, size, size, handle, uint, handle, handle)
            self.write = self._bind('clEnqueueWriteBuffer', integer, *transfer_args)
            self.read = self._bind('clEnqueueReadBuffer', integer, *transfer_args)
            self.fill = self._bind('clEnqueueFillBuffer', integer, handle, handle, handle,
                                   size, size, size, uint, handle, handle)
            self.run = self._bind('clEnqueueNDRangeKernel', integer, handle, handle, uint, ct.POINTER(size),
                                  ct.POINTER(size), ct.POINTER(size), uint, handle, handle)
            self.release = weakref.finalize(self, resources.pop_all().close)

    def _bind(self, name, result, *params):
        function = getattr(self.library, name)
        function.restype = result
        function.argtypes = params
        return function

    def _device(self):
        platforms = self._bind('clGetPlatformIDs', integer, uint, ct.POINTER(handle), ct.POINTER(uint))
        devices = self._bind('clGetDeviceIDs', integer, handle, flags, uint, ct.POINTER(handle), ct.POINTER(uint))
        info = self._bind('clGetDeviceInfo', integer, handle, uint, size, handle, ct.POINTER(size))
        count = uint()
        _check('clGetPlatformIDs', platforms(0, None, ct.byref(count)))
        found = (handle * count.value)()
        _check('clGetPlatformIDs', platforms(count, found, None))
        for platform in found:
            if devices(platform, GPU_DEVICE, 0, None, ct.byref(count)) != 0:
                continue
            candidates = (handle * count.value)()
            _check('clGetDeviceIDs', devices(platform, GPU_DEVICE, count, candidates, None))
            for device in candidates:
                double_config = flags()
                if info(device, DEVICE_DOUBLE_FP_CONFIG, ct.sizeof(double_config), ct.byref(double_config), None) == 0 and double_config.value:
                    return handle(device)
        raise OpenCLError('No OpenCL GPU with double precision support')

    def close(self):
        self.release()

    def _scan(self, locations):
        if not 1 <= len(locations) <= MAX_LOCATIONS:
            raise ValueError('Road GPU location count is out of range')
        coords = array('d', (component for point in locations for component in _xyz(point)))
        groups = array('i')
        for index, (lat, lon) in enumerate(locations):
            row, col = math.floor(lat*100), math.floor(lon*100)
            for r in range(row-2, row+3):
                for c in range(col-2, col+3):
                    bounds = self.ranges.get((r, c))
                    if bounds:
                        groups.extend((*bounds, index))
        output = array('d', [0.0]) * len(groups)
        if not groups:
            return groups, output
        try:
            for buffer, values in ((self.location_buffer, coords), (self.scan_buffer, groups)):
                host = _buffer(values)
                _check('clEnqueueWriteBuffer', self.write(self.queue, buffer, 1, 0, len(host), host, 0, None, None))
            global_size = size(len(groups)//3*BLOCK_SIZE)
            local_size = size(BLOCK_SIZE)
            _check('clEnqueueNDRangeKernel', self.run(self.queue, self.kernel, 1, None, ct.byref(global_size),
                                                      ct.byref(local_size), 0, None, None))
            host = _buffer(output)
            _check('clEnqueueReadBuffer', self.read(self.queue, self.output_buffer, 1, 0, len(host), host, 0, None, None))
        finally:
            # Clear request-derived scratch data before another request can use the queue.
            zero = uint()
            try:
                for buffer, length in ((self.scan_buffer, len(groups) * groups.itemsize),
                                       (self.output_buffer, len(output) * output.itemsize)):
                    _check('clEnqueueFillBuffer', self.fill(self.queue, buffer, ct.byref(zero),
                                                            ct.sizeof(zero), 0, length, 0, None, None))
            finally:
                clear = self.clear_locations
                _check('clEnqueueWriteBuffer', self.write(self.queue, self.location_buffer, 1, 0,
                                                          len(clear), clear, 0, None, None))
        return groups, output

    def nearest(self, locations, points, distance_km):
        if not self.lock.acquire(blocking=False):
            return None
        try:
            groups, output = self._scan(locations)
        finally:
            self.lock.release()
        best = [(math.inf, None) for _ in locations]
        for offset in range(0, len(groups), 3):
            start, stop, location = groups[offset:offset+3]
            index, first, second = output[offset:offset+3]
            if not start <= index < stop or not math.isfinite(first) or not first <= second or index != int(index):
                raise OpenCLError('OpenCL returned an invalid nearest-node candidate')
            # Near ties in a cell use the original full CPU scan for that cell.
            indices = range(start, stop) if second-first <= TIE_MARGIN else (int(index),)
            point = locations[location]
            candidate = min((distance_km(point, points[self.nodes[i]]), self.nodes[i]) for i in indices)
            best[location] = min(best[location], candidate)
        return [(node if distance <= 1.5 else None, distance if node is not None else None)
                for distance, node in best]


class OptionalRoadGPU:
    """Initialize once per graph and keep CPU requests independent of the driver."""

    def __init__(self):
        self.lock = Lock()
        self.attempted = False
        self.gpu = None

    def prepare(self, points, cells):
        with self.lock:
            if self.attempted:
                return
            self.attempted = True
        try:
            Thread(target=self._prepare, args=(points, cells), name='jeju-road-opencl', daemon=True).start()
        except RuntimeError as exc:
            LOGGER.warning('Optional road GPU worker did not start: %s', exc)

    def _prepare(self, points, cells):
        try:
            gpu = RoadGPU(points, cells)
        except (AttributeError, OSError, OpenCLError, ValueError, MemoryError, ct.ArgumentError) as exc:
            LOGGER.warning('Optional road GPU unavailable. Using CPU: %s', exc)
            return
        with self.lock:
            self.gpu = gpu

    def nearest(self, locations, points, distance_km):
        with self.lock:
            gpu = self.gpu
        if gpu is None:
            return None
        try:
            return gpu.nearest(locations, points, distance_km)
        except (OSError, OpenCLError, ValueError, MemoryError, ct.ArgumentError) as exc:
            with self.lock:
                self.gpu = None
            LOGGER.warning('Optional road GPU disabled. Using CPU: %s', exc)
            return None
