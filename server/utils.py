import json
import re

# Hàm phân tích dữ liệu JSON
def parse_json(data):
    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON format: {e}"}

# Hàm kiểm tra định dạng IP hợp lệ
def validate_ip(ip):
    ip_pattern = re.compile(
        r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$"
    )  # Định dạng IPv4
    if ip_pattern.match(ip):
        parts = ip.split(".")
        if all(0 <= int(part) <= 255 for part in parts):
            return True
    return False
