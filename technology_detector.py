"""Conservative public website technology signature detection."""

import re


DETECTOR_VERSION = "1.0.0"
TECHNOLOGY_PATTERNS = {
    "WordPress": (r"(?:/wp-content/|/wp-includes/|/wp-json(?:/|\b))", 0.95),
    "Elementor": (r"(?:/elementor(?:-pro)?/|\belementorFrontend\b)", 0.95),
    "Gravity Forms": (r"(?:/gravityforms/|\bgforms_[a-z0-9_]+)", 0.95),
    "FuneralTech": (r"(?:client-data\.funeraltechweb\.com|website powered by\s+FuneralTech)", 0.98),
    "CFS Funeral Home Websites": (r"funeral home website by\s+CFS\s*&(?:amp;)?\s*TA", 0.9),
    "Google Tag Manager": (r"(?:googletagmanager\.com/(?:gtm|ns)\.js|\bGTM-[A-Z0-9]+)", 0.95),
}


def detect_technology(html):
    """Return positive signatures only; absence is not a negative claim."""
    source = str(html or "")
    detected = {}
    for name, (pattern, confidence) in TECHNOLOGY_PATTERNS.items():
        match = re.search(pattern, source, re.I)
        if match:
            detected[name] = {
                "marker": match.group(0)[:120],
                "confidence": confidence,
                "detector_version": DETECTOR_VERSION,
            }
    return detected
