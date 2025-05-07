
import threading

active_channel_livestreams = {}
livestream_lock = threading.Lock()
# Shared data structures for the server

# Dictionary to store user status (online, offline, invisible)
# Key: username, Value: status string
user_status = {}

# Dictionary to store user roles (authenticated, guest)
# Key: username, Value: role string
user_roles = {} # Add this dictionary

# Dictionary to store channel information and users within them
# Key: channel_name
# Value: {"online": [user1, user2], "offline": [user3], "invisible": [user4]}
channel_users = {}

# --- NEW FOR CHANNEL HOSTING ---
# Stores the designated owner of a channel
# Loaded from channels.json (or a new file) on server startup, or populated on channel creation
# Example: { "channel_name1": "owner_username1", "channel_name2": "owner_username2" }
channel_owners = {}
connected_clients = {}  # Dictionary: {client_socket: username}

# Stores active P2P endpoints for channels being hosted by their owners
# Updated by 'announce'/'unannounce' requests from channel owner clients
# Example: { "channel_name1": {"host_ip": "1.2.3.4", "p2p_port": 6001, "owner_username": "owner_username1"} }
active_channel_hosts = {}

channel_host_p2p_data_ports = {} # Format: { "username_cua_host": {"ip": "ip_host", "port": cong_du_lieu_p2p} }

