"""Use the matched JejuDataHub name without changing place identity or evidence."""


def prefer_hub_name(item):
    result = dict(item)
    if result.get('source_overlap_verified') is not True:
        return result
    evidence = result.get('cross_source')
    if not isinstance(evidence, dict):
        return result
    hub = evidence.get('hub')
    name = hub.get('name') if isinstance(hub, dict) else None
    if not isinstance(name, str) or not name.strip():
        return result
    mapped = evidence.get('osm')
    map_name = mapped.get('name') if isinstance(mapped, dict) else None
    result['map_name'] = map_name if isinstance(map_name, str) and map_name.strip() else result.get('map_name', result.get('name', ''))
    result['name'] = name.strip()
    result['display_name_source'] = 'jejudatahub'
    return result
