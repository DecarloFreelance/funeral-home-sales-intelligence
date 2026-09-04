"""
Clean diagnostic routes for debugging data file issues.
"""

import json
import os
from pathlib import Path
from flask import jsonify

def register_debug_routes(app):
    """Register debug routes with the Flask app."""
    
    @app.route('/api/diagnostic')
    def diagnostic():
        """Diagnostic endpoint to check file paths and data."""
        results = {
            'cwd': os.getcwd(),
            'environment': {
                'DATA_ROOT': str(app.config.get('DATA_ROOT', 'not set')),
                'PORTAL_FINDINGS_PATH': os.environ.get('PORTAL_FINDINGS_PATH', 'not set'),
            },
            'paths_checked': [],
            'file_exists': False,
            'found_path': None,
            'file_info': None,
            'error': None
        }
        
        # Check multiple possible paths
        possible_paths = [
            Path(app.config.get('DATA_ROOT', 'data')) / 'ui_data_streamlined.json',
            Path('data/ui_data_streamlined.json'),
            Path('ui_data_streamlined.json'),
            Path('/app/data/ui_data_streamlined.json'),
            Path('/opt/render/project/src/data/ui_data_streamlined.json'),
        ]
        
        for path in possible_paths:
            path_str = str(path.resolve())
            results['paths_checked'].append({
                'path': path_str,
                'exists': path.exists(),
                'is_file': path.is_file() if path.exists() else False
            })
            
            if path.exists() and path.is_file():
                results['file_exists'] = True
                results['found_path'] = path_str
                
                # Read and analyze the file
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                    
                    stats = data.get('stats', {})
                    provinces = stats.get('provinces', [])
                    
                    results['file_info'] = {
                        'size': path.stat().st_size,
                        'leads_count': len(data.get('leads', [])),
                        'province_count': len(provinces),
                        'province_codes': [p.get('code') for p in provinces],
                        'has_nt': 'NT' in [p.get('code') for p in provinces],
                        'has_nu': 'NU' in [p.get('code') for p in provinces],
                    }
                except json.JSONDecodeError as e:
                    results['error'] = f"JSON decode error: {e}"
                except Exception as e:
                    results['error'] = str(e)
                break
        
        return jsonify(results)
    
    @app.route('/api/check-data')
    def check_data():
        """Quick check if data has NT and NU."""
        try:
            from operator_ui.data_loader import load_data
            data = load_data()
            if not data:
                return jsonify({'error': 'No data loaded'}), 404
            
            stats = data.get('stats', {})
            provinces = [p.get('code') for p in stats.get('provinces', [])]
            
            return jsonify({
                'provinces': provinces,
                'has_nt': 'NT' in provinces,
                'has_nu': 'NU' in provinces,
                'total_leads': len(data.get('leads', []))
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/provinces')
    def api_provinces():
        """Serve list of provinces with lead counts."""
        try:
            from operator_ui.data_loader import load_data
            data = load_data()
            if not data:
                return jsonify({'error': 'Data file not found'}), 404
            
            stats = data.get('stats', {})
            province_counts = stats.get('province_counts', {})
            
            return jsonify({
                'success': True,
                'provinces': stats.get('provinces', []),
                'counts': province_counts
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
