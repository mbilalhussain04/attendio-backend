from math import sin, cos, sqrt, atan2, pi


def distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000
    d_lat = (lat2 - lat1) * pi / 180
    d_lon = (lon2 - lon1) * pi / 180
    a = sin(d_lat / 2) ** 2 + cos(lat1 * pi / 180) * cos(lat2 * pi / 180) * sin(d_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return r * c
