"""CPU nearest-node search using conservative bounds on the existing road grid."""

import math
from operator import itemgetter


# This matches the range of validated origin and destination coordinates.
_LATITUDE = (32.9, 33.8)
_LONGITUDE = (126.0, 127.1)
# Keep a 10-micrometre margin for floating-point rounding in the lower bound.
_BOUND_MARGIN_KM = 1e-8


def build_cell_bounds(points, cells):
    """Build bounds once for the same immutable graph as points and cells."""
    bounds = {}
    for key, node_ids in cells.items():
        if not node_ids:
            continue
        latitudes, longitudes = zip(*(points[node_id] for node_id in node_ids))
        south, north = min(latitudes), max(latitudes)
        west, east = min(longitudes), max(longitudes)
        if not (
            _LATITUDE[0] <= south <= north <= _LATITUDE[1]
            and _LONGITUDE[0] <= west <= east <= _LONGITUDE[1]
        ):
            continue
        south, north, west, east = map(math.radians, (south, north, west, east))
        bounds[key] = (south, north, west, east, math.cos(north))
    return bounds


def nearest_bounded(point, points, cells, bounds, km):
    """Return the original grid search's node ID and Haversine distance in km."""
    latitude, longitude = point
    row, column = math.floor(latitude * 100), math.floor(longitude * 100)
    lat, lon = math.radians(latitude), math.radians(longitude)
    cos_lat = math.cos(lat)
    in_jeju = (
        _LATITUDE[0] <= latitude <= _LATITUDE[1]
        and _LONGITUDE[0] <= longitude <= _LONGITUDE[1]
    )

    candidates = []
    for r in range(row - 2, row + 3):
        for c in range(column - 2, column + 3):
            key = (r, c)
            node_ids = cells.get(key)
            if not node_ids:
                continue
            lower_km = 0.0
            cell_bounds = bounds.get(key) if in_jeju else None
            if cell_bounds is not None:
                south, north, west, east, min_cos = cell_bounds
                lat_gap = max(south - lat, lat - north, 0.0)
                lon_gap = max(west - lon, lon - east, 0.0)
                # Jeju's positive latitudes give cos(north) as the cell minimum.
                # Its small longitude span keeps sin(gap / 2) increasing.
                h = math.sin(lat_gap / 2) ** 2
                h += cos_lat * min_cos * math.sin(lon_gap / 2) ** 2
                lower_km = 12742 * math.asin(min(1, math.sqrt(h)))
            candidates.append((lower_km, node_ids))

    best = None
    for lower_km, node_ids in sorted(candidates, key=itemgetter(0)):
        if best is not None and lower_km > best[0] + _BOUND_MARGIN_KM:
            break
        cell_best = min((km(point, points[node_id]), node_id) for node_id in node_ids)
        if best is None or cell_best < best:
            best = cell_best

    if best is None:
        return None, None
    distance, node_id = best
    return (node_id, distance) if distance <= 1.5 else (None, distance)
