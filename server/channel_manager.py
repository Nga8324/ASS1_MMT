import json
import os
import threading
import datetime
from logger import log_info, log_error
from shared import channel_users, user_status, user_roles  # Import danh sách người dùng và trạng thái người dùng
# --- Constants and Lock ---
CHANNELS_FILE = "server/channels.json"
channels_lock = threading.Lock() # <--- Define the lock globally

# --- File Operations (Thread-Safe) ---
# Replace your existing load_channels with this one
def load_channels():
    """Loads channel data from the JSON file (thread-safe)."""
    with channels_lock: # Acquire lock before file access
        try:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(CHANNELS_FILE), exist_ok=True)
            with open(CHANNELS_FILE, "r") as file:
                data = json.load(file)
                # Basic validation
                if "channels" not in data or not isinstance(data.get("channels"), dict):
                    log_error(f"Invalid structure in {CHANNELS_FILE}. Resetting.")
                    return {"channels": {}}
                return data
        except FileNotFoundError:
            log_info(f"{CHANNELS_FILE} not found. Creating default structure.")
            return {"channels": {}} # Return default structure if file doesn't exist
        except json.JSONDecodeError as e:
            log_error(f"Error decoding JSON from {CHANNELS_FILE}: {e}. Returning default.")
            return {"channels": {}}
        except Exception as e:
            log_error(f"Unexpected error loading channels: {e}", exc_info=True)
            return {"channels": {}}

# Replace your existing save_channels with this one
def save_channels(channels):
    """Saves channel data to the JSON file (thread-safe)."""
    with channels_lock: # Acquire lock before file access
        try:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(CHANNELS_FILE), exist_ok=True)
            with open(CHANNELS_FILE, "w") as file:
                json.dump(channels, file, indent=4)
                file.flush() # Ensure data is written immediately
        except Exception as e:
            log_error(f"Error saving channels to {CHANNELS_FILE}: {e}", exc_info=True)

def send_response(client_socket, response_data, addr=None):
    """Sends a JSON response to the client."""
    try:
        # Ensure addr is a string for logging if provided
        addr_str = f"{addr}" if addr else "Unknown Address"
        # Use sendall and add a newline character as a delimiter
        client_socket.sendall((json.dumps(response_data) + "\n").encode('utf-8'))
        # log_info(f"Sent response to {addr_str}: {response_data}") # Optional
    except Exception as e:
        log_error(f"Failed to send response to {addr_str if addr else 'Unknown Address'}: {e}")

# Hàm điều hướng yêu cầu liên quan đến channel (SỬA ĐỔI)
def handle_channel_request(client_socket, data):
    response = None # Initialize response
    addr_info = client_socket.getpeername() if client_socket and client_socket.fileno() != -1 else "Unknown Address"
    try:
        # ... (parsing logic remains the same) ...
        if isinstance(data, bytes):
            data = data.decode('utf-8')
        if isinstance(data, str):
            request = json.loads(data)
        else:
            request = data

        action = request.get("action")
        authenticated_user = data.get("_authenticated_user") # Get authenticated user

        # Call the appropriate function, which should RETURN the response dict
        if action == "create_channel":
            response = create_channel(client_socket, request) # Should return dict
        elif action == "list_channels":
            response = list_channels(client_socket) # Modify to return dict
        elif action == "delete_channel":
            response = delete_channel(client_socket, request) # Modify to return dict
        elif action == "join_channel":
            response = join_channel(client_socket, request) # Modify to return dict
        elif action == "save_message":
            response = save_message(client_socket, request, authenticated_user) # Already returns dict
        elif action == "sync_to_server":
            response = handle_sync_to_server(client_socket, request) # Modify to return dict
        elif action == "sync_from_server":
            response = handle_sync_from_server(client_socket, request) # Modify to return dict
        else:
            response = {"status": "error", "message": "Invalid channel action"}

        # Always send the response if one was generated
        if response:
            send_response(client_socket, response, addr_info)
        # else: # Optional: Log if no response was generated unexpectedly
        #    log_warning(f"No response generated for action '{action}' from {addr_info}")

    except json.JSONDecodeError:
        response = {"status": "error", "message": "Invalid JSON format"}
        send_response(client_socket, response, addr_info) # Send error response
    except Exception as e:
        log_error(f"Error handling channel request for {addr_info}: {e}", exc_info=True)
        response = {"status": "error", "message": f"Internal server error: {str(e)}"}
        # Try to send error response, but might fail if socket is broken
        try:
            send_response(client_socket, response, addr_info)
        except Exception as send_e:
            log_error(f"Failed to send error response after exception in handle_channel_request: {send_e}")
# Hàm tạo kênh
def create_channel(client_socket, request):
    try:
        channel_name = request.get("channel_name")
        username = request.get("username")
        if not channel_name or not username:
            return {"status": "error", "message": "Channel name and username are required"}

        channels = load_channels()
        if channel_name in channels["channels"]:
            return {"status": "error", "message": f"Channel '{channel_name}' already exists"}
        else:
            channels["channels"][channel_name] = {
                "host": username,
                "participants": [username],
                "messages": []
            }
            save_channels(channels)
            return {"status": "success", "message": f"Channel '{channel_name}' created successfully"}

    except Exception as e:
        log_error(f"Error in create_channel: {e}")
        return {"status": "error", "message": str(e)}


# Hàm xóa kênh
def delete_channel(client_socket, request):
    try:
        channel_name = request.get("channel_name")
        username = request.get("username")  # Lấy thông tin người yêu cầu
        if not channel_name or not username:
            response = {"status": "error", "message": "Channel name and username are required"}
            client_socket.send(json.dumps(response).encode('utf-8'))
            return

        channels = load_channels()

        # Kiểm tra nếu "channels" không phải là từ điển
        if not isinstance(channels["channels"], dict):
            response = {"status": "error", "message": "Invalid channels data format"}
            client_socket.send(json.dumps(response).encode('utf-8'))
            return

        # Kiểm tra nếu kênh tồn tại
        if channel_name != "General" and channel_name not in channels["channels"]:
            response = {"status": "error", "message": f"Channel '{channel_name}' does not exist"}
            client_socket.send(json.dumps(response).encode('utf-8'))
            return

        # Kiểm tra nếu người yêu cầu là người tạo kênh
        if channels["channels"][channel_name]["host"] != username:
            response = {"status": "error", "message": "You do not have permission to delete the channel"}
            client_socket.send(json.dumps(response).encode('utf-8'))
            return

        # Xóa kênh
        del channels["channels"][channel_name]
        save_channels(channels)
        response = {"status": "success", "message": f"Channel '{channel_name}' deleted successfully"}
        client_socket.send(json.dumps(response).encode('utf-8'))
    except Exception as e:
        response = {"status": "error", "message": str(e)}
        client_socket.send(json.dumps(response).encode('utf-8'))
# Hàm liệt kê danh sach các kênh
def list_channels(client_socket):
    try:
        channels = load_channels()
        response = {
            "status": "success",
            "channels": list(channels["channels"].keys())
        }
        client_socket.send(json.dumps(response).encode('utf-8'))  # Gửi một phản hồi JSON duy nhất
        log_info(f"Channels listed: {response}")
    except Exception as e:
        response = {"status": "error", "message": str(e)}
        client_socket.send(json.dumps(response).encode('utf-8'))
        log_error(f"Error in list_channels: {e}")

def join_channel(client_socket, request): # Modified to return response dict
    try:
        channel_name = request.get("channel_name")
        username = request.get("username")

        if not channel_name or not username:
            return {"status": "error", "message": "Channel name and username are required"}

        channels = load_channels() # Thread-safe load

        # Ensure "channels" key exists and is a dictionary
        if "channels" not in channels or not isinstance(channels.get("channels"), dict):
            log_error("Invalid or missing 'channels' structure in channels.json during join_channel")
            channels["channels"] = {} # Attempt to initialize if missing

        # Check if channel exists (allow "General" implicitly)
        if channel_name != "General" and channel_name not in channels["channels"]:
            return {"status": "error", "message": f"Channel '{channel_name}' does not exist"}

        # Handle "General" channel creation if it doesn't exist
        if channel_name == "General" and "General" not in channels["channels"]:
            channels["channels"]["General"] = {
                "host": "system", 
                "participants": [],
                "messages": []
            }
            log_info("Implicitly created 'General' channel during join_channel.")

        channel_data = channels["channels"][channel_name]

        user_joined_for_first_time = False
        # Ensure participants list exists
        if "participants" not in channel_data or not isinstance(channel_data["participants"], list):
            channel_data["participants"] = []
            
        if username not in channel_data["participants"]:
            channel_data["participants"].append(username)
            user_joined_for_first_time = True # User is newly added to participants

        # Add system message for user join if they are new to the channel's participant list
        system_message_content = f"User '{username}' has joined the channel."
        timestamp = datetime.datetime.utcnow().isoformat() + "Z"
        if user_roles.get(username) != "guest":  # Check if the role is not 'guest'
            system_message_data = {
            "username": "System",
            "message": system_message_content,
            "timestamp": timestamp,
            "event_type": "USER_JOINED_CHANNEL"
            }
            # Ensure messages list exists and is a list
            messages_list = channel_data.setdefault("messages", [])
            if not isinstance(messages_list, list): 
                messages_list = []
                channel_data["messages"] = messages_list
                
            messages_list.append(system_message_data)
            messages_list.sort(key=lambda x: x.get('timestamp', '')) # Keep sorted
            log_info(f"System message for '{username}' joining '{channel_name}' prepared.")
        
        save_channels(channels) # Save updated participants and potentially the new system message

        # Update channel_users (in-memory state for online/offline list)
        if channel_name not in channel_users:
            channel_users[channel_name] = {"online": [], "offline": []}

        status = user_status.get(username, "offline") 

        # Remove from the other list and add to the correct one
        # Treat invisible as online for channel presence regarding lists
        if status == "online" or status == "invisible": 
            if username in channel_users[channel_name].get("offline", []):
                channel_users[channel_name]["offline"].remove(username)
            if username not in channel_users[channel_name].get("online", []):
                channel_users[channel_name].setdefault("online", []).append(username)
        else: # offline
            if username in channel_users[channel_name].get("online", []):
                channel_users[channel_name]["online"].remove(username)
            if username not in channel_users[channel_name].get("offline", []):
                channel_users[channel_name].setdefault("offline", []).append(username)
        
        # Ensure no duplicates
        if "online" in channel_users[channel_name]:
            channel_users[channel_name]["online"] = list(set(channel_users[channel_name]["online"]))
        if "offline" in channel_users[channel_name]:
            channel_users[channel_name]["offline"] = list(set(channel_users[channel_name]["offline"]))

        log_info(f"User '{username}' joined channel '{channel_name}'. In-memory status updated.")
        
        return { 
            "status": "success",
            "message": f"User '{username}' joined channel '{channel_name}' successfully",
            "owner": channel_data.get("host", "system"), 
            "user_list": { 
                "online": channel_users[channel_name].get("online", []),
                "offline": channel_users[channel_name].get("offline", [])
            }
        }

    except Exception as e:
        log_error(f"Error in join_channel for user '{request.get('username', 'N/A')}' in channel '{request.get('channel_name', 'N/A')}': {e}", exc_info=True)
        return {"status": "error", "message": f"Internal server error during join channel: {str(e)}"}
# --- Helper Functions (Add this if not already present) ---
def send_response(client_socket, response_data, addr=None):
    """Sends a JSON response to the client."""
    try:
        client_socket.sendall((json.dumps(response_data) + "\n").encode('utf-8')) # Use sendall and newline
    except Exception as e:
        log_error(f"Failed to send response to {addr}: {e}")
# Hàm lưu tin nhắn vào kênh
def save_message(client_socket, request, authenticated_user):
    try:
        channel_name = request.get("channel_name")
        message_text = request.get("message")
        username = request.get("username") # Username provided in the request

        # Security check: Ensure the username in the request matches the authenticated user
        if username != authenticated_user:
             log_error(f"Message save attempt mismatch: Auth user '{authenticated_user}', request user '{username}'")
             response = {"status": "error", "message": "Authentication mismatch"}
             # send_response(client_socket, response) // DO NOT SEND HERE
             return response 

        current_user_status = user_status.get(username, "offline") 
        if current_user_status not in ["online", "invisible"]:
            log_error(f"User '{username}' attempted to send message while server status is '{current_user_status}'")
            response = {"status": "error", "message": f"Cannot send messages while status is '{current_user_status}'"}
            # send_response(client_socket, response) // DO NOT SEND HERE
            return response 

        if not channel_name or not message_text or not username:
            response = {"status": "error", "message": "Channel name, message, and username are required"}
            # send_response(client_socket, response) // DO NOT SEND HERE
            return response 

        channels = load_channels()
        if "channels" not in channels or not isinstance(channels.get("channels"), dict):
             log_error("Invalid or missing 'channels' structure in channels.json")
             channels = {"channels": {}} 

        channel_data = channels.get("channels", {}).get(channel_name)

        if not channel_data:
            if channel_name == "General":
                 if "General" not in channels.get("channels", {}):
                      channels.setdefault("channels", {})["General"] = {"owner": "system", "participants": [], "messages": []}
                      log_info("Implicitly created 'General' channel during save_message.")
                 channel_data = channels["channels"]["General"]
            else:
                 log_error(f"User '{username}' tried saving message to non-existent channel '{channel_name}'.")
                 response = {"status": "error", "message": f"Channel '{channel_name}' does not exist"}
                 # send_response(client_socket, response) // DO NOT SEND HERE
                 return response 

        messages_list = channel_data.setdefault("messages", [])
        if not isinstance(messages_list, list):
            log_error(f"Correcting invalid 'messages' type for channel '{channel_name}'.")
            messages_list = []
            channel_data["messages"] = messages_list

        timestamp = datetime.datetime.utcnow().isoformat() + "Z" 
        message_data = {
            "username": username,
            "message": message_text,
            "timestamp": timestamp
        }

        messages_list.append(message_data)
        save_channels(channels)

        response = {"status": "success", "message": "Message saved successfully", "message_data": message_data}
        # send_response(client_socket, response) // REMOVE THIS LINE
        log_info(f"Message saved for '{username}' in '{channel_name}'.") 

        # --- TODO: Broadcast message_data to other online/invisible users in the channel ---
        # broadcast_message(channel_name, message_data, sender_socket=client_socket)

        return response 

    except Exception as e:
        log_error(f"Error in save_message: {e}", exc_info=True)
        response = {"status": "error", "message": f"Internal server error: {e}"}
        # try:
            # send_response(client_socket, response) // DO NOT SEND HERE
        # except Exception as send_e:
            # log_error(f"Failed to send error response during save_message: {send_e}")
        return response 
def save_system_message(channel_name, message_data):
    """Saves a system-generated message/notification to a channel (thread-safe)."""
    if not channel_name or not isinstance(message_data, dict):
        log_error(f"Invalid input for save_system_message: channel='{channel_name}', data='{message_data}'")
        return False # Indicate failure

    try:
        # Use the thread-safe load_channels function
        channels = load_channels()
        # Ensure "channels" key exists and is a dictionary
        if "channels" not in channels or not isinstance(channels.get("channels"), dict):
             log_error("Invalid or missing 'channels' structure in channels.json during system save")
             channels = {"channels": {}} # Reset to avoid further errors

        channel_data = channels.get("channels", {}).get(channel_name)

        # Check if channel exists or handle 'General' implicitly
        if not channel_data:
            if channel_name == "General":
                 if "General" not in channels.get("channels", {}):
                      channels.setdefault("channels", {})["General"] = {"owner": "system", "participants": [], "messages": []}
                      log_info("Implicitly created 'General' channel during save_system_message.")
                 channel_data = channels["channels"]["General"]
            else:
                 log_error(f"Attempted to save system message to non-existent channel '{channel_name}'.")
                 return False # Indicate failure

        # Ensure messages list exists and is a list
        messages_list = channel_data.setdefault("messages", [])
        if not isinstance(messages_list, list):
            log_error(f"Correcting invalid 'messages' type for channel '{channel_name}' during system save.")
            messages_list = []
            channel_data["messages"] = messages_list

        # Add the system message (timestamp should already be in message_data)
        messages_list.append(message_data)

        # Sort messages by timestamp after adding (optional but good practice)
        messages_list.sort(key=lambda x: x.get('timestamp', ''))

        # Use the thread-safe save_channels function
        save_channels(channels)
        log_info(f"System message saved to channel '{channel_name}'.")
        return True # Indicate success

    except Exception as e:
        log_error(f"Error in save_system_message for channel '{channel_name}': {e}", exc_info=True)
        return False # Indicate failure
# Hàm đồng bộ tin nhắn từ channel-hosting lên server
def handle_sync_to_server(client_socket, request):
    channel_name = request.get("channel_name")
    messages_to_sync = request.get("messages") # Messages sent from client's local cache

    if not channel_name or not isinstance(messages_to_sync, list): # Check if messages is a list
        response = {"status": "error", "message": "Channel name and a list of messages are required"}
        client_socket.send(json.dumps(response).encode('utf-8'))
        return
    try:
        channels = load_channels()

        if channel_name not in channels.get("channels", {}):
             # If channel doesn't exist on server, reject sync or auto-create (rejecting for now)
             response = {"status": "error", "message": f"Channel '{channel_name}' does not exist on server"}
             client_socket.send(json.dumps(response).encode('utf-8'))
             log_error(f"Sync failed: Channel '{channel_name}' does not exist.")
             return

        # Use timestamps for merging to avoid duplicates
        # Create a set of existing timestamps for quick lookup
        server_channel_messages = channels["channels"][channel_name].get("messages", [])
        existing_timestamps = {msg['timestamp'] for msg in server_channel_messages if isinstance(msg, dict) and 'timestamp' in msg}

        new_messages_added_count = 0
        malformed_messages_count = 0

        for msg in messages_to_sync:
            # Validate message format and timestamp presence
            if isinstance(msg, dict) and 'timestamp' in msg and 'username' in msg and 'message' in msg:
                 msg_timestamp = msg['timestamp']
                 if msg_timestamp not in existing_timestamps:
                    server_channel_messages.append(msg)
                    existing_timestamps.add(msg_timestamp) # Add new timestamp to the set
                    new_messages_added_count += 1
            else:
                log_error(f"Invalid message format during sync for channel '{channel_name}': {msg}")
                malformed_messages_count += 1

        if new_messages_added_count > 0:
            # Sort messages by timestamp after merging (important for consistency)
            server_channel_messages.sort(key=lambda x: x.get('timestamp', ''))
            channels["channels"][channel_name]["messages"] = server_channel_messages # Update the list in channels dict
            save_channels(channels) # Save the updated channels data
            log_info(f"Synchronized {new_messages_added_count} new messages to channel '{channel_name}' from client.")
        else:
             log_info(f"No new messages to synchronize for channel '{channel_name}' from client.")

        if malformed_messages_count > 0:
             log_error(f"{malformed_messages_count} malformed messages ignored during sync for channel '{channel_name}'.")

        response = {
            "status": "success",
            "message": f"Synchronization to server for '{channel_name}' complete. {new_messages_added_count} new messages added."
        }
        client_socket.send(json.dumps(response).encode('utf-8'))

    except Exception as e:
        response = {"status": "error", "message": f"Internal server error during sync: {str(e)}"}
        client_socket.send(json.dumps(response).encode('utf-8'))
        log_error(f"Error in handle_sync_to_server for channel '{channel_name}': {e}")


# Hàm đồng bộ tin nhắn từ server về client (channel-hosting hoặc joined user)
def handle_sync_from_server(client_socket, request):
    try:
        channel_name = request.get("channel_name")
        username = request.get("username")

        if not channel_name or not username:
            response = {"status": "error", "message": "Channel name and username are required"}
            client_socket.send(json.dumps(response).encode('utf-8'))
            return

        channels = load_channels()

        # Check if channel exists
        if channel_name not in channels.get("channels", {}):
            # If channel doesn't exist, return empty list or error (returning empty for now)
            log_error(f"Sync from server requested for non-existent channel '{channel_name}'. Returning empty list.")
            messages = []
        else:
            # Check if the user is a participant of the channel
            participants = channels["channels"][channel_name].get("participants", [])
            if username not in participants:
                response = {"status": "error", "message": "You are not a participant of this channel"}
                client_socket.send(json.dumps(response).encode('utf-8'))
                log_error(f"User '{username}' attempted to sync messages for channel '{channel_name}' without being a participant.")
                return

            messages = channels["channels"][channel_name].get("messages", [])

        response = {"status": "success", "messages": messages}
        client_socket.send(json.dumps(response).encode('utf-8'))
        log_info(f"Sent {len(messages)} messages for channel '{channel_name}' during sync from server.")

    except Exception as e:
        response = {"status": "error", "message": f"An error occurred during sync from server: {str(e)}"}
        client_socket.send(json.dumps(response).encode('utf-8'))
        log_error(f"Error in handle_sync_from_server: {str(e)}")
