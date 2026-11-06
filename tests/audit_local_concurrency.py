"""Run a bounded local load audit in an isolated, owned server process."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPResponse
import json
from pathlib import Path
from statistics import median
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler, Request


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = dict(start_lat=33.506, start_lon=126.492, end_lat=33.506, end_lon=126.492,
              origin_confirmed=True, origin_source='landmark', origin_label='제주공항')
DAY = dict(ORIGIN, date='2026-11-06', transport='car', start_minute=540,
           end_minute=1080, budget_krw=100000, max_stops=3)
ROUTE_IDS = ['osm_tourism_way_1563942072', 'osm_tourism_node_538148519']
WORKLOAD = (
    ('health', '/api/operational-check', None, lambda data: data['models_ready'] is True),
    ('1048', '/api/observed-reference?audience=resident&month=6', None, lambda data: bool(data['categories'])),
    ('1047', '/api/data-guide?kind=dining&month=6', None, lambda data: len(data['rows']) > 0),
    ('guide', '/api/guide-search', {'query': '성산일출봉'}, lambda data: data[0]['name'] == '성산일출봉'),
    ('places', '/api/tourism', {'limit': 6, 'region': 'all'}, lambda data: len(data['items']) == 6),
    ('manual', '/api/plan-destinations', dict(DAY, destination_ids=ROUTE_IDS),
     lambda data: data['status'] == 'ok' and {stop['poi_id'] for stop in data['stops']} == set(ROUTE_IDS)),
    ('auto', '/api/agent/plan', dict(DAY, query='', region='north'),
     lambda data: data['status'] == 'ok' and 1 <= len(data['stops']) <= 3),
)


def request(port, case, timeout=25):
    name, path, body, verify = case
    start = time.perf_counter()
    try:
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        req = Request(f'http://127.0.0.1:{port}{path}', data=payload,
                      headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        opener = build_opener(ProxyHandler({}))
        with opener.open(req, timeout=timeout) as response:
            status = response.status
            data = json.load(response)
        result = 'ok' if verify(data) else 'invalid result'
    except HTTPError as error:
        status, result = error.code, f'HTTP {error.code}'
        error.close()
    except (URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as error:
        status, result = None, type(error).__name__
    return {'name': name, 'result': result, 'http_status': status,
            'ms': round((time.perf_counter() - start) * 1000, 1)}


def batch(port, workers):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(lambda case: request(port, case), WORKLOAD * 6))
    failures = [item for item in outcomes if item['result'] != 'ok']
    times = sorted(item['ms'] for item in outcomes)
    return {'workers': workers, 'requests': len(outcomes),
            'outcomes': Counter(item['result'] for item in outcomes),
            'p50_ms': median(times), 'p95_ms': times[(95 * len(times) + 99) // 100 - 1],
            'max_ms': max(times), 'failures': failures}


def probe_with_partial_bodies(port, clients):
    sockets = []
    try:
        for _ in range(clients):
            conn = socket.create_connection(('127.0.0.1', port), timeout=2)
            sockets.append(conn)
            conn.sendall(b'POST /api/tourism HTTP/1.1\r\nHost: localhost\r\n'
                         b'Content-Type: application/json\r\nContent-Length: 64\r\n\r\n{')
        # Wait briefly so these local sockets occupy the handlers before probing.
        time.sleep(0.25)
        return request(port, WORKLOAD[0], timeout=1.5)
    finally:
        for conn in sockets:
            conn.close()


def probe_with_unread_downloads(port):
    sockets = []
    try:
        for _ in range(8):
            conn = socket.socket()
            sockets.append(conn)
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
            conn.settimeout(2)
            conn.connect(('127.0.0.1', port))
            conn.sendall(b'GET /api/offline-roads HTTP/1.1\r\nHost: localhost\r\n\r\n')
        time.sleep(0.25)
        return request(port, WORKLOAD[0], timeout=1.5)
    finally:
        for conn in sockets:
            conn.close()


def verify_incomplete_body_timeout(port):
    with socket.create_connection(('127.0.0.1', port), timeout=7) as conn:
        conn.sendall(b'POST /api/tourism HTTP/1.1\r\nHost: localhost\r\n'
                     b'Content-Type: application/json\r\nContent-Length: 64\r\n\r\n{')
        response = HTTPResponse(conn)
        try:
            response.begin()
            return response.status
        finally:
            response.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8892)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port == 8765:
        parser.error('Choose a separate local test port, excluding 8765.')
    with socket.socket() as reservation:
        if sys.platform == 'win32':
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            reservation.bind(('127.0.0.1', args.port))
        except OSError:
            parser.error('Test port cannot be reserved.')

    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    with subprocess.Popen([sys.executable, '-B', 'dev.py', 'run', '--port', str(args.port)],
                          cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          creationflags=flags) as process:
        try:
            for _ in range(30):
                if process.poll() is not None:
                    raise RuntimeError('Isolated test server exited before becoming ready.')
                if request(args.port, WORKLOAD[0], timeout=1)['result'] == 'ok':
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError('Isolated test server did not respond.')
            warmup = [request(args.port, case) for case in WORKLOAD]
            if any(item['result'] != 'ok' for item in warmup):
                raise RuntimeError(f'Invalid warmup responses: {warmup}')
            results = [batch(args.port, workers) for workers in (1, 8, 16, 32)]
            partial = {clients: probe_with_partial_bodies(args.port, clients) for clients in (1, 8)}
            unread = probe_with_unread_downloads(args.port)
            timed_out = verify_incomplete_body_timeout(args.port)
            recovered = request(args.port, WORKLOAD[0], timeout=5)
            print(json.dumps({'batches': results, 'partial_body_health': partial,
                              'unread_download_health': unread, 'incomplete_body_status': timed_out,
                              'health_after_close': recovered}, ensure_ascii=False, indent=2))
            return int(any(item['failures'] for item in results)
                       or any(item['result'] != 'ok' for item in partial.values())
                       or unread['result'] != 'ok' or timed_out != 408 or recovered['result'] != 'ok')
        finally:
            process.terminate()
            process.wait(timeout=5)


if __name__ == '__main__':
    sys.exit(main())
