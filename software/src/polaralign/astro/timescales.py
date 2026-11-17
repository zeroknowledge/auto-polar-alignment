"""Time scales: just enough for precession, nutation and local sidereal time.

Precession moves the pole by 20"/yr, so the date only needs to be right to about a month for
a 2" effect.  Refraction needs the local sidereal time to a few minutes (it only sets the
*direction* of a ~2' displacement).  UT1-UTC (< 0.9 s) and the equation of the equinoxes
(< 1.2 s of time) are therefore ignored: both are below 20" of sidereal angle.
"""
from __future__ import annotations

from datetime import datetime, timezone

JD_J2000 = 2451545.0
# TT - UTC = 32.184 s + TAI-UTC; TAI-UTC = 37 s since 2017-01-01 (no leap second since).
TT_MINUS_UTC_S = 69.184


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def julian_date_utc(dt: datetime) -> float:
    """Julian date of a UTC datetime (valid 1901-2099, Meeus ch. 7 Gregorian algorithm)."""
    dt = as_utc(dt)
    y, m = dt.year, dt.month
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    day_frac = (dt.hour + (dt.minute + (dt.second + dt.microsecond * 1e-6) / 60.0) / 60.0) / 24.0
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + dt.day + day_frac + b - 1524.5


def centuries_tt(dt: datetime) -> float:
    jd_tt = julian_date_utc(dt) + TT_MINUS_UTC_S / 86400.0
    return (jd_tt - JD_J2000) / 36525.0


def gmst_deg(dt: datetime) -> float:
    """Greenwich mean sidereal time in degrees (UT1 taken as UTC; Meeus eq. 12.4)."""
    jd = julian_date_utc(dt)
    t = (jd - JD_J2000) / 36525.0
    g = (280.46061837 + 360.98564736629 * (jd - JD_J2000)
         + 0.000387933 * t * t - t ** 3 / 38710000.0)
    return g % 360.0


def local_sidereal_deg(dt: datetime, longitude_deg: float) -> float:
    return (gmst_deg(dt) + longitude_deg) % 360.0


def decimal_year(dt: datetime) -> float:
    dt = as_utc(dt)
    start = datetime(dt.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
    return dt.year + (dt - start).total_seconds() / (end - start).total_seconds()
