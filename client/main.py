import socket
import json
import datetime
import os
import select
import threading
import time # Needed for robust receive
from logger import log_info, log_error, log_debug, log_warning
from peer import start_livestream, connect_to_peer, receive_stream

# Global variable for local message cache
local_channels = {} # Format: { "channel_name": {"messages": [...]}, ... }
LOCAL_CACHE_FILE = "client/client_cache.json" # Optional: for persistence

# --- Connection ---
def connect_to_server(host="127.0.0.1", port=5000):
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.settimeout(10)  # Set a timeout for connection attempt
        client_socket.connect((host, port))
        client_socket.settimeout(None) # Reset timeout after connection
        log_info(f"Connected to server at {host}:{port}")
        return client_socket
    except socket.timeout:
        log_error("Connection timed out. Please check the server and try again.")
        return None
    except Exception as e:
        log_error(f"Failed to connect to server: {e}")
        return None

# --- Local Cache ---
def load_local_cache():
    """Loads local message cache from a file."""
    global local_channels
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(LOCAL_CACHE_FILE), exist_ok=True)
        with open(LOCAL_CACHE_FILE, "r") as f:
            local_channels = json.load(f)
            log_info("Local message cache loaded.")
    except FileNotFoundError:
        local_channels = {}
        log_info("No local cache file found. Starting empty.")
    except json.JSONDecodeError:
        local_channels = {}
        log_error("Error decoding local cache file. Starting with empty cache.")
    except Exception as e:
        log_error(f"Unexpected error loading local cache: {e}")
        local_channels = {}

def save_local_cache():
    """Saves local message cache to a file."""
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(LOCAL_CACHE_FILE), exist_ok=True)
        with open(LOCAL_CACHE_FILE, "w", encoding='utf-8') as f:
            json.dump(local_channels, f, ensure_ascii=False, indent=4)
            # log_info("Local message cache saved.") # Can be noisy
    except Exception as e:
        log_error(f"Error saving local cache: {e}")

# --- Robust Receive Helper ---
# ... (other functions like connect_to_server, login, etc.) ...

def receive_json_response(client_socket, timeout=10.0):
    buffer = b""
    json_data = None
    start_time = time.time()
    
    # Store original blocking state and set to non-blocking for select
    original_blocking_state = client_socket.getblocking()
    client_socket.setblocking(False)

    try:
        while True:
            # Check for overall timeout
            elapsed_time = time.time() - start_time
            if elapsed_time >= timeout:
                # print(f"[ERROR] Overall timeout ({timeout}s) receiving JSON response. Buffer: {buffer[:200]}")
                return {"status": "error", "message": "Overall timeout receiving JSON response: Timeout waiting for complete JSON response"}

            # Calculate remaining time for select
            remaining_timeout = timeout - elapsed_time
            if remaining_timeout <= 0: # Should be caught by above, but as a safeguard
                return {"status": "error", "message": "Timeout before select call"}

            # Wait for the socket to be readable
            ready_to_read, _, exceptional_sockets = select.select([client_socket], [], [client_socket], remaining_timeout)

            if exceptional_sockets:
                # print("[ERROR] Socket exception during select.")
                return {"status": "error", "message": "Socket exception"}

            if ready_to_read:
                for sock in ready_to_read:
                    try:
                        chunk = sock.recv(4096) # This was line 80
                        if not chunk:
                            # print("[ERROR] Connection closed by server while receiving JSON.")
                            return {"status": "error", "message": "Connection closed by server"}
                        buffer += chunk
                        # print(f"[DEBUG] Received chunk, buffer size: {len(buffer)}")
                    except BlockingIOError:
                        # This shouldn't happen if select.select indicated readability,
                        # but handle defensively. More likely, no data was ready yet if select timed out.
                        pass # Continue to the next iteration to check timeout or select again
                    except ConnectionResetError:
                        # print("[ERROR] ConnectionResetError while receiving JSON.")
                        return {"status": "error", "message": "Connection reset by server"}
                    except Exception as e:
                        # print(f"[ERROR] Unexpected error receiving chunk: {e}")
                        return {"status": "error", "message": f"Unexpected error receiving response: {e}"}
            # If select timed out (ready_to_read is empty) and we haven't hit overall timeout,
            # the outer loop will continue and check overall_timeout or call select again.

            # Attempt to parse JSON from the buffer
            # This brace-counting logic is fragile.
            # A more robust method is for the server to send the message length first.
            try:
                decoded_buffer = buffer.decode('utf-8', errors='replace') # Use replace for safety
                
                json_start_index = -1
                # Find the first opening brace that is not part of an already processed object
                # This logic assumes we are looking for the *next* JSON object if buffer contains multiple.
                # For simplicity, let's assume we are looking for the first complete JSON.
                
                # Try to find the start of a JSON object
                current_scan_start = 0
                while current_scan_start < len(buffer):
                    try:
                        first_brace = buffer.find(b'{', current_scan_start)
                        if first_brace == -1: # No more opening braces
                            break 

                        brace_count = 0
                        in_string = False
                        json_end_index = -1

                        for i in range(first_brace, len(buffer)):
                            char_byte = buffer[i:i+1]
                            char = char_byte.decode('utf-8', errors='ignore') # Process one byte at a time

                            if char == '"':
                                # Basic handling for strings, not perfect for escaped quotes within JSON strings
                                if i > first_brace and buffer[i-1:i] != b'\\':
                                    in_string = not in_string
                                elif i == first_brace: # Quote at the very start of scan (unlikely for valid JSON start)
                                    in_string = not in_string
                            elif not in_string:
                                if char == '{':
                                    brace_count += 1
                                elif char == '}':
                                    brace_count -= 1
                                    if brace_count == 0: # Potential end of a JSON object
                                        json_end_index = i
                                        break
                        
                        if json_end_index != -1 and brace_count == 0:
                            json_str_bytes = buffer[first_brace : json_end_index + 1]
                            try:
                                json_data = json.loads(json_str_bytes.decode('utf-8'))
                                # print(f"[DEBUG] Successfully parsed JSON: {json_data}")
                                buffer = buffer[json_end_index + 1:] # Remove parsed data
                                return json_data
                            except json.JSONDecodeError:
                                # Found matching braces, but not valid JSON.
                                # This could mean it's part of a larger structure or malformed.
                                # If it's malformed and we assume one JSON per call, this is an error.
                                # For now, we'll assume it might be incomplete and continue accumulating
                                # if more data comes. If it's the only object, this will eventually timeout.
                                # print(f"[DEBUG] JSONDecodeError, buffer might be incomplete or malformed. Trying to accumulate more. Slice: {json_str_bytes[:100]}")
                                current_scan_start = json_end_index + 1 # Try to find next JSON
                                continue # Continue scanning the rest of the buffer
                            except UnicodeDecodeError as ue:
                                # print(f"[ERROR] UnicodeDecodeError during JSON parsing: {ue}")
                                return {"status": "error", "message": f"Unicode decode error during JSON parsing: {ue}"}
                        elif brace_count > 0 : # Incomplete JSON object, need more data
                            break # Break from inner scanning loop, wait for more data from socket
                        else: # No valid JSON found starting at first_brace
                            current_scan_start = first_brace + 1


                    except UnicodeDecodeError:
                        # This can happen if a multi-byte char is split. Wait for more data.
                        break # Break from inner scanning loop, wait for more data

                # If we've scanned the whole buffer and found no complete JSON, wait for more data
                if json_data: # Should have been returned
                    break

            except UnicodeDecodeError:
                # Error decoding the whole buffer, might be incomplete.
                pass # Continue accumulating

            # If not parsed and not timed out, the loop continues.
            # No explicit sleep here as select() handles the waiting.

    except socket.error as e: # Catch other socket errors
        # print(f"[ERROR] Socket error in receive_json_response: {e}")
        return {"status": "error", "message": f"Socket error: {e}"}
    except Exception as e:
        # print(f"[ERROR] General exception in receive_json_response: {e}")
        # import traceback
        # print(traceback.format_exc())
        return {"status": "error", "message": f"General error receiving JSON: {e}"}
    finally:
        client_socket.setblocking(original_blocking_state) # Restore original blocking state

    # This part is reached if the loop exits due to timeout without parsing successfully
    if not json_data:
        # print(f"[ERROR] Failed to parse complete JSON within timeout. Final Buffer: {buffer[:200]}")
        return {"status": "error", "message": "Timeout waiting for complete JSON response (final check)"}
    
    # This line should ideally not be reached if logic is correct, as json_data is returned inside the loop.
    return json_data



# --- Authentication and Status ---
def login(client_socket, username=None, password=None, visitor_name=None, register=False):
    try:
        if register:
            request = {"type": "auth", "action": "register", "username": username, "password": password}
        elif visitor_name:
            request = {"type": "auth", "action": "visitor_login", "visitor_name": visitor_name}
        elif username and password:
            request = {"type": "auth", "action": "login", "username": username, "password": password}
        else:
            return {"status": "error", "message": "Invalid login parameters"}

        client_socket.sendall((json.dumps(request) + "\n").encode('utf-8')) # Use sendall + newline
        response = receive_json_response(client_socket) # Use robust receiver
        log_info(f"Login/Register response: {response}")
        return response
    except (ConnectionError, BrokenPipeError, socket.error) as e:
        log_error(f"Connection failed during Login/Register: {e}")
        return {"status": "error", "message": f"Connection failed: {e}"}
    except Exception as e:
        log_error(f"Login/Register failed: {e}")
        return {"status": "error", "message": str(e)}

def change_status(client_socket, username, status):
    try:
        request = {
            "type": "auth",
            "action": "update_status",
            "username": username,
            "status": status
        }
        client_socket.sendall((json.dumps(request) + "\n").encode('utf-8')) # Use sendall + newline
        response_data = receive_json_response(client_socket) # Use robust receiver

        if response_data.get("status") == "success":
            log_info(f"Status change to {status} for {username} confirmed by server.")
        else:
            log_error(f"Failed to change status: {response_data.get('message')}")
        return response_data
    except (ConnectionError, BrokenPipeError, socket.error) as e:
        log_error(f"Connection failed during status change: {e}")
        return {"status": "error", "message": f"Connection failed: {e}"}
    except Exception as e:
        log_error(f"Error changing status: {e}")
        return {"status": "error", "message": str(e)}

# --- User List ---
def list_online_users(client_socket, channel_name):
    try:
        request = {
            "type": "get_user_status",
            "channel": channel_name
        }
        # log_debug(f"Sending get_user_status request for channel '{channel_name}': {request}") # Bỏ comment nếu logger của bạn hỗ trợ log_debug và bạn muốn xem request
        client_socket.sendall((json.dumps(request) + "\n").encode("utf-8"))
        response = receive_json_response(client_socket) # Sử dụng hàm nhận đã được cải thiện

        # Ghi log toàn bộ phản hồi nhận được để gỡ lỗi (nếu log_debug được cấu hình)
        log_debug(f"Full response for get_user_status on '{channel_name}': {response}")

        if response and response.get("status") == "success":
            online_list = response.get('online', [])
            offline_list = response.get('offline', [])
            # Lưu ý: User 'invisible' có thể xuất hiện trong danh sách 'offline' tùy theo logic của server
        elif response: # Nhận được phản hồi, nhưng status không phải là "success"
            error_msg = response.get('message', 'No message provided')
            log_error(f"Failed to get user status for '{channel_name}'. Server message: '{error_msg}'. Full response: {response}")
        else: # Không nhận được phản hồi hoặc phản hồi không hợp lệ từ receive_json_response
            log_error(f"Failed to get user status for '{channel_name}': No valid response received from server.")
            # Trả về một dictionary lỗi chuẩn nếu response không hợp lệ
            return {"status": "error", "message": "No valid response received from server."}
            
        return response
    except (ConnectionError, BrokenPipeError, socket.error) as e:
        log_error(f"Connection failed fetching user status for '{channel_name}': {e}")
        return {"status": "error", "message": f"Connection failed while fetching status for {channel_name}: {e}"}
    except Exception as e:
        # Ghi log lỗi kèm traceback cho các lỗi không mong muốn
        # Giả sử log_error của bạn có thể xử lý exc_info=True nếu bạn dùng module logging của Python
        # Nếu không, bạn cần tự in traceback trong hàm log_error
        log_error(f"Unexpected error fetching user status for '{channel_name}': {e}", exc_info=True) 
        return {"status": "error", "message": f"Unexpected error fetching status for {channel_name}: {str(e)}"}

# --- Channel Management ---
def send_create_channel_request(client_socket, channel_name, username):
    try:
        request = {
            "type": "channel",
            "action": "create_channel",
            "channel_name": channel_name,
            "username": username
        }
        client_socket.sendall((json.dumps(request) + "\n").encode('utf-8')) # Use sendall + newline
        response_data = receive_json_response(client_socket) # Use robust receiver
        return response_data
    except (ConnectionError, BrokenPipeError, socket.error) as e:
        log_error(f"Connection failed creating channel: {e}")
        return {"status": "error", "message": f"Connection failed: {e}"}
    except Exception as e:
        log_error(f"Failed to create channel: {e}")
        return {"status": "error", "message": str(e)}

def list_channels(client_socket):
    try:
        request = {
            "type": "channel",
            "action": "list_channels"
        }
        client_socket.sendall((json.dumps(request) + "\n").encode('utf-8')) # Use sendall + newline
        response_data = receive_json_response(client_socket) # Use robust receiver

        if response_data.get("status") == "success":
            channels = response_data.get("channels", [])
        else:
            log_error(f"Failed to list channels: {response_data.get('message')}")
        return response_data
    except (ConnectionError, BrokenPipeError, socket.error) as e:
        log_error(f"Connection failed listing channels: {e}")
        return {"status": "error", "message": f"Connection failed: {e}"}
    except Exception as e:
        log_error(f"Failed to list channels: {e}")
        return {"status": "error", "message": str(e)}

def send_join_channel_request(client_socket, username, channel_name):
    try:
        join_request = {
            "type": "channel",
            "action": "join_channel",
            "username": username,
            "channel_name": channel_name
        }
        client_socket.sendall((json.dumps(join_request) + "\n").encode('utf-8')) # Use sendall + newline
        response_data = receive_json_response(client_socket) # Use robust receiver

        if response_data.get("status") == "success":
            log_info(f"Successfully joined channel '{channel_name}'. Server response: {response_data}")
            # UI should handle displaying the details from response_data
        else:
            log_error(f"Failed to join channel '{channel_name}': {response_data.get('message')}")
        return response_data
    except (ConnectionError, BrokenPipeError, socket.error) as e:
        log_error(f"Connection failed joining channel: {e}")
        return {"status": "error", "message": f"Connection failed: {e}"}
    except Exception as e:
        log_error(f"Error joining channel '{channel_name}': {e}")
        return {"status": "error", "message": str(e)}

def send_delete_channel_request(client_socket, channel_name, username):
    try:
        request = {
            "type": "channel",
            "action": "delete_channel",
            "channel_name": channel_name,
            "username": username
        }
        client_socket.sendall((json.dumps(request) + "\n").encode('utf-8')) # Use sendall + newline
        response_data = receive_json_response(client_socket) # Use robust receiver
        return response_data
    except (ConnectionError, BrokenPipeError, socket.error) as e:
        log_error(f"Connection failed deleting channel: {e}")
        return {"status": "error", "message": f"Connection failed: {e}"}
    except Exception as e:
        log_error(f"Failed to delete channel: {e}")
        return {"status": "error", "message": str(e)}

# --- Sync Functions ---

def request_sync_from_server(client_socket, channel_name, username): # Added username for server check
    """Requests all messages for a channel from the server."""
    if not client_socket or client_socket.fileno() == -1:
         log_error("Error: Invalid socket for sync from server.")
         return {"status": "error", "message": "Invalid client socket"}
    try:
        request = {
            "type": "channel",
            "action": "sync_from_server",
            "channel_name": channel_name,
            "username": username # Send username so server can verify participation
        }
        client_socket.sendall((json.dumps(request) + "\n").encode('utf-8'))
        response = receive_json_response(client_socket, timeout=15.0) # Longer timeout for potentially large sync

        # Check if the response is a PUSH notification FIRST
        if response and response.get("type") == "channel" and response.get("action") == "new_message":
            log_debug(f"request_sync_from_server received a PUSH message: {response}")
            return response # Return PUSH message for UI to handle without logging error here

        # If not a PUSH, then it's a response to our sync request. Check its status.
        if response and response.get("status") != "success":
             log_error(f"Server error during sync from server for '{channel_name}': {response.get('message')}")
        # else:
        #    if response and response.get("status") == "success":
        #        log_info(f"Sync from server for '{channel_name}' successful.") # Can be noisy
        return response
    except (ConnectionError, BrokenPipeError, socket.error) as e:
        log_error(f"Connection error syncing from server for {channel_name}: {e}")
        return {"status": "error", "message": f"Connection error: {e}"}
    except Exception as e:
        log_error(f"Error syncing from server for {channel_name}: {e}", exc_info=True) # Added exc_info for better debugging
        return {"status": "error", "message": str(e)}

def request_sync_to_server(client_socket, channel_name, messages, username): # Added username for server check
    """Sends locally cached messages to the server for merging."""
    if not client_socket or client_socket.fileno() == -1:
         log_error("Error: Invalid socket for sync to server.")
         return {"status": "error", "message": "Invalid client socket"}
    if not messages:
        return {"status": "success", "message": "No local messages to sync."}
    try:
        request = {
            "type": "channel",
            "action": "sync_to_server",
            "channel_name": channel_name,
            "messages": messages,
            "username": username # Send username so server can verify participation and message ownership
        }
        client_socket.sendall((json.dumps(request) + "\n").encode('utf-8')) # Use sendall + newline
        response = receive_json_response(client_socket) # Use robust receiver
        if response.get("status") != "success":
             log_error(f"Server error during sync to server for '{channel_name}': {response.get('message')}")
        # else: log_info(f"Sync to server for '{channel_name}' confirmed by server.")
        return response
    except (ConnectionError, BrokenPipeError, socket.error) as e:
        log_error(f"Connection error syncing to server for {channel_name}: {e}")
        return {"status": "error", "message": f"Connection error: {e}"}
    except Exception as e:
        log_error(f"Error syncing to server for {channel_name}: {e}")
        return {"status": "error", "message": str(e)}

# --- Local Saving ---
def save_local_message(channel_name, username, message):
    """Lưu tin nhắn cục bộ khi server không khả dụng hoặc gửi thất bại."""
    global local_channels
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    if channel_name not in local_channels:
        local_channels[channel_name] = {"messages": []}
    elif not isinstance(local_channels[channel_name].get("messages"), list):
         log_warning(f"Correcting invalid local message list for channel '{channel_name}'.")
         local_channels[channel_name]["messages"] = []


    # Check for duplicates before adding
    is_duplicate = any(
        m.get('timestamp') == timestamp and m.get('username') == username and m.get('message') == message
        for m in local_channels[channel_name].get("messages", [])
        if isinstance(m, dict) # Ensure message format is correct before checking
    )

    if not is_duplicate:
         new_message = {
            "username": username,
            "message": message,
            "timestamp": timestamp
         }
         local_channels[channel_name]["messages"].append(new_message)
         log_info(f"Message saved locally for channel '{channel_name}': {new_message}")
         save_local_cache() # Save cache immediately after adding a message
    else:
        log_info(f"Attempted to save duplicate local message for channel '{channel_name}'.")


# --- Online/Offline Handling ---
def handle_client_online(client_socket, username, current_channel):
    """
    Synchronizes local cache TO server, then fetches updates FROM server
    for the current channel when client comes online.
    """
    global local_channels
    log_info(f"Client '{username}' is online. Starting synchronization for channel '{current_channel}'...")

    # --- Phase 1: Sync TO Server (Local Cache -> Server) ---
    log_info("Phase 1: Syncing local messages TO server...")
    synced_successfully = False
    try:
        if current_channel in local_channels:
            messages_to_sync = local_channels[current_channel].get("messages", [])
            if messages_to_sync:
                log_info(f"Attempting to sync {len(messages_to_sync)} local messages for '{current_channel}' to server...")
                # Pass username for server-side validation
                sync_response = request_sync_to_server(client_socket, current_channel, messages_to_sync, username)

                if sync_response and sync_response.get("status") == "success":
                    log_info(f"Successfully synced local messages for '{current_channel}' to server.")
                    # Clear local cache for this channel ONLY IF sync was successful
                    local_channels[current_channel]["messages"] = []
                    save_local_cache() # Save the cleared cache
                    synced_successfully = True
                else:
                    error_msg = sync_response.get('message', 'Unknown error') if sync_response else 'No response'
                    log_error(f"Failed to sync local messages for '{current_channel}' to server: {error_msg}. Messages kept locally.")
            else:
                log_info(f"No local messages to sync for channel '{current_channel}'.")
                synced_successfully = True # No sync needed is also a success for this phase
        else:
            synced_successfully = True # No sync needed

        log_info("Phase 1 (Sync TO Server) finished.")

    except Exception as e:
        log_error(f"Error during client online synchronization (Phase 1 - TO server): {e}")
        # Proceed to Phase 2 even if Phase 1 had errors? Yes, try to get latest data.

    # --- Phase 2: Sync FROM Server (Server -> Client) ---
    # This should happen regardless of Phase 1 success to get latest messages
    log_info("Phase 2: Syncing messages FROM server...")
    server_messages = []
    try:
        # Pass username for server-side validation
        sync_response = request_sync_from_server(client_socket, current_channel, username)
        if sync_response and sync_response.get("status") == "success":
            server_messages = sync_response.get("messages", [])
            # The UI layer will be responsible for merging/displaying these messages
        else:
            error_msg = sync_response.get('message', 'Unknown error') if sync_response else 'No response'
            log_error(f"Failed to sync messages from server for '{current_channel}': {error_msg}")

        log_info("Phase 2 (Sync FROM Server) finished.")
        # Return the fetched messages so the UI can update
        return server_messages

    except Exception as e:
        log_error(f"Error during client online synchronization (Phase 2 - FROM server): {e}")
        return [] # Return empty list on error


# --- Sending Messages ---
def send_message(client_socket, channel_name, message, username):
    """
    Sends a message to the server. If connection fails, saves locally.
    Returns the server's response on success/error, or a specific status for local save.
    """
    # Check socket validity before attempting to send
    if not client_socket or client_socket.fileno() == -1:
        log_warning("Socket invalid or closed. Saving message locally.")
        save_local_message(channel_name, username, message)
        return {"status": "offline_save", "message": "Server unavailable (socket invalid). Message saved locally."}

    try:
        request = {
            "type": "channel",
            "action": "save_message",
            "channel_name": channel_name,
            "message": message,
            "username": username # Server uses this to verify sender and store
        }
        client_socket.sendall((json.dumps(request) + "\n").encode('utf-8')) # Use sendall + newline

        # Wait for server confirmation using the robust receiver
        response = receive_json_response(client_socket, timeout=5.0) # 5 second timeout for send confirmation

        # Log success/error based on server response status
        # if response.get("status") == "success":
        #      log_info(f"Server confirmed message saved: {response.get('message_data')}")
        # elif response.get("status") == "error":
        #      log_error(f"Server returned error for send_message: {response.get('message')}")
        #      # Decide if we should save locally on server error (e.g., auth mismatch)?
        #      # For now, let's NOT save locally if server explicitly rejected it.
        # else:
        #      # Handle unexpected status or connection issues during receive
        #      log_error(f"Unexpected response status or connection issue receiving send confirmation: {response}. Saving locally.")
        #      save_local_message(channel_name, username, message)
        #      return {"status": "offline_save", "message": f"Receive error/timeout: {response.get('message', 'Unknown')}. Message saved locally."}

        return response # Return the full server response (success or error)

    except (ConnectionError, BrokenPipeError, socket.error) as e:
        log_error(f"Connection error sending message: {e}. Saving locally.")
        save_local_message(channel_name, username, message)
        return {"status": "offline_save", "message": f"Connection error: {e}. Message saved locally."}
    except Exception as e:
        # Catch any other unexpected errors
        log_error(f"Unexpected error in send_message: {e}. Saving locally.")
        save_local_message(channel_name, username, message)
        return {"status": "error", "message": f"Unexpected error: {e}. Message saved locally."}

# --- Utility/Debugging ---
def log_debug(message):
     # Simple print for debug, or integrate with logger if needed
     # print(f"[DEBUG] {message}")
     pass # Keep debug logs off by default