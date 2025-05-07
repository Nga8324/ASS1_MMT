import json
from logger import log_error, log_info
def parse_server_response_list_channel(response):
    try:
        # Tách các đối tượng JSON nếu có nhiều hơn một
        responses = response.split('}{')
        if len(responses) > 1:
            responses = [responses[0] + '}', '{' + responses[1]]
        return json.loads(responses[0])  # Giải mã JSON đầu tiên
    except json.JSONDecodeError as e:
        log_error(f"Failed to decode JSON response: {e}")
        return {"status": "error", "message": "Invalid JSON response from server"}
def parse_server_response_multi(response_str):
    responses = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(response_str):
        try:
            obj, offset = decoder.raw_decode(response_str[idx:])
            responses.append(obj)
            idx += offset
            # Bỏ qua ký tự thừa như \n, khoảng trắng
            while idx < len(response_str) and response_str[idx] in ['\n', '\r', ' ']:
                idx += 1
        except json.JSONDecodeError as e:
            print(f"JSON Decode Error: {e}")
            break
    return responses

#---------------------ui----------------------
