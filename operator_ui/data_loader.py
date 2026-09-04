"""
Data loader with fallback paths for ui_data_streamlined.json.
"""
import json
import os
from pathlib import Path

def load_data():
    """Load data from multiple possible paths."""
    possible_paths = [
        Path('data/ui_data_streamlined.json'),
        Path('ui_data_streamlined.json'),
        Path(os.environ.get('PORTAL_FINDINGS_PATH', '')),
        Path('/opt/render/project/src/data/ui_data_streamlined.json'),
        Path('/app/data/ui_data_streamlined.json'),
    ]
    
    for path in possible_paths:
        if path and path.exists():
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception:
                continue
    
    return None
