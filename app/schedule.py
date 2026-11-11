"""Turn 'times per day' + timing into clock times for dose alarms."""
_BASE = {1: ["09:00"], 2: ["09:00", "21:00"], 3: ["08:00", "14:00", "21:00"], 4: ["08:00", "12:00", "17:00", "21:00"]}

def dose_times(freq, timing=None):
    f = max(1, min(int(freq or 1), 4))
    times = list(_BASE[f])
    t = (timing or "").lower()
    if f == 1 and ("night" in t or "bed" in t): times = ["21:30"]
    if f == 1 and ("morning" in t or "empty stomach" in t): times = ["07:30"]
    return times
