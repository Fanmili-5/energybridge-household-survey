"""Bind declared weather provenance to actual annual EPW bytes and time coverage."""
import csv
import datetime as dt
import math

from .pipeline import sha


def inspect_weather(path, source):
    required = ('provider', 'url', 'dataset', 'release', 'sha256')
    if any(not source.get(k) for k in required):
        raise ValueError('WEATHER_REGISTRATION: provider,url,dataset,release,sha256 required')
    actual = sha(path)
    if actual != source['sha256']:
        raise ValueError('WEATHER_IDENTITY: registered SHA-256 differs from selected EPW')
    with path.open(newline='') as stream:
        rows = [[field.strip() for field in row] for row in csv.reader(stream)]
    if len(rows) < 8 or len(rows[0]) < 10 or rows[0][0] != 'LOCATION':
        raise ValueError('WEATHER_HEADER: invalid LOCATION')
    location = dict(zip(('city', 'region', 'country', 'data_source', 'station'), rows[0][1:6]))
    for key, text, low, high in zip(('latitude', 'longitude', 'utc_offset'), rows[0][6:9],
                                    (-90, -180, -12), (90, 180, 12)):
        value = float(text)
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError('WEATHER_HEADER: invalid ' + key)
        location[key] = value
    if source.get('station') and source['station'] != location['station']:
        raise ValueError('WEATHER_IDENTITY: registered station differs from LOCATION')
    if len(rows[7]) < 3 or rows[7][0] != 'DATA PERIODS' or rows[7][1:3] != ['1', '1']:
        raise ValueError('WEATHER_PROFILE: one annual period with hourly records required')
    data = rows[8:]
    if len(data) not in (8760, 8784):
        raise ValueError('WEATHER_COVERAGE: complete8760/8784hour year required')
    # Pinned official TMY3 uses0; EPW dictionary convention uses60.
    minutes = {int(row[4]) for row in data if len(row) >= 5}
    if minutes not in ({0}, {60}):
        raise ValueError('WEATHER_PROFILE: consistent hourly minute labels0or60 required')
    year = 2000 if len(data) == 8784 else 2001
    start = dt.datetime(year, 1, 1)
    for i, row in enumerate(data):
        if len(row) < 35:
            raise ValueError('WEATHER_RECORD:35EPW fields required')
        date = start + dt.timedelta(hours=i)
        if [int(row[k]) for k in (1, 2, 3)] != [date.month, date.day, date.hour + 1]:
            raise ValueError('WEATHER_COVERAGE: missing/duplicate/out-of-order hour')
        value = float(row[6])
        if not math.isfinite(value) or not -70 < value < 70:
            raise ValueError('WEATHER_DRYBULB: missing or out-of-dictionary value')
    if sha(path) != actual:
        raise ValueError('WEATHER_IDENTITY: file changed during inspection')
    return {'sha256': actual, 'location': location, 'hours': len(data), 'hourly_minute_label': next(iter(minutes)),
            'checks': ['registered_bytes', 'LOCATION_bounds', 'hourly_annual_coverage', 'drybulb_dictionary_bounds'],
            'scope': 'identity,time coverage,drybulb;not full meteorological or solar-quality certification'}
