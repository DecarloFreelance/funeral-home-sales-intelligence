"""Canadian province and territory mapping and normalization."""

from typing import Dict, Optional, Set, Tuple, List
import re


# Complete list of Canadian provinces and territories
CANADIAN_PROVINCES = {
    'AB': 'Alberta',
    'BC': 'British Columbia',
    'MB': 'Manitoba',
    'NB': 'New Brunswick',
    'NL': 'Newfoundland and Labrador',
    'NS': 'Nova Scotia',
    'NT': 'Northwest Territories',
    'NU': 'Nunavut',
    'ON': 'Ontario',
    'PE': 'Prince Edward Island',
    'QC': 'Quebec',
    'SK': 'Saskatchewan',
    'YT': 'Yukon'
}

# Province code variations
PROVINCE_VARIATIONS = {
    'AB': ['AB', 'Alberta', 'Alta.', 'ALTA'],
    'BC': ['BC', 'British Columbia', 'B.C.', 'BC'],
    'MB': ['MB', 'Manitoba', 'Man.', 'MAN'],
    'NB': ['NB', 'New Brunswick', 'N.B.', 'NB'],
    'NL': ['NL', 'Newfoundland', 'Newfoundland and Labrador', 'Nfld.', 'N.L.', 'LABRADOR'],
    'NS': ['NS', 'Nova Scotia', 'N.S.', 'NS'],
    'NT': ['NT', 'Northwest Territories', 'N.W.T.', 'NWT', 'NW Territories'],
    'NU': ['NU', 'Nunavut', 'NU'],
    'ON': ['ON', 'Ontario', 'Ont.', 'ONT'],
    'PE': ['PE', 'Prince Edward Island', 'P.E.I.', 'PEI', 'PE'],
    'QC': ['QC', 'Quebec', 'Québec', 'PQ', 'P.Q.', 'QC'],
    'SK': ['SK', 'Saskatchewan', 'Sask.', 'SASK'],
    'YT': ['YT', 'Yukon', 'Yukon Territory', 'Y.T.', 'YT']
}

# Reverse mapping for fast lookup
PROVINCE_LOOKUP: Dict[str, str] = {}
for code, variations in PROVINCE_VARIATIONS.items():
    for var in variations:
        PROVINCE_LOOKUP[var.upper()] = code


def normalize_province(value: str) -> Optional[str]:
    """
    Normalize a province/territory string to its 2-letter code.
    
    Args:
        value: Province name, code, or variation
        
    Returns:
        2-letter province code or None if not found
    """
    if not value:
        return None
    
    # Clean up the value
    cleaned = re.sub(r'[^A-Za-z0-9.\'\- ]', ' ', str(value))
    cleaned = ' '.join(cleaned.split()).strip().upper()
    
    # Direct lookup
    if cleaned in PROVINCE_LOOKUP:
        return PROVINCE_LOOKUP[cleaned]
    
    # Try partial match for multi-word names
    for code, name in CANADIAN_PROVINCES.items():
        if name.upper() in cleaned:
            return code
    
    # Try to extract 2-letter code from text
    if len(cleaned) == 2 and cleaned in CANADIAN_PROVINCES:
        return cleaned
    
    return None


def extract_province_from_address(address: str) -> Optional[str]:
    """
    Extract province code from an address string.
    
    Args:
        address: Address string containing province
        
    Returns:
        2-letter province code or None
    """
    if not address:
        return None
    
    # Common patterns: city, PROV or city PROV
    # Look for 2-letter codes at the end of lines or after commas
    patterns = [
        r',\s*([A-Z]{2})\s*(?:\d|$)',  # ", AB" or ", AB "
        r'\s([A-Z]{2})\s*(?:\d|$)',     # " AB" or " AB "
        r',\s*([A-Za-z\.]+)\s*(?:\d|$)',  # ", Alberta" or ", Alta."
        r'\s([A-Za-z\.]+)\s*(?:\d|$)',     # " Alberta" or " Alta."
    ]
    
    for pattern in patterns:
        match = re.search(pattern, address.upper())
        if match:
            province_str = match.group(1).strip()
            normalized = normalize_province(province_str)
            if normalized:
                return normalized
    
    # If no pattern matches, try to find any province code in the text
    for code in CANADIAN_PROVINCES.keys():
        if code in address.upper():
            return code
    
    return None


def get_province_name(code: str) -> Optional[str]:
    """Get the full province name from its code."""
    return CANADIAN_PROVINCES.get(code.upper())


def get_all_provinces() -> List[str]:
    """Get list of all province codes."""
    return sorted(CANADIAN_PROVINCES.keys())


def get_province_variations(code: str) -> List[str]:
    """Get variations for a province code."""
    return PROVINCE_VARIATIONS.get(code.upper(), [])


def is_valid_province(code: str) -> bool:
    """Check if a province code is valid."""
    return code.upper() in CANADIAN_PROVINCES


def extract_province_from_record(record: Dict) -> Optional[str]:
    """
    Extract province from a record dictionary.
    Tries multiple fields and normalizes the result.
    """
    # Try common field names
    fields_to_check = ['province', 'state', 'region', 'territory', 'location', 'address', 'city']
    
    for field in fields_to_check:
        if field in record and record[field]:
            # If it's a dict, try nested fields
            if isinstance(record[field], dict):
                for nested in ['province', 'state', 'region']:
                    if nested in record[field] and record[field][nested]:
                        normalized = normalize_province(record[field][nested])
                        if normalized:
                            return normalized
            else:
                normalized = normalize_province(str(record[field]))
                if normalized:
                    return normalized
    
    # Check for province in address strings
    for field in ['address', 'location']:
        if field in record and isinstance(record[field], str):
            extracted = extract_province_from_address(record[field])
            if extracted:
                return extracted
    
    return None
