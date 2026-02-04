"""
Utility functions for handling property IDs
"""
import re

def normalize_id(id_str: str) -> str:
    """
    Normalize property ID by stripping prefixes and converting to standard format.
    Examples: 
    - "stand-Erf-001" -> "1"
    - "Erf-001" -> "1"
    - "001" -> "1"
    - "1" -> "1"
    """
    if not id_str:
        return ""
        
    # Convert to string and lower case
    s = str(id_str).strip().lower()
    
    # Extract just the numeric part if possible
    # This regex looks for digits at the end of the string
    match = re.search(r'(\d+)$', s)
    if match:
        # Return the number without leading zeros
        return str(int(match.group(1)))
        
    return s

def ids_match(id1: str, id2: str) -> bool:
    """
    Check if two IDs represent the same property.
    Uses normalization to compare.
    """
    return normalize_id(id1) == normalize_id(id2)
