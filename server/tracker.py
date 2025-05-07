import json
from utils import validate_ip, parse_json
from logger import log_info, log_error
# Danh sách các peer được theo dõi
peer_list = []

# Hàm điều hướng yêu cầu liên quan đến tracker
def handle_tracker_request(client_socket, data):
    if "submit_info" in data:
        submit_info(client_socket, data)
    elif "get_list" in data:
        get_list(client_socket)
    else:
        response = {"status": "error", "message": "Invalid tracker request"}
        client_socket.send(json.dumps(response).encode('utf-8'))
        print("[ERROR] Invalid tracker request")
    
# Hàm xử lý yêu cầu submit_info
def submit_info(client_socket, data):
    try:
        # Parse dữ liệu từ client
        request = parse_json(data)
        if "error" in request:
            raise ValueError(request["error"])

        peer_ip = request.get("ip")
        peer_port = request.get("port")

        if not peer_ip or not peer_port:
            raise ValueError("Missing IP or port in request")

        # Kiểm tra định dạng IP
        if not validate_ip(peer_ip):
            raise ValueError("Invalid IP format")

        # Thêm peer vào danh sách
        peer_info = {"ip": peer_ip, "port": peer_port}
        add_list(peer_info)

        response = {"status": "success", "message": "Peer added successfully"}
        client_socket.send(json.dumps(response).encode('utf-8'))
        log_info(f"Peer added: {peer_info}")
    except Exception as e:
        response = {"status": "error", "message": str(e)}
        client_socket.send(json.dumps(response).encode('utf-8'))
        log_error(f"Failed to add peer: {e}")
# Hàm thêm peer vào danh sách
def add_list(peer_info):
    global peer_list
    if peer_info not in peer_list:
        peer_list.append(peer_info)

# Hàm xử lý yêu cầu get_list
def get_list(client_socket):
    try:
        # Trả về danh sách các peer hiện tại
        response = {"status": "success", "peers": peer_list}
        client_socket.send(json.dumps(response).encode('utf-8'))
        print(f"[INFO] Sent peer list to client: {len(peer_list)} peers")
    except Exception as e:
        response = {"status": "error", "message": str(e)}
        client_socket.send(json.dumps(response).encode('utf-8'))
        print(f"[ERROR] Failed to send peer list: {e}")

