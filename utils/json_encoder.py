import json
from datetime import datetime, date

class CustomJsonEncoder(json.JSONEncoder):
    """
    Custom JSON encoder to handle datetime objects.
    """
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

def convert_to_json_serializable(data):
    """
    Recursively converts a dictionary to be JSON serializable,
    handling datetime objects.
    """
    if isinstance(data, dict):
        return {k: convert_to_json_serializable(v) for k, v in data.items()}
    if isinstance(data, list):
        return [convert_to_json_serializable(i) for i in data]
    if isinstance(data, (datetime, date)):
        return data.isoformat()
    return data
