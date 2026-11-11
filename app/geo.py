"""Distance maths. Distances are exact WGS-84 geodesic distances (geographiclib), not a haversine approximation,
so a provider is never counted as inside the radius because of a spherical-earth rounding error."""
import math
from geographiclib.geodesic import Geodesic

MAX_RADIUS_KM = 10.0
_WGS84 = Geodesic.WGS84

def valid_coord(lat, lon):
    """True only for finite, in-range coordinates. (0, 0) is rejected: it is the classic 'location missing' value."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lat) and math.isfinite(lon)): return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0): return False
    return not (lat == 0.0 and lon == 0.0)

def distance_km(lat1, lon1, lat2, lon2):
    return _WGS84.Inverse(lat1, lon1, lat2, lon2)["s12"] / 1000.0

def lat_band(lat, radius_km):
    """Latitude window that must contain every point within radius_km (a degree of latitude is never shorter than ~110.57 km).
    Used only to narrow the database query; the exact distance check always runs afterwards."""
    d = radius_km / 110.0
    return max(-90.0, lat - d), min(90.0, lat + d)

def point_at(lat, lon, bearing_deg, dist_km):
    """The point dist_km away along a bearing. Used by the demo seed and the tests."""
    r = _WGS84.Direct(lat, lon, bearing_deg, dist_km * 1000.0)
    lon2 = ((r["lon2"] + 180.0) % 360.0) - 180.0
    return r["lat2"], lon2
