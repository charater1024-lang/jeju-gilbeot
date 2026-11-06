"""Use the same directed road legs for the schedule and its reference map."""
import math
import sqlite3

from .engine import _travel
from . import roads


ROAD_BASIS = 'osm_road_distance'
STRAIGHT_BASIS = 'adjusted_straight_line'


def _car_road_leg(distance):
    return math.ceil(distance / 35 * 60), math.ceil(distance * 250), distance


def road_search_legs(root, req, points, stay_minutes):
    """Find alternative car legs when the coordinate-based draft cannot be used."""
    travel_minutes = req['end_minute'] - req['start_minute'] - stay_minutes
    if travel_minutes < 0:
        return {}
    max_km = min(travel_minutes / 60 * 35, req['budget_krw'] / 250)
    try:
        distances = roads.road_distance_matrix(root, points, max_km)
    except (OSError, ValueError, sqlite3.Error):
        return {}
    return {leg: _car_road_leg(distance) for leg, distance in distances.items()}


def estimate_itinerary(root, req, destination_ids, points):
    """Check the shortlisted order with one bounded road search per leg."""
    mode = req['transport']
    origin, destination = points[0], points[-1]
    geometry = None
    if mode == 'car' or req.get('include_geometry', True):
        try:
            if destination_ids:
                geometry = roads.route_geometry(root, {
                    'destination_ids': destination_ids, 'transport': mode,
                    'origin': {'latitude': origin[0], 'longitude': origin[1]},
                    'destination': {'latitude': destination[0], 'longitude': destination[1]},
                })
            else:
                geometry = roads.direct_route_geometry(root, origin, destination, mode)
        except (OSError, ValueError, sqlite3.Error):
            # Give a coarse planning estimate when the offline map cannot be read.
            pass

    speed, cost_per_km = (35, 250) if mode == 'car' else (4, 0)
    road_distances = geometry.get('leg_distances_km') if geometry else None
    road_ready = (mode == 'car' and geometry is not None and geometry.get('kind') == 'road'
                  and isinstance(road_distances, list) and len(road_distances) == len(points) - 1
                  and all(type(distance) in (int, float) and math.isfinite(distance) and distance >= 0
                          for distance in road_distances))
    estimate = {'basis': ROAD_BASIS if road_ready else STRAIGHT_BASIS,
                'speed_kmh': speed, 'cost_per_km_krw': cost_per_km, 'live': False}
    if road_ready:
        legs = [_car_road_leg(distance) for distance in road_distances]
    else:
        if geometry and geometry.get('kind') == 'road':
            # Never attach a road map whose distances cannot support the schedule.
            geometry = None
        legs = [_travel(a, b, mode) for a, b in zip(points, points[1:])]
        estimate['distance_factor'] = 1.35 if mode == 'car' else 1.2
        if mode == 'car':
            estimate['fallback_reason'] = geometry.get('road_status', 'road_path_unavailable') if geometry else 'road_data_unavailable'
    estimate['distance_km'] = round(sum(leg[2] for leg in legs), 3)
    return legs, estimate, geometry


def constraint_check(req, legs, stay_minutes=0):
    arrival = req['start_minute'] + stay_minutes + sum(leg[0] for leg in legs)
    cost = sum(leg[1] for leg in legs)
    deadline_margin = req['end_minute'] - arrival
    budget_margin = req['budget_krw'] - cost
    return {'end_arrival_minute': arrival, 'travel_cost_krw': cost,
            'deadline_margin_minutes': deadline_margin, 'budget_margin_krw': budget_margin,
            'within_deadline': deadline_margin >= 0, 'within_budget': budget_margin >= 0}


def itinerary_totals(req, legs, estimate, check, stop_count):
    back_minutes, back_cost, back_distance = legs[-1]
    return {'stops': stop_count, 'duration_minutes': check['end_arrival_minute'] - req['start_minute'],
            'end_arrival_minute': check['end_arrival_minute'], 'travel_minutes': sum(leg[0] for leg in legs),
            'travel_distance_km': estimate['distance_km'], 'travel_basis': estimate['basis'],
            'visit_cost_krw': None, 'travel_cost_krw': check['travel_cost_krw'],
            'cost_krw': check['travel_cost_krw'], 'return_travel_minutes': back_minutes,
            'return_travel_cost_krw': back_cost, 'return_travel_km': round(back_distance, 3),
            'deadline_margin_minutes': check['deadline_margin_minutes'], 'budget_margin_krw': check['budget_margin_krw'],
            'budget_verified': False, 'price_unknown_count': stop_count}


def estimate_note(estimate):
    if estimate['basis'] == ROAD_BASIS:
        return '지도에 표시한 OSM 자동차 도로 거리와 시속 35km, 1km당 250원 가정으로 시간·이동비를 다시 계산했습니다. 지도 점선의 입구 연결 구간과 실시간 교통은 반영하지 않았습니다.'
    if 'fallback_reason' in estimate:
        return '도로 연결 거리를 확인하지 못해 직선거리에 1.35를 곱하고 시속 35km, 1km당 250원을 적용했습니다. 표시한 여유는 이 가정에서 계산한 값입니다.'
    return '도보는 직선거리에 1.2를 곱하고 시속 4km를 적용한 계획용 추정입니다. 실제 보행 경로와 제한은 방문 전에 확인해 주세요.'
