from __future__ import annotations

from .models import VerticalProfile

PROFILES = (
    VerticalProfile(
        "funeral_home",
        "Funeral Home",
        "phase14-v1",
        ("funeral homes", "funeral director", "mortuary"),
        ("about", "team", "staff", "people", "funeral director", "locations", "contact", "history"),
        ("funeral director", "director", "owner", "manager", "administrator"),
        ("obituary", "memorial", "tribute", "testimonial", "vendor", "supplier", "social"),
        ("ownership_type", "parent_organization", "founded_year", "languages_offered", "service_offering", "service_area", "technology_signal"),
    ),
    VerticalProfile(
        "cemetery",
        "Cemetery and Memorial Park",
        "phase14-v1",
        ("cemeteries", "burial ground", "memorial park"),
        ("cemetery", "memorial park", "burial", "interment", "mausoleum", "columbarium", "grounds"),
        ("owner", "operator", "manager", "administrator", "cemetery director", "grounds manager", "registrar"),
        ("obituary", "tribute", "testimonial", "vendor", "supplier", "social"),
        (),
    ),
)

_BY_KEY = {profile.key: profile for profile in PROFILES}


def list_profiles() -> list[VerticalProfile]:
    return sorted(PROFILES, key=lambda profile: profile.key)


def get_profile(key: str) -> VerticalProfile:
    try:
        return _BY_KEY[key]
    except KeyError as exc:
        raise ValueError(f"Unknown vertical: {key}") from exc
