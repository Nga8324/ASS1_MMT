import socket
import threading
import sys
import json
import os
import datetime
from tracker import handle_tracker_request
# Import channel_manager to access constants/functions if needed for startup checks
from channel_manager import (
    handle_channel_request, CHANNELS_FILE,
    save_channels as save_channels_external,
    save_message, save_system_message # Thêm save_system_message
)
from utils import parse_json
from logger import log_info, log_error
from shared import channel_users, user_status, user_roles, connected_clients # Import user_roles

# Use dictionaries to map sockets to user info
# user_roles is already in shared.py, we'll use that directly.
# user_channel is deprecated by connected_clients

# Đường dẫn file lưu thông tin người dùng
USER_DATA_FILE = "server/users.json"

# --- Server Initialization ---
def start_server(host="0.0.0.0", port=5000):
    global user_status, channel_users, connected_clients, user_roles
    # Clear in-memory state on start
    user_status.clear()
    user_roles.clear()
    connected_clients.clear()
    channel_users.clear() # Clear channel user lists too

    # Ensure essential files exist
    ensure_data_files_exist()

    # Refresh user status from users.json (mark all as offline initially)
    refresh_all_users_offline() # Changed function name for clarity

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Allow address reuse
    try:
        server_socket.bind((host, port))
        server_socket.listen(5)
        log_info(f"Server started on {host}:{port}")

        while True:
            client_socket, address = server_socket.accept()
            log_info(f"New connection attempt from {address}")
            # Start thread to handle the client connection lifecycle
            threading.Thread(target=handle_client, args=(client_socket, address), daemon=True).start()
    except OSError as e:
        log_error(f"Server failed to start on {host}:{port}. Error: {e}. Is the port already in use?")
    except KeyboardInterrupt:
        log_info("KeyboardInterrupt received.")
    finally:
        shutdown_server(server_socket)

def ensure_data_files_exist():
    """Creates default user and channel files if they don't exist."""
    # Ensure users.json exists
    if not os.path.exists(USER_DATA_FILE):
         log_info(f"{USER_DATA_FILE} not found. Creating default.")
         os.makedirs(os.path.dirname(USER_DATA_FILE), exist_ok=True)
         save_users({"users": []}) # Save empty user list

    # Ensure channels.json exists
    if not os.path.exists(CHANNELS_FILE):
         log_info(f"{CHANNELS_FILE} not found. Creating default.")
         os.makedirs(os.path.dirname(CHANNELS_FILE), exist_ok=True)
         # Use the imported save_channels function from channel_manager
         save_channels_external({"channels": {}})

def refresh_all_users_offline():
    """Loads users from file and sets their initial RAM status to offline."""
    global user_status
    users_data = load_users()
    for user in users_data.get("users", []):
        username = user.get("username")
        if username:
            user_status[username] = "offline" # Mark everyone offline in RAM initially
            # user_roles[username] = "authenticated" # Assume users in file are authenticated
    log_info(f"Initialized RAM user statuses from file (all set to offline).")


# --- Client Connection Handling ---
def handle_client(client_socket, address):
    """Manages a single client connection, processing incoming requests."""
    addr_str = f"{address[0]}:{address[1]}" # For logging
    log_info(f"Handling connection from {addr_str}")
    try:
        while True:
            try:
                data = client_socket.recv(4096) # Increased buffer size
                if not data:
                    log_info(f"Connection closed gracefully by {addr_str}")
                    break # Exit loop if client disconnected

                data_str = data.decode('utf-8', errors='ignore')
                log_info(f"Received raw data from {addr_str}: {data_str[:200]}...") # Log truncated data

                # Handle potentially multiple JSON objects concatenated by client/network issues
                requests = []
                decoder = json.JSONDecoder()
                pos = 0
                while pos < len(data_str):
                    # Skip leading whitespace/newlines
                    while pos < len(data_str) and data_str[pos].isspace():
                        pos += 1
                    if pos == len(data_str): break # End of data

                    try:
                        req, json_len = decoder.raw_decode(data_str[pos:])
                        if isinstance(req, dict):
                            requests.append(req)
                        else:
                            log_error(f"Received non-dict JSON from {addr_str}: {req}")
                        pos += json_len
                    except json.JSONDecodeError as e:
                        log_error(f"Invalid JSON segment from {addr_str} at pos {pos}: {e}. Data: '{data_str[pos:pos+50]}...'")
                        # Attempt to recover or break? Break for now.
                        break # Stop processing this chunk on error

                if not requests:
                    log_warning(f"No valid JSON request found in data from {addr_str}. Data: {data_str}")
                    # Optionally send an error response if this is unexpected
                    # send_error_response(client_socket, "Invalid request format", addr_str)
                    continue # Skip to next recv

                # Process each valid request found in the buffer
                for request in requests:
                    route_request(client_socket, request) # Route each request

            except ConnectionResetError:
                log_info(f"Connection reset by {addr_str}")
                break # Exit loop
            except socket.timeout:
                 log_warning(f"Socket timeout for {addr_str}. Connection might be unstable.")
                 # Continue listening or break? Continue for now.
                 continue
            except Exception as loop_e: # Catch errors within the loop
                 log_error(f"Error processing data from {addr_str}: {loop_e}", exc_info=True)
                 # Maybe send an error response to the client if possible
                 send_error_response(client_socket, "Internal server error processing request", addr_str)
                 # Decide whether to continue or break the loop on error
                 # continue # Try to continue processing further requests

    except Exception as outer_e: # Catch errors outside the loop (e.g., initial recv)
        log_error(f"Unhandled error in handle_client for {addr_str}: {outer_e}", exc_info=True)
    finally:
        # --- Cleanup on Disconnection ---
        log_info(f"Cleaning up connection for {addr_str}")
        # Use the socket to find the username for disconnection cleanup
        username_to_disconnect = connected_clients.get(client_socket)
        if username_to_disconnect:
            handle_client_disconnection(client_socket, username_to_disconnect)
        else:
             log_info(f"Socket from {addr_str} disconnected (was not authenticated or already cleaned up).")

        # Remove from connected_clients map regardless
        connected_clients.pop(client_socket, None)

        try:
             client_socket.close()
             log_info(f"Closed socket for {addr_str}")
        except Exception as close_e:
             log_error(f"Error closing socket for {addr_str}: {close_e}")

# --- Request Routing ---
def route_request(client_socket, data):
    """Routes incoming request data to the appropriate handler based on 'type'."""
    global connected_clients, user_roles # Ensure user_roles is accessible
    addr_info = client_socket.getpeername() if client_socket and client_socket.fileno() != -1 else "Unknown Address"
    try:
        log_debug(f"Routing data from {addr_info}: {data}") # Use debug level if too verbose
        request_type = data.get("type")

        # Get authenticated user based on the socket connection
        authenticated_user = connected_clients.get(client_socket)
        user_role = user_roles.get(authenticated_user) # Get user role (None if not found)

        # --- Authentication Check for most requests ---
        # Most request types require an authenticated user (can be 'guest' or 'authenticated')
        if request_type != "auth" and not authenticated_user:
             log_warning(f"Unauthorized request type '{request_type}' from unauthenticated socket {addr_info}. Data: {data}")
             send_error_response(client_socket, "Authentication required", addr_info)
             return # Stop processing

        # --- Route based on type ---
        if request_type == "auth":
            handle_auth_request(client_socket, data) # Auth handles its own logic and responses

        elif request_type == "tracker":
            # Tracker might have its own auth or be public? Assuming public for now.
            response = handle_tracker_request(client_socket, data)
            # Tracker handler should send its own response if needed

        elif request_type == "channel":
            # Add authentication context before passing to channel manager
            data["_authenticated_user"] = authenticated_user
            data["_user_role"] = user_role # Pass role as well
            # Channel manager functions now handle sending their own responses
            handle_channel_request(client_socket, data)

        elif request_type == "get_user_status":
            # Get user list for a specific channel
            channel_name = data.get("channel")
            if not channel_name:
                 send_error_response(client_socket, "Channel name required for get_user_status", addr_info)
                 return

            # Get users for the specific channel from RAM
            channel_data = channel_users.get(channel_name, {})
            all_online = list(set(channel_data.get("online", []))) # Ensure unique
            all_offline = list(set(channel_data.get("offline", []))) # Ensure unique

            # --- MODIFICATION START: Filter out guests based on role ---
            filtered_online = [user for user in all_online if user_roles.get(user) != "guest"]
            filtered_offline = [user for user in all_offline if user_roles.get(user) != "guest"]
            # --- MODIFICATION END ---

            response = {
                "status": "success",
                "online": filtered_online, # Send filtered list
                "offline": filtered_offline # Send filtered list
            }
            send_response_helper(client_socket, response, addr_info) # Use helper
            log_info(f"Sent user status for '{channel_name}' to {authenticated_user or addr_info}: Online({len(filtered_online)}), Offline({len(filtered_offline)}) (Guests excluded)")
        elif request_type == "livestream":
                handle_livestream_request(client_socket, data)
        else:
            log_error(f"Invalid request type '{request_type}' from {authenticated_user or addr_info}. Data: {data}")
            send_error_response(client_socket, f"Invalid request type: {request_type}", addr_info)

    except Exception as e:
        log_error(f"Error routing request from {addr_info}: {e}", exc_info=True)
        send_error_response(client_socket, "Internal server error during request routing", addr_info)

# --- Authentication Logic ---

def handle_auth_request(client_socket, data):
    """Handles login, registration, guest login, and status updates."""
    global connected_clients, user_roles, user_status # Need to modify globals
    addr_info = client_socket.getpeername() if client_socket and client_socket.fileno() != -1 else "Unknown Address"
    response = None # Initialize response
    try:
        action = data.get("action")

        if action == "login":
            username = data.get("username")
            password = data.get("password")
            if authenticate_user(username, password): # This now also updates file status to online
                response = {"status": "success", "message": f"Welcome back, {username}!", "role": "authenticated"}
                # Update RAM state
                user_status[username] = "online"
                user_roles[username] = "authenticated"
                connected_clients[client_socket] = username # Map socket to username AFTER successful auth
                log_info(f"User '{username}' authenticated successfully from {addr_info}.")
                # Update user's presence in relevant channel lists (call helper)
                update_user_channel_presence(username, "online")
            else:
                response = {"status": "error", "message": "Invalid username or password"}
                log_warning(f"Failed login attempt for username '{username}' from {addr_info}.")

        elif action == "register":
            username = data.get("username")
            password = data.get("password")
            response = register_user(username, password) # Returns success/error dict
            # No automatic login or socket mapping after registration

        elif action == "visitor_login":
            visitor_name = data.get("visitor_name")
            if visitor_name:
                # Create a distinct guest username (e.g., prefix)
                guest_username = f"{visitor_name}" # Consider making this more robust
                # Check if guest_username conflicts? For now, allow.
                response = {"status": "success", "message": f"Welcome, {guest_username}!", "role": "guest"}
                # Update RAM state for guest
                user_status[guest_username] = "online" # Guests are online when connected
                user_roles[guest_username] = "guest" # GÁN VAI TRÒ GUEST
                log_info(f"Assigned role '{user_roles.get(guest_username)}' to user '{guest_username}'.") # THÊM LOG KIỂM TRA
                connected_clients[client_socket] = guest_username # Map socket to guest username
                log_info(f"User '{guest_username}' connected as guest from {addr_info}.")
                # Update guest's presence in relevant channel lists (call helper)
                update_user_channel_presence(guest_username, "online")
            else:
                response = {"status": "error", "message": "Visitor name is required"}

        elif action == "update_status":
             username_to_update = data.get("username")
             new_status = data.get("status")
             # Security: Verify the request comes from the correct authenticated user's socket
             authenticated_user = connected_clients.get(client_socket)

             if not authenticated_user:
                 response = {"status": "error", "message": "Authentication required to update status"}
                 log_warning(f"Unauthenticated status update attempt from {addr_info} for '{username_to_update}'.")
             elif authenticated_user != username_to_update:
                 response = {"status": "error", "message": "Authentication mismatch for status update"}
                 log_error(f"Status update mismatch: Socket {addr_info} (Auth: {authenticated_user}) tried to update status for '{username_to_update}'")
             elif user_roles.get(authenticated_user) == "guest":
                  response = {"status": "error", "message": "Guests cannot change status"}
                  log_warning(f"Guest '{authenticated_user}' attempted to change status from {addr_info}.")
             elif new_status not in {"online", "offline", "invisible"}:
                 response = {"status": "error", "message": f"Invalid status value: {new_status}"}
             else:
                 # Call the function to change status in RAM, file, and channel lists
                 response = change_user_status(username_to_update, new_status)
                 log_info(f"User '{username_to_update}' requested status change to '{new_status}'. Response: {response}")
        else:
            response = {"status": "error", "message": f"Invalid auth action: {action}"}

        # Send response if one was generated
        if response:
            send_response_helper(client_socket, response, addr_info)

    except Exception as e:
        log_error(f"Error handling auth request for {addr_info}: {e}", exc_info=True)
        send_error_response(client_socket, "Internal server error during authentication", addr_info)

# --- User Data Persistence ---
def load_users():
    """Loads user data from the JSON file."""
    try:
        # Ensure file exists before reading
        if not os.path.exists(USER_DATA_FILE):
             log_warning(f"{USER_DATA_FILE} not found during load. Returning empty.")
             return {"users": []}
        with open(USER_DATA_FILE, "r") as f:
            try:
                 users_data = json.load(f)
                 # Basic validation
                 if not isinstance(users_data, dict) or not isinstance(users_data.get("users"), list):
                      log_error(f"Invalid format in {USER_DATA_FILE}. Returning empty.")
                      return {"users": []}
                 return users_data
            except json.JSONDecodeError as e:
                 log_error(f"Error decoding JSON from {USER_DATA_FILE}: {e}. Returning empty.")
                 return {"users": []}
    except Exception as e:
        log_error(f"Unexpected error loading users from {USER_DATA_FILE}: {e}", exc_info=True)
        return {"users": []}

def save_users(users_data):
    """Saves user data to the JSON file."""
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(USER_DATA_FILE), exist_ok=True)
        with open(USER_DATA_FILE, "w") as file:
            json.dump(users_data, file, indent=4)
    except Exception as e:
        log_error(f"Error saving users to {USER_DATA_FILE}: {e}", exc_info=True)
        # Depending on severity, might want to raise the exception

def authenticate_user(username, password):
    """Checks credentials against users.json and updates status to 'online' in file on success."""
    if not username or not password: return False
    users_data = load_users()
    user_found = False
    for user in users_data.get("users", []):
        # !! IMPORTANT: In a real app, NEVER store plain passwords. Use hashing (e.g., bcrypt).
        if user.get("username") == username and user.get("password") == password:
            # Update status to 'online' in the structure before saving
            user["status"] = "online"
            user_found = True
            break

    if user_found:
        try:
            save_users(users_data) # Save the updated status to file
            return True
        except Exception as e:
            log_error(f"Failed to save user status to file during authentication for '{username}': {e}")
            # Decide if auth should still succeed. For now, yes.
            return True
    else:
        return False

def register_user(username, password):
    """Registers a new user, saving to users.json with 'offline' status."""
    if not username or not password:
        return {"status": "error", "message": "Username and password are required"}
    # Add more validation (length, characters, password complexity) here

    users_data = load_users()
    if not isinstance(users_data.get("users"), list):
         log_error(f"Correcting invalid 'users' list format in {USER_DATA_FILE} during registration.")
         users_data["users"] = []

    # Check if username already exists
    if any(user.get("username") == username for user in users_data["users"]):
        log_warning(f"Registration failed: Username '{username}' already exists.")
        return {"status": "error", "message": "Username already exists"}

    # Add new user (store hashed password in real app)
    users_data["users"].append({
        "username": username,
        "password": password, # HASH THIS PASSWORD
        "status": "offline"  # Initial status is offline
    })

    try:
        save_users(users_data)
        log_info(f"User '{username}' registered successfully.")
        return {"status": "success", "message": "User registered successfully"}
    except Exception as e:
        log_error(f"Failed to save new user '{username}' to file: {e}")
        # Consider cleanup if save fails?
        return {"status": "error", "message": "Failed to save user data during registration"}

# --- Status and Presence Management ---
def change_user_status(username, new_status):
    """Updates user status in RAM (user_status), file (users.json), and updates channel presence lists."""
    global user_status # Ensure access to global
    try:
        log_info(f"Attempting to change status for '{username}' to '{new_status}'...")
        previous_ram_status = user_status.get(username)

        # --- Update users.json ---
        users_data = load_users()
        user_found_in_file = False
        if isinstance(users_data.get("users"), list):
            for user in users_data["users"]:
                if user.get("username") == username:
                    user["status"] = new_status
                    user_found_in_file = True
                    break
        else:
             log_error(f"Invalid format in {USER_DATA_FILE} during status change for '{username}'.")

        if not user_found_in_file and user_roles.get(username) != "guest":
             log_warning(f"User '{username}' not found in {USER_DATA_FILE} during status change (might be guest or error).")
             # Proceed with RAM update but be aware of inconsistency

        if user_found_in_file or user_roles.get(username) != "guest": # Save if found or if not a guest
             try:
                 save_users(users_data)
                 log_info(f"Updated status for '{username}' to '{new_status}' in {USER_DATA_FILE}.")
             except Exception as e:
                 log_error(f"Failed to save status update for '{username}' to {USER_DATA_FILE}: {e}")
                 # Proceed with RAM update anyway? Yes.

        # --- Update RAM (user_status) ---
        user_status[username] = new_status
        log_info(f"Updated RAM status for '{username}' from '{previous_ram_status}' to '{new_status}'.")

        # --- Update RAM (channel_users presence) ---
        update_user_channel_presence(username, new_status)

        # --- Broadcast Status Change (Optional) ---
        # broadcast_status_update(username, new_status) # Implement if needed for real-time UI

        return {"status": "success", "message": f"Status changed to {new_status}"}

    except Exception as e:
        log_error(f"Error in change_user_status for '{username}': {e}", exc_info=True)
        return {"status": "error", "message": f"Internal server error changing status: {e}"}
def handle_livestream_request(client_socket, data):
    """Handles requests related to livestreaming (e.g., start notification)."""
    # Sửa: Thêm save_system_message vào global nếu cần (không cần vì đã import)
    global connected_clients, channel_users
    addr_info = client_socket.getpeername() if client_socket and client_socket.fileno() != -1 else "Unknown Address"
    action = data.get("action")
    streamer_username = connected_clients.get(client_socket) # Get username associated with this socket

    # --- Authentication Check ---
    if not streamer_username:
        log_warning(f"Unauthenticated livestream request '{action}' from {addr_info}.")
        send_error_response(client_socket, "Authentication required for livestream actions", addr_info)
        return
    # Optional: Check if guest users can stream
    # if user_roles.get(streamer_username) == "guest":
    #     log_warning(f"Guest user '{streamer_username}' attempted livestream action '{action}'.")
    #     send_error_response(client_socket, "Guests cannot perform livestream actions", addr_info)
    #     return

    if action == "start_livestream":
        channel_name = data.get("channel_name")
        p2p_port = data.get("port")

        if not channel_name or not p2p_port:
            log_error(f"Missing channel_name or port in start_livestream request from {streamer_username} ({addr_info}).")
            send_error_response(client_socket, "Missing channel_name or port for start_livestream", addr_info)
            return

        try:
            p2p_port = int(p2p_port) # Ensure port is an integer
            streamer_ip = addr_info[0] if isinstance(addr_info, tuple) else "unknown_ip" # Get IP from socket peername

            log_info(f"User '{streamer_username}' started livestream in channel '{channel_name}' on {streamer_ip}:{p2p_port}.")

            # --- Create Notification Content to Save ---
            # This is the core data stored in the channel's message history
            message_content_to_save = {
                "username": "System", # Or "Server", "Notification", etc.
                "message": "LIVESTREAM_START", # Special identifier for UI
                "streamer": streamer_username,
                "host": streamer_ip,
                "port": p2p_port,
                # "channel_name": channel_name, # Không cần lưu channel_name bên trong message
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
            }

            # --- Save Notification to Channel History ---
            # Gọi hàm save_system_message từ channel_manager
            if save_system_message(channel_name, message_content_to_save):
                log_info(f"Livestream start notification saved for channel '{channel_name}'.")
            else:
                # Log lỗi nhưng vẫn tiếp tục broadcast nếu có thể
                log_error(f"Failed to save livestream start notification for channel '{channel_name}'.")

            # --- Create Broadcast Message ---
            # This is the full message sent to clients in real-time
            broadcast_message = {
                "type": "channel", # Keep type as channel so client sync picks it up
                "action": "new_message", # Simulate a new message arrival
                "message_data": message_content_to_save # Embed the saved content
            }

            # --- Broadcast to Channel Members ---
            target_users = set()
            # Combine online and offline users of the channel, as anyone joined should get notified
            channel_data = channel_users.get(channel_name, {})
            target_users.update(channel_data.get("online", []))
            target_users.update(channel_data.get("offline", []))

            log_debug(f"Broadcasting livestream start from '{streamer_username}' in '{channel_name}' to users: {target_users}")

            # Iterate through all connected sockets
            for target_socket, target_username in connected_clients.items():
                # Check if the user is in the target channel AND is NOT the streamer themselves
                if target_username in target_users and target_username != streamer_username:
                    target_addr = target_socket.getpeername() if target_socket and target_socket.fileno() != -1 else "Unknown"
                    log_info(f"Sending livestream notification to {target_username} ({target_addr})")
                    # Gửi tin nhắn broadcast đã tạo
                    send_response_helper(target_socket, broadcast_message, target_addr)

            # Optionally send a confirmation back to the streamer?
            # send_response_helper(client_socket, {"status": "success", "message": "Livestream notification sent"}, addr_info)

        except ValueError:
            log_error(f"Invalid port number '{data.get('port')}' from {streamer_username} ({addr_info}).")
            send_error_response(client_socket, "Invalid port number provided", addr_info)
        except Exception as e:
            log_error(f"Error handling start_livestream from {streamer_username} ({addr_info}): {e}", exc_info=True)
            send_error_response(client_socket, "Internal server error handling start_livestream", addr_info)

    # Add elif blocks here for other livestream actions like "stop_livestream" if needed
    # elif action == "stop_livestream":
    #     # Handle stop notification and broadcast similarly
    #     # 1. Create message_content_to_save for stop event
    #     # 2. Call save_system_message
    #     # 3. Create broadcast_message
    #     # 4. Broadcast to relevant users
    #     pass

    else:
        log_error(f"Invalid livestream action '{action}' from {streamer_username} ({addr_info}).")
        send_error_response(client_socket, f"Invalid livestream action: {action}", addr_info)
def update_user_channel_presence(username, current_status):
    """Updates the online/offline lists in channel_users based on user's status."""
    global channel_users
    is_present_online = current_status == "online" # Only 'online' counts as present
    log_debug(f"Updating channel presence for '{username}' (Status: {current_status}, PresentOnline: {is_present_online})")

    for channel_name, channel_data in channel_users.items():
        online_list = channel_data.setdefault("online", [])
        offline_list = channel_data.setdefault("offline", [])

        # Remove from both lists first for clean transition
        was_online = False
        if username in online_list:
            online_list.remove(username)
            was_online = True

        was_offline = False
        if username in offline_list:
            offline_list.remove(username)
            was_offline = True

        # Add to the correct list based on new presence
        if is_present_online:
            if username not in online_list: # Avoid duplicates
                 online_list.append(username)
                 if not was_online: log_debug(f"'{username}' added to online list for '{channel_name}'.")
            # else: was already online, no change needed after removal/add
        else: # offline or invisible
            if username not in offline_list: # Avoid duplicates
                 offline_list.append(username)
                 if not was_offline: log_debug(f"'{username}' added to offline list for '{channel_name}'.")
            # else: was already offline, no change needed after removal/add

        # Log if presence state changed
        # if was_online != is_present_online:
        #      log_info(f"Presence updated for '{username}' in channel '{channel_name}': {'Online' if is_present_online else 'Offline'}")


def handle_client_disconnection(client_socket, username):
    """Handles cleanup when a known client disconnects."""
    # Sửa: Thêm global channel_users và user_status để sửa đổi trực tiếp
    global user_roles, channel_users, user_status
    addr_info = client_socket.getpeername() if client_socket and client_socket.fileno() != -1 else "Unknown Address"
    try:
        log_info(f"Handling disconnection for user '{username}' from {addr_info}...")

        # --- 1. Update status to 'offline' in users.json ---
        users_data = load_users()
        user_found_in_file = False
        if isinstance(users_data.get("users"), list):
            for user in users_data["users"]:
                if user.get("username") == username:
                    if user.get("status") != "offline": # Only save if status changes
                        user["status"] = "offline"
                        user_found_in_file = True
                        try:
                            save_users(users_data)
                            log_info(f"Updated status to 'offline' for '{username}' in {USER_DATA_FILE}.")
                        except Exception as e_save:
                            log_error(f"Failed to save offline status for disconnected user '{username}' to {USER_DATA_FILE}: {e_save}")
                    else:
                        user_found_in_file = True # Found, but already offline in file
                    break
        if not user_found_in_file and user_roles.get(username) != "guest":
             log_warning(f"Disconnected user '{username}' not found in {USER_DATA_FILE} (might be guest or error).")

        # --- 2. Remove user COMPLETELY from channel presence lists (RAM) ---
        log_info(f"Removing disconnected user '{username}' from all channel presence lists.")
        for channel_name, channel_data in channel_users.items():
            removed_online = False
            removed_offline = False
            if username in channel_data.get("online", []):
                channel_data["online"].remove(username)
                removed_online = True
            if username in channel_data.get("offline", []):
                channel_data["offline"].remove(username)
                removed_offline = True
            if removed_online or removed_offline:
                 log_debug(f"Removed '{username}' from presence lists for channel '{channel_name}'.")

        # --- 3. Update RAM status (user_status) ---
        # Vẫn cập nhật RAM status để phản ánh trạng thái logic cuối cùng
        if user_status.get(username) != "offline":
            user_status[username] = "offline"
            log_info(f"Set RAM status to 'offline' for disconnected user '{username}'.")

        # --- 4. Remove from other RAM mappings ---
        # connected_clients removal happens in handle_client finally block
        user_roles.pop(username, None) # Remove role mapping

        # --- Broadcast User List Update (Optional) ---
        # broadcast_user_list_update_for_user(username) # Implement if needed

        log_info(f"Finished handling disconnection for user '{username}'.")

    except Exception as e:
        log_error(f"Error in handle_client_disconnection for user '{username}': {e}", exc_info=True)

# --- Server Shutdown ---
def shutdown_server(server_socket):
    """Gracefully shuts down the server."""
    log_info("Initiating server shutdown...")
    # Set all connected users to offline before closing sockets
    for sock, user in list(connected_clients.items()):
         log_info(f"Marking user '{user}' as offline due to server shutdown.")
         # Use the change_user_status function for consistency
         change_user_status(user, "offline")
         try:
             # Optionally send a shutdown message
             # send_response_helper(sock, {"type":"system", "message":"Server shutting down"}, "Shutdown")
             sock.close()
         except Exception as e:
             log_error(f"Error closing client socket for '{user}' during shutdown: {e}")

    connected_clients.clear() # Clear the map
    user_roles.clear()
    user_status.clear()
    channel_users.clear()

    try:
        if server_socket:
            server_socket.close()
            log_info("Server socket closed.")
    except Exception as e:
        log_error(f"Error closing server socket: {e}")

    log_info("Server shutdown complete.")
    # Use os._exit(0) for a more immediate exit if threads might hang
    os._exit(0) # Force exit after cleanup

# --- Helper Functions ---
def send_response_helper(client_socket, response_data, addr_info=""):
    """Safely sends a JSON response with newline termination."""
    if not client_socket or client_socket.fileno() == -1:
        log_error(f"Attempted to send response on invalid socket ({addr_info}). Data: {response_data}")
        return
    try:
        if not isinstance(response_data, dict):
             log_error(f"Invalid response data type: {type(response_data)}. Data: {response_data}")
             response_data = {"status": "error", "message": "Internal server error: Invalid response format"}
        json_string = json.dumps(response_data) + "\n"
        client_socket.sendall(json_string.encode('utf-8'))
        # log_debug(f"Sent response to {addr_info}: {response_data}") # Use debug if too verbose
    except Exception as e:
        log_error(f"Failed to send response to {addr_info}: {e}. Data: {response_data}")

def send_error_response(client_socket, message, addr_info=""):
    """Sends a standardized error response."""
    send_response_helper(client_socket, {"status": "error", "message": message}, addr_info)

def log_warning(message):
    """Logs a warning message."""
    log_info(f"[WARNING] {message}") # Use log_info with prefix for now

def log_debug(message):
    """Logs a debug message (can be disabled later)."""
    # print(f"[DEBUG] {message}") # Simple print for debug
    log_info(f"[DEBUG] {message}") # Or use info level

# --- Main Execution ---
if __name__ == "__main__":
    start_server()