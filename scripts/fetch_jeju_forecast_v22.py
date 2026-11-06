"""Read Open-Meteo's fixed-lead NOAA GFS forecast archive for a public Jeju point."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HOST = 'https://previous-runs-api.open-meteo.com/v1/forecast'
MODEL = 'gfs_seamless'
COORDINATES = (33.4996, 126.5312)
LEAD = 2
VARIABLES = ('temperature_2m', 'precipitation', 'wind_speed_10m')


def fetch(start, end):
    query = urlencode(dict(latitude=COORDINATES[0], longitude=COORDINATES[1], models=MODEL,
                           hourly=','.join(f'{v}_previous_day{LEAD}' for v in VARIABLES),
                           timezone='Asia/Seoul', start_date=start, end_date=end))
    url = HOST + '?' + query
    with urlopen(Request(url, headers={'User-Agent': 'JejuGilbeot/1.0 non-commercial research'}), timeout=35) as response:
        raw = response.read(4_000_000)
    payload = json.loads(raw)
    assert payload.get('utc_offset_seconds') == 32400
    times = payload['hourly']['time']
    expected = [(dt.date.fromisoformat(start)+dt.timedelta(days=day)).isoformat()+f'T{hour:02d}:00'
                for day in range((dt.date.fromisoformat(end)-dt.date.fromisoformat(start)).days+1) for hour in range(24)]
    assert times == expected
    keys = [f'{v}_previous_day{LEAD}' for v in VARIABLES]
    lengths = [len(payload['hourly'][key]) for key in keys]
    assert all(length == len(times) for length in lengths)
    return raw, url, {key: sum(v is not None for v in payload['hourly'][key]) for key in keys}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--start', required=True)
    p.add_argument('--end', required=True)
    args = p.parse_args()
    raw, url, nonmissing = fetch(args.start, args.end)
    args.output.write_bytes(raw)
    receipt = dict(url=url, retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), valid_hours=nonmissing,
                   source='NOAA GFS via Open-Meteo Previous Runs API, CC BY 4.0',
                   lead_hours=48, timezone='Asia/Seoul', scope='Jeju City public reference point')
    args.output.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2)+'\n', 'utf-8')
    print(json.dumps(receipt, ensure_ascii=False))
