"""Dated calendar inputs and offline inference for the 561 calendar experiment.

This frozen feature table covers the 2022-10 through 2025-10 study only.
"""

from datetime import date, timedelta
from functools import lru_cache
from math import cos, isfinite, log1p, pi, sin


ANNUAL = {
    2022: ("2021-08-11", "1003 1009 1010 1225"),
    2023: ("2022-06-13", "0101 0121 0122 0123 0124 0301 0505 0527 0606 0815 0928 0929 0930 1003 1009 1225"),
    2024: ("2023-06-22", "0101 0209 0210 0211 0212 0301 0410 0505 0506 0515 0606 0815 0916 0917 0918 1003 1009 1225"),
    2025: ("2024-06-20", "0101 0128 0129 0130 0301 0303 0505 0506 0606 0815 1003 1005 1006 1007 1008 1009 1225"),
}
SPECIAL = {
    "2023-05-29": "2023-05-02",
    "2023-10-02": "2023-09-05",
    "2024-10-01": "2024-09-03",
    "2025-01-27": "2025-01-14",
    "2025-06-03": "2025-04-08",
}
SOURCES = {
    "2022": "https://www.kasi.re.kr/kor/publication/post/newsMaterial/28806",
    "2023": "https://www.kasi.re.kr/kor/publication/post/newsMaterial/29168",
    "2024": "https://www.korea.kr/news/policyNewsView.do?newsId=148916689",
    "2025": "https://www.kasi.re.kr/publication/post/newsMaterial/30071",
    "2023-05-29": "https://www.korea.kr/news/policyNewsView.do?newsId=148914528",
    "2023-10-02": "https://www.korea.kr/news/policyNewsView.do?newsId=148919798",
    "2024-10-01": "https://www.korea.kr/news/policyNewsView.do?newsId=148933400",
    "2025-01-27": "https://www.korea.kr/briefing/pressReleaseView.do?newsId=156670135",
    "2025-06-03": "https://www.korea.kr/news/policyNewsView.do?newsId=148941443",
}


def is_holiday(day, as_of):
    stamp = day.isoformat()
    published, values = ANNUAL.get(day.year, ("9999-12-31", ""))
    standard = published <= as_of and day.strftime("%m%d") in values.split()
    announced = SPECIAL.get(stamp)
    special = announced is not None and announced <= as_of
    return int(standard or special)


@lru_cache(maxsize=16384)
def calendar_vector(day, as_of, holidays):
    weekday = day.weekday()
    phase = 2 * pi * (day.timetuple().tm_yday - 1) / 365.25
    harmonic = [sin(phase), cos(phase), sin(2 * phase), cos(2 * phase)]
    result = [int(weekday == i) for i in range(7)] + harmonic
    result.extend(value * int(weekday >= 5) for value in harmonic)
    if holidays:
        yesterday, tomorrow = day - timedelta(1), day + timedelta(1)
        holiday = is_holiday(day, as_of)
        previous, following = is_holiday(yesterday, as_of), is_holiday(tomorrow, as_of)
        result.extend((holiday, previous, following, holiday * (weekday < 5)))
    return result


def tree_vector(day, as_of, features, group, holiday, stats):
    """Group ID is categorical, not a numeric distance or a road identifier."""
    weekday = day.weekday()
    median = stats["centers"][weekday]
    return [group, weekday, day.month, day.day, log1p(median), stats["scale"],
            stats["recent_ratio"], stats["weekday_ratio"],
            min(0., (day - date.fromisoformat(as_of)).days / 365.25),
            *features[7:15], *(features[15:] if holiday else ())]


def _tree_ratio(parameters, features):
    encoded = []
    for index in parameters["order"]:
        value = features[index]
        categories = parameters["categories"].get(str(index))
        encoded.append(value if categories is None else
                       categories.index(value) if value in categories else None)
    result = parameters["offset"]
    for tree in parameters["trees"]:
        index = 0
        while True:
            node = tree["nodes"][index]
            contribution, feature, threshold, missing_left, left, right, leaf, cat, bits = node
            if leaf:
                result += contribution
                break
            value = encoded[feature]
            if value is None:
                go_left = bool(missing_left)
            elif cat:
                category = int(value)
                masks = tree["bitsets"][bits]
                go_left = bool((masks[category // 32] >> (category % 32)) & 1)
            else:
                go_left = value <= threshold
            index = left if go_left else right
    return result


def predict_artifact(model, day, group, *, calendar_as_of=None):
    """Predict a historical calendar pattern using standard Python only.

    The fit date fixes learned trends. Explicit calendar_as_of lets callers
    use published holiday notices that arrived after the historical fit.
    """
    if isinstance(day, str):
        day = date.fromisoformat(day)
    stats = model["statistics"][group]
    config = model["config"]
    baseline = stats["centers"][day.weekday()]
    family = config["family"]
    if family == "weekday_scale":
        return baseline * config["factor"]
    features = calendar_vector(day, calendar_as_of or model["fit_end"], config["holiday"])
    parameters = model["parameters"]
    if family == "route_calendar_ridge":
        coefs = parameters["coefficients"][group]
        if len(features) != len(coefs):
            raise ValueError("Calendar parameter dimensions differ")
        relative = 1. + sum(x * c for x, c in zip(features, coefs))
    elif family == "calendar_hist_boosting":
        group_id = model["groups"][group] if len(model["groups"]) <= 255 else 0
        features = tree_vector(day, model["fit_end"], features, group_id, config["holiday"], stats)
        relative = _tree_ratio(parameters, features)
    else:
        raise ValueError("Unsupported calendar model family")
    value = baseline * (1. - config["blend"] + config["blend"] * max(0., relative))
    if not isfinite(value) or value < 0.:
        raise ValueError("Invalid ridership estimate")
    return value
