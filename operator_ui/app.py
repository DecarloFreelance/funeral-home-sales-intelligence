# [PASTE THE FULL app.py WITH THE fix_data_file function here]
# Instead of pasting the whole thing, let's just fix the specific function

# Add debug version of api_provinces
@app.route('/api/provinces_debug')
def api_provinces_debug():
    """Debug version of provinces API."""
    import json
    from pathlib import Path
    
    # Log all paths checked
    paths_checked = []
    possible_paths = [
        Path(app.config['DATA_ROOT']) / 'ui_data_streamlined.json',
        Path('data/ui_data_streamlined.json'),
        Path('ui_data_streamlined.json'),
    ]
    
    result = {
        'paths_checked': [],
        'found_path': None,
        'exists': False,
        'data': None,
        'error': None
    }
    
    for path in possible_paths:
        paths_checked.append(str(path.absolute()))
        if path.exists():
            result['found_path'] = str(path.absolute())
            result['exists'] = True
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                result['data'] = {
                    'keys': list(data.keys()),
                    'stats_keys': list(data.get('stats', {}).keys()),
                    'province_count': len(data.get('stats', {}).get('provinces', [])),
                    'nt': data.get('stats', {}).get('province_counts', {}).get('NT', 0),
                    'nu': data.get('stats', {}).get('province_counts', {}).get('NU', 0),
                }
            except Exception as e:
                result['error'] = str(e)
            break
    
    result['paths_checked'] = paths_checked
    return jsonify(result)
    @app.route('/api/provinces_debug')
    def api_provinces_debug():
        """Debug version of provinces API."""
        import json
        from pathlib import Path
        
        paths_checked = []
        possible_paths = [
            Path(app.config['DATA_ROOT']) / 'ui_data_streamlined.json',
            Path('data/ui_data_streamlined.json'),
            Path('ui_data_streamlined.json'),
            Path('/app/data/ui_data_streamlined.json'),
        ]
        
        result = {
            'paths_checked': [],
            'found_path': None,
            'exists': False,
            'data': None,
            'error': None
        }
        
        for path in possible_paths:
            path_str = str(path.absolute())
            paths_checked.append(path_str)
            if path.exists():
                result['found_path'] = path_str
                result['exists'] = True
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                    result['data'] = {
                        'keys': list(data.keys()),
                        'stats_keys': list(data.get('stats', {}).keys()),
                        'province_count': len(data.get('stats', {}).get('provinces', [])),
                        'nt': data.get('stats', {}).get('province_counts', {}).get('NT', 0),
                        'nu': data.get('stats', {}).get('province_counts', {}).get('NU', 0),
                    }
                except Exception as e:
                    result['error'] = str(e)
                break
        
        result['paths_checked'] = paths_checked
        return jsonify(result)

