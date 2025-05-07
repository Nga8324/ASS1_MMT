import tkinter as tk
from tkinter import simpledialog
import threading
import json
import time
import sys
import datetime
from tkinter import messagebox
from PIL import Image, ImageTk
from peer import start_livestream, connect_to_peer, receive_stream
# Import necessary functions from main
from main import (
    connect_to_server, login, list_channels, change_status,
    send_create_channel_request, send_delete_channel_request,
    send_join_channel_request, send_message, list_online_users,
    request_sync_from_server, save_local_message, handle_client_online,
    save_local_cache, load_local_cache
)

# Global variables
online_users_list = None
offline_users_list = None
online_users = []
offline_users = []
shown_messages = set()
current_channel = "General"
sync_thread_running = False
user_status_update_job = None
# Add message_entry and send_button as globals to be accessible in update_status
message_entry = None
send_button = None
# Store livestream info associated with chat messages
livestream_links = {} # Format: { msg_key: {"host": ip, "port": port} }
notified_livestreams = set()

# --- Helper: Update Widget State Safely ---
def update_widget_state(widget, state):
    """Safely update widget state if it exists."""
    if widget and widget.winfo_exists():
        try:
            widget.config(state=state)
        except tk.TclError as e:
            print(f"Warning: Could not update widget state: {e}")
# --- Login Screen ---
def login_screen(client_socket):
    def handle_login():
        username = username_entry.get()
        password = password_entry.get()
        if not username or not password:
            messagebox.showwarning("Warning", "Please enter both username and password.")
            return
        response = login(client_socket, username=username, password=password)
        # Sửa: Kiểm tra response trước khi gọi get
        if response and response.get("status") == "success":
            user_role = response.get("role", "authenticated")
            messagebox.showinfo("Success", f"Welcome back, {username}!")
            root.destroy()
            # Sửa: Gọi handle_client_online sau khi login thành công
            print("Attempting to sync local messages to server after login...")
            # --- MODIFIED LINE ---
            # Pass username and the default channel ("General")
            handle_client_online(client_socket, username, "General")
            # --- END MODIFIED LINE ---
            main_screen(client_socket, username, user_role)
        elif response: # Sửa: Xử lý lỗi cụ thể hơn
            messagebox.showerror("Error", f"Login failed: {response.get('message', 'Unknown error')}")
        else: # Sửa: Xử lý trường hợp không có response
             messagebox.showerror("Error", "Login failed. No response from server.")

    def handle_register():
        username = username_entry.get()
        password = password_entry.get()
        if not username or not password:
            messagebox.showwarning("Warning", "Please enter both username and password.")
            return
        response = login(client_socket, username=username, password=password, register=True)
        # Sửa: Kiểm tra response trước khi gọi get
        if response and response.get("status") == "success":
            messagebox.showinfo("Success", "Registration successful! Please log in.")
        elif response: # Sửa: Xử lý lỗi cụ thể hơn
            messagebox.showerror("Error", f"Registration failed: {response.get('message', 'Username might already exist')}")
        else: # Sửa: Xử lý trường hợp không có response
            messagebox.showerror("Error", "Registration failed. No response from server.")

    def handle_guest():
        visitor_name = username_entry.get()
        if not visitor_name:
            messagebox.showwarning("Warning", "Please enter a name.")
            return
        response = login(client_socket, visitor_name=visitor_name)
        # Sửa: Kiểm tra response trước khi gọi get
        if response and response.get("status") == "success":
            user_role = "guest"
            messagebox.showinfo("Success", f"Welcome, {visitor_name}!")
            root.destroy()
            # Guests usually don't sync local messages TO server, but might sync FROM
            # handle_client_online(client_socket) # Decide if guests should sync
            main_screen(client_socket, visitor_name, user_role)
        elif response: # Sửa: Xử lý lỗi cụ thể hơn
            messagebox.showerror("Error", f"Guest login failed: {response.get('message', 'Unknown error')}")
        else: # Sửa: Xử lý trường hợp không có response
            messagebox.showerror("Error", "Guest login failed. No response from server.")

    root = tk.Tk()
    root.title("Login/Register")
    root.geometry("400x300")

    tk.Label(root, text="Username:").pack(pady=5)
    username_entry = tk.Entry(root)
    username_entry.pack(pady=5)

    tk.Label(root, text="Password:").pack(pady=5)
    password_entry = tk.Entry(root, show="*")
    password_entry.pack(pady=5)

    tk.Button(root, text="Login", command=handle_login).pack(pady=5)
    tk.Button(root, text="Register", command=handle_register).pack(pady=5)
    tk.Button(root, text="Login as Guest", command=handle_guest).pack(pady=5)

    root.mainloop()

# --- Main Screen ---
def main_screen(client_socket, username, user_role):
    global current_channel, shown_messages, online_users_list, offline_users_list
    global user_status_update_job, sync_thread_running
    # Make message_entry and send_button global within this scope
    global message_entry, send_button
    global notified_livestreams
    current_channel = "General"
    shown_messages = set()
    # Không reset user_status_update_job và sync_thread_running ở đây

    root = tk.Tk()
    root.title(f"Chat Client - {username} ({user_role})")
    root.geometry("1000x600")
    current_status = tk.StringVar(value="Online") # Default status for authenticated users

    # --- Top Bar ---
    top_frame = tk.Frame(root)
    top_frame.pack(fill=tk.X, pady=5)

    channel_label = tk.Label(top_frame, text=f"Channel: {current_channel}", font=("Arial", 16))
    channel_label.pack(side=tk.LEFT, padx=10)

    # Frame for Search, Toggle
    search_frame = tk.Frame(top_frame)
    # Sửa: Pack search_frame vào top_frame
    search_frame.pack(side=tk.RIGHT, padx=10)
 # --- Livestream Handling ---
    def handle_start_livestream():
        if user_role == "guest":
            messagebox.showerror("Permission Denied", "Guests cannot start a livestream.")
            return
        if not client_socket or client_socket.fileno() == -1:
            messagebox.showerror("Error", "Not connected to server.")
            return

        # Ask for a port (optional, could use a default or dynamic one)
        # For simplicity, let's use a default port for now, e.g., 5001
        # IMPORTANT: Ensure this port is open/forwarded if testing across different networks.
        livestream_port = 5001 # You might want to make this configurable or dynamic

        messagebox.showinfo("Livestream", f"Attempting to start livestream on port {livestream_port}...")

        # Run start_livestream in a separate thread to avoid blocking the UI
        # It needs the main client_socket to send the initial notification to the server
        threading.Thread(
            target=start_livestream,
            # Pass the main client_socket, channel, username, and the chosen P2P port
            args=("0.0.0.0", livestream_port, client_socket, current_channel, username),
            daemon=True
        ).start()
    def handle_join_livestream(event, msg_key):
        """Called when a user clicks a livestream link."""
        if msg_key not in livestream_links:
            messagebox.showerror("Error", "Livestream link information not found.")
            return

        stream_info = livestream_links[msg_key]
        host = stream_info.get("host")
        port = stream_info.get("port")

        if not host or not port:
            messagebox.showerror("Error", "Invalid livestream link information (missing host or port).")
            return

        messagebox.showinfo("Join Livestream", f"Attempting to connect to {host}:{port}...")

        # Connect and receive in a separate thread
        def join_and_receive():
            peer_socket = connect_to_peer(host, port)
            if peer_socket:
                # receive_stream will block until the stream ends or 'q' is pressed
                receive_stream(peer_socket)
                print(f"Stopped receiving stream from {host}:{port}.")
            else:
                # Show error in the main thread using 'after'
                root.after(0, messagebox.showerror, "Connection Failed", f"Could not connect to livestream at {host}:{port}.")

        threading.Thread(target=join_and_receive, daemon=True).start()
#--------------------------------------------USER LIST--------------------------------------------
    # --- Right Panel (User List) ---
    right_frame = tk.Frame(root, width=200, bg="lightgray")
    # Không pack right_frame ban đầu

    tk.Label(right_frame, text="Users Online", bg="lightgray", font=("Arial", 12)).pack(pady=10)
    online_users_list = tk.Listbox(right_frame)
    online_users_list.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

    tk.Label(right_frame, text="Users Offline", bg="lightgray", font=("Arial", 12)).pack(pady=10)
    offline_users_list = tk.Listbox(right_frame)
    offline_users_list.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

# ----------------------------------- Toggle User List Button ----------------------------------
    show_user_list_state = [False] # Use list for mutability
    try:
        toggle_img = Image.open("images/group_people.png").resize((25, 25))
        toggle_photo = ImageTk.PhotoImage(toggle_img)
    except FileNotFoundError:
        print("Warning: group_people.png not found. Using text button.")
        toggle_photo = None # Fallback

    def toggle_user_list():
        # Sửa: Khai báo global nếu cần sửa đổi user_status_update_job
        global user_status_update_job
        if show_user_list_state[0]:
            right_frame.pack_forget()
            show_user_list_state[0] = False
            # Optionally stop polling when hidden
            # if user_status_update_job:
            #     root.after_cancel(user_status_update_job)
            #     user_status_update_job = None
        else:
            fetch_user_status() # Fetch immediately when showing
            right_frame.pack(side=tk.RIGHT, fill=tk.Y)
            show_user_list_state[0] = True
            # Ensure polling starts/continues if not already running
            if not user_status_update_job:
                 schedule_user_status_update()

    if toggle_photo:
        toggle_button = tk.Button(search_frame, image=toggle_photo, command=toggle_user_list, bd=0)
        toggle_button.image = toggle_photo
    else:
        toggle_button = tk.Button(search_frame, text="Users", command=toggle_user_list)
    # Pack nút toggle vào search_frame
    toggle_button.pack(side=tk.LEFT, padx=5) # Đặt trước search_entry

# ---------------------------------------Search -----------------------------------------
    
    search_entry = tk.Entry(search_frame, width=20)
    search_entry.insert(0, "")
    search_entry.pack(side=tk.LEFT, padx=5) # Pack search_entry vào search_frame

    def search_users(event=None):
        global online_users, offline_users # Use global lists as the source
        search_term = search_entry.get().lower()

        # Clear existing listbox content
        if online_users_list and online_users_list.winfo_exists():
            online_users_list.delete(0, tk.END)
        if offline_users_list and offline_users_list.winfo_exists():
            offline_users_list.delete(0, tk.END)

        # If search term is empty, show all users
        if not search_term:
            if online_users_list and online_users_list.winfo_exists():
                for user in online_users:
                    online_users_list.insert(tk.END, user)
            if offline_users_list and offline_users_list.winfo_exists():
                for user in offline_users:
                    offline_users_list.insert(tk.END, user)
        else:
            # Filter online based on the global list
            filtered_online = [user for user in online_users if search_term in user.lower()]
            if online_users_list and online_users_list.winfo_exists():
                for user in filtered_online:
                    online_users_list.insert(tk.END, user)

            # Filter offline based on the global list
            filtered_offline = [user for user in offline_users if search_term in user.lower()]
            if offline_users_list and offline_users_list.winfo_exists():
                for user in filtered_offline:
                    offline_users_list.insert(tk.END, user)

    search_entry.bind("<Return>", search_users)
    # Add binding for KeyRelease to update dynamically
    search_entry.bind("<KeyRelease>", search_users)
    # --- Left Panel (Status, Channels, Avatar) ---
    left_frame = tk.Frame(root, width=200, bg="lightgray")
    left_frame.pack(side=tk.LEFT, fill=tk.Y)

    # --- Status Module ---
    def update_status(new_status):
            global message_entry, send_button # Ensure access to global widgets

            if user_role != "authenticated":
                messagebox.showerror("Permission Denied", "Guests cannot change status.")
                return

            # Store previous status before attempting change
            previous_status = current_status.get().lower()

            if not client_socket or client_socket.fileno() == -1:
                messagebox.showerror("Error", "Lost connection to server.")
                # Force disable input if connection lost
                update_widget_state(message_entry, "disabled")
                update_widget_state(send_button, "disabled")
                return

            try:
                response = change_status(client_socket, username=username, status=new_status)
                if response and response.get("status") == "success":
                    current_status.set(new_status.capitalize())
                    messagebox.showinfo("Success", f"Status changed to {new_status}.")
                    fetch_user_status() # Fetch user list immediately

                    # --- REVISED WIDGET STATE LOGIC ---
                    # Enable input for 'online' and 'invisible' (if authenticated)
                    # Disable input for if guest
                
                    if user_role == "authenticated":
                        update_widget_state(message_entry, "normal")
                        update_widget_state(send_button, "normal")
                    else: # Guest should always be disabled
                        update_widget_state(message_entry, "disabled")
                        update_widget_state(send_button, "disabled")

                    # --- END REVISED LOGIC ---

                    # --- Trigger Sync on going Online ---
                    # If user was 'offline' and is now 'online', sync local messages
                    if previous_status == "offline" and new_status in ["online", "invisible"]:
                        print("Status changed from Offline to Online/Invisible. Syncing local messages...")
                        # Run sync in a separate thread to avoid blocking UI
                        # --- MODIFIED LINE ---
                        threading.Thread(target=handle_client_online, args=(client_socket, username, current_channel), daemon=True).start()
                    # --- End Sync Trigger ---

                elif response:
                    messagebox.showerror("Error", f"Failed to change status: {response.get('message', 'Unknown error')}")
                    # Revert UI status if server failed
                    current_status.set(previous_status.capitalize())
                else:
                    messagebox.showerror("Error", "Failed to change status: No response from server.")
                    # Revert UI status if no response
                    current_status.set(previous_status.capitalize())
            except Exception as e:
                messagebox.showerror("Error", f"Error changing status: {e}")
                # Force disable input on error and revert UI status
                update_widget_state(message_entry, "disabled")
                update_widget_state(send_button, "disabled")
                current_status.set(previous_status.capitalize())


 # Display status differently for guests vs authenticated users
    if user_role == "guest":
        guest_frame = tk.Frame(left_frame, bg="white", bd=1, relief=tk.SOLID)
        guest_frame.pack(pady=8, padx=8, fill=tk.X)
        guest_status_label = tk.Label(guest_frame, text="Guest", bg="white", font=("Arial", 12))
        guest_status_label.pack(padx=10, pady=5)
    else: # Authenticated user
        status_button = tk.Menubutton(left_frame, textvariable=current_status, relief=tk.RAISED, bg="white", font=("Arial", 12), width=12)
        status_menu = tk.Menu(status_button, tearoff=0)
        status_button.config(menu=status_menu)
        status_menu.add_command(label="Online", command=lambda: update_status("online"))
        status_menu.add_command(label="Offline", command=lambda: update_status("offline"))
        status_menu.add_command(label="Invisible", command=lambda: update_status("invisible"))
        status_button.pack(pady=10, padx=10, fill=tk.X)       

    # --- Channel Module ---
    button_width = 14
    button_height = 2

    def handle_create_channel():
        if user_role == "guest": return
        channel_name = simpledialog.askstring("Create Channel", "Enter new channel name:")
        if channel_name:
            response = send_create_channel_request(client_socket, channel_name, username)
            # Sửa: Kiểm tra response trước khi gọi get
            if response and response.get("status") == "success":
                messagebox.showinfo("Success", f"Channel '{channel_name}' created!")
            elif response:
                messagebox.showerror("Error", f"Failed to create channel: {response.get('message')}")
            else:
                 messagebox.showerror("Error", "Failed to create channel: No response from server.")

    # Sửa: Chỉ tạo nút Create Channel một lần
    create_channel_button = tk.Button(left_frame, text="Create Channel", command=handle_create_channel, width=button_width, height=button_height)
    if user_role == "guest":
        create_channel_button.config(state="disabled")
    create_channel_button.pack(pady=10, padx=10)
    # Bỏ khối if user_role == "guest": thứ hai

    def handle_join_channel():
        # Sửa: Khai báo global để sửa đổi
        global current_channel, shown_messages, user_status_update_job, sync_thread_running, notified_livestreams
        try:
            response_data = list_channels(client_socket)
            if not response_data or response_data.get("status") != "success":
                messagebox.showerror("Error", f"Unable to retrieve channel list: {response_data.get('message', 'Unknown error')}")
                return

            channels = response_data.get("channels", [])
            if not channels:
                messagebox.showinfo("Info", "No channels available.")
                return

            join_window = tk.Toplevel(root)
            join_window.title("Join Channel")
            tk.Label(join_window, text="Select a channel:").pack(pady=5)
            channel_listbox = tk.Listbox(join_window)
            for channel in channels: channel_listbox.insert(tk.END, channel)
            channel_listbox.pack(pady=5, fill=tk.X, expand=True)

            def confirm_join():
                # Sửa: Khai báo global để sửa đổi
                global current_channel, shown_messages, user_status_update_job, sync_thread_running
                selected = channel_listbox.curselection()
                if selected:
                    selected_channel = channel_listbox.get(selected)
                    if selected_channel == current_channel:
                         messagebox.showinfo("Info", f"You are already in channel '{current_channel}'.")
                         join_window.destroy()
                         return

                    join_response = send_join_channel_request(client_socket, username, selected_channel)

                    if join_response and join_response.get("status") == "success":
                        # Stop existing sync/poll before changing channel
                        sync_thread_running = False # Signal sync thread to stop
                        if user_status_update_job:
                            try: root.after_cancel(user_status_update_job)
                            except: pass
                            user_status_update_job = None

                        # Update channel state
                        current_channel = selected_channel
                        channel_label.config(text=f"Channel: {current_channel}")
                        join_window.destroy()

                        # Clear UI and memory for new channel
                        chat_display.configure(state="normal")
                        chat_display.delete('1.0', tk.END)
                        chat_display.configure(state="disabled")
                        shown_messages = set()
                        livestream_links = {}
                        notified_livestreams = set()
                        if online_users_list: online_users_list.delete(0, tk.END)
                        if offline_users_list: offline_users_list.delete(0, tk.END)
                        online_users = []
                        offline_users = []

                        # Ensure user list panel visibility is correct
                        if show_user_list_state[0]:
                            right_frame.pack(side=tk.RIGHT, fill=tk.Y)
                        else:
                            right_frame.pack_forget()

                        # Sync and start polling for the new channel
                        sync_messages() # Sync messages immediately
                        fetch_user_status() # Fetch user list immediately
                        start_auto_sync(interval=3) # Start message sync thread
                        schedule_user_status_update() # Start user list polling

                        messagebox.showinfo("Success", f"Joined channel '{current_channel}' successfully!")
                    elif join_response:
                        messagebox.showerror("Error", f"Failed to join channel: {join_response.get('message')}")
                    else:
                        messagebox.showerror("Error", "Failed to join channel: No response from server.")
                else:
                    messagebox.showwarning("Warning", "Please select a channel.")

            tk.Button(join_window, text="Join", command=confirm_join).pack(pady=5)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to retrieve channel list: {e}")

    tk.Button(left_frame, text="Join Channel", command=handle_join_channel, width=button_width, height=button_height).pack(pady=10, padx=10)

    def handle_delete_channel():
        if user_role == "guest": return
        try:
            response_data = list_channels(client_socket)
            # Sửa: Kiểm tra response trước khi gọi get
            if not response_data or response_data.get("status") != "success":
                messagebox.showerror("Error", f"Failed to retrieve channels: {response_data.get('message', 'Unknown error')}")
                return

            channels = response_data.get("channels", [])
            if not channels:
                messagebox.showinfo("Info", "No channels available.")
                return

            delete_window = tk.Toplevel(root)
            delete_window.title("Delete Channel")
            tk.Label(delete_window, text="Select a channel to delete:").pack(pady=5)
            channel_listbox = tk.Listbox(delete_window)
            for channel in channels: channel_listbox.insert(tk.END, channel)
            channel_listbox.pack(pady=5, fill=tk.X, expand=True)

            def confirm_delete():
                selected = channel_listbox.curselection()
                if selected:
                    selected_channel = channel_listbox.get(selected)
                    if selected_channel == "General":
                        messagebox.showerror("Error", "Cannot delete the 'General' channel.")
                        return
                    response = send_delete_channel_request(client_socket, selected_channel, username)
                    # Sửa: Kiểm tra response trước khi gọi get
                    if response and response.get("status") == "success":
                        messagebox.showinfo("Success", f"Channel '{selected_channel}' deleted!")
                        delete_window.destroy()
                        # If the deleted channel was the current one, potentially move to General
                        if current_channel == selected_channel:
                            print(f"Current channel '{selected_channel}' was deleted. Consider joining 'General'.")
                            # Optionally auto-join General here by calling relevant parts of confirm_join
                    elif response:
                        messagebox.showerror("Error", f"Failed to delete channel: {response.get('message')}")
                    else:
                        messagebox.showerror("Error", "Failed to delete channel: No response from server.")
                else:
                    messagebox.showwarning("Warning", "Please select a channel.")

            tk.Button(delete_window, text="Delete", command=confirm_delete).pack(pady=5)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to fetch channels: {e}")

    delete_channel_button = tk.Button(left_frame, text="Delete Channel", command=handle_delete_channel, width=button_width, height=button_height)
    if user_role == "guest": 
        delete_channel_button.config(state="disabled")
    delete_channel_button.pack(pady=10, padx=10)
#---------------------------------------LIVESTREAM-------------------------------------

    start_livestream_button = tk.Button(left_frame, text="Start Livestream", command=handle_start_livestream, width=button_width, height=button_height)
    if user_role == "guest":
        start_livestream_button.config(state="disabled")
    start_livestream_button.pack(pady=10, padx=10)

# ------------------------------------- Chat Area -------------------------------------------------------------

    chat_frame = tk.Frame(root, bg="white", relief=tk.SUNKEN, borderwidth=2)
    chat_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

    chat_display = tk.Text(chat_frame, state="disabled", height=20, width=80, wrap=tk.WORD, bg="#f0f0f0") # Lighter gray
    chat_display.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")

    message_entry = tk.Entry(chat_frame, width=60)
    message_entry.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
    if user_role == "guest": message_entry.config(state="disabled")

    chat_frame.grid_rowconfigure(0, weight=1)
    chat_frame.grid_columnconfigure(0, weight=1)

    # --- Message Handling ---
    def update_chat_display(messages_list):
        global shown_messages, livestream_links, notified_livestreams
        if not chat_display.winfo_exists(): return # Avoid error if widget destroyed
        chat_display.configure(state="normal")
        new_message_added = False
        messages_list.sort(key=lambda x: x.get('timestamp', ''))

        for msg in messages_list:
            ts = msg.get('timestamp', '')
            usr = msg.get('username', '')
            content = msg.get('message', '')
            event_type = msg.get('event_type') # Lấy event_type từ tin nhắn
            # msg_key nên bao gồm event_type cho tin nhắn hệ thống để đảm bảo tính duy nhất
            msg_key = f"{ts}_{usr}_{event_type if event_type else ''}_{hash(content[:20])}"

            if msg_key and isinstance(msg, dict) and usr and ts:
                if msg_key not in shown_messages:
                    shown_messages.add(msg_key)
                    display_time_str = ts
                    try:
                        if display_time_str.endswith('Z'): display_time_str = display_time_str[:-1] + '+00:00'
                        parsed_time = datetime.datetime.fromisoformat(display_time_str)
                        formatted_time = parsed_time.strftime("%H:%M:%S")
                    except ValueError: formatted_time = "??:??:??"

                    is_livestream_notification = (
                        msg.get("message") == "LIVESTREAM_START" and # Hoặc có thể dùng event_type nếu server gửi
                        "streamer" in msg and "host" in msg and "port" in msg
                    )

                    is_user_join_notification = (
                        usr == "System" and
                        event_type == "USER_JOINED_CHANNEL"
                    )

                    # --- BEGIN MODIFICATION: Check for user disconnect notification ---
                    is_user_disconnect_notification = (
                        usr == "System" and
                        event_type == "USER_DISCONNECTED"
                    )
                    # --- END MODIFICATION ---

                    if is_livestream_notification:
                        if msg_key not in notified_livestreams:
                            notified_livestreams.add(msg_key)
                            streamer = msg["streamer"]
                            host = msg["host"]
                            port = msg["port"]
                            livestream_links[msg_key] = {"host": host, "port": port}
                            link_tag = f"livestream_{msg_key}"
                            display_text = f"[{formatted_time}] System: User '{streamer}' started a livestream. "
                            chat_display.insert(tk.END, display_text)
                            chat_display.insert(tk.END, "[Click to Join]", (link_tag, "link"))
                            chat_display.insert(tk.END, "\n")
                            chat_display.tag_config(link_tag, foreground="blue", underline=True)
                            chat_display.tag_bind(link_tag, "<Button-1>", lambda event, key=msg_key: handle_join_livestream(event, key))
                            chat_display.tag_config("link", foreground="blue", underline=True)
                    elif is_user_join_notification:
                        join_notification_tag = "user_joined_event"
                        chat_display.insert(tk.END, f"[{formatted_time}] ", "timestamp_style") 
                        chat_display.insert(tk.END, f"{usr}: {content}\n", join_notification_tag)
                        chat_display.tag_config(join_notification_tag, foreground="green", font=("Arial", 10, "italic"))
                        chat_display.tag_config("timestamp_style", foreground="gray") 
                    # elif is_user_disconnect_notification:
                    #     disconnect_notification_tag = "user_disconnected_event"
                    #     chat_display.insert(tk.END, f"[{formatted_time}] ", "timestamp_style")
                    #     chat_display.insert(tk.END, f"{usr}: {content}\n", disconnect_notification_tag)
                    #     chat_display.tag_config(disconnect_notification_tag, foreground="orange", font=("Arial", 10, "italic"))
                    #     chat_display.tag_config("timestamp_style", foreground="gray")
                    # --- BEGIN MODIFICATION: Handle display for user disconnect ---
                # Optional: Style the disconnect message (e.g., orange, italic)
                    # --- END MODIFICATION ---
                    else:
                        # Regular message display (bao gồm các tin nhắn hệ thống khác nếu có)
                        chat_display.insert(tk.END, f"[{formatted_time}] {usr}: {content}\n")

                    new_message_added = True
            else: print(f"Skipping invalid message format or missing key fields: {msg}")

        if new_message_added: chat_display.see(tk.END)
        chat_display.configure(state="disabled")
    def sync_messages():
        # Ensure username is accessible here (it is, as it's passed to main_screen)
        if not current_channel or not client_socket or client_socket.fileno() == -1: return
        try:
            # This function in client/main.py should also be aware of PUSH messages
            # and not log an error if it receives one instead of a direct sync response.
            response = request_sync_from_server(client_socket, current_channel, username)

            if not response:
                safe_channel = current_channel.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                print(f"[UI SYNC] Unable to sync messages for {safe_channel}: No response from request_sync_from_server.")
                return # Exit if no response

            # Case 1: Successful sync response from request_sync_from_server
            if response.get("status") == "success":
                messages = response.get("messages", [])
                if root.winfo_exists():
                    root.after(0, update_chat_display, messages)
            
            # Case 2: Server PUSH notification (e.g., new_message broadcast)
            # This might be received if request_sync_from_server picked up a broadcast.
            elif response.get("type") == "channel" and response.get("action") == "new_message" and "message_data" in response:
                print(f"[UI SYNC - PUSH DEBUG] Received a PUSH message during sync attempt: {response}")
                message_data = response['message_data']
                if isinstance(message_data, dict):
                    print(f"[UI SYNC - PUSH] Processing PUSH system message: {message_data}")
                    if root.winfo_exists():
                        root.after(0, update_chat_display, [message_data]) # Display as a single message
                else:
                    print(f"[UI SYNC - PUSH ERROR] Unexpected format for 'message_data' in PUSH message: {message_data}")
            
            # Case 3: Actual error response from the sync request OR other unexpected format
            # This block is reached if status is not "success" AND it's not the specific PUSH message handled above.
            else:
                print(f"[UI SYNC - ERROR DEBUG] Received non-success/non-push response from request_sync_from_server: {response}")
                log_msg_detail = ""
                if 'message' in response: # Check if 'message' key exists (typical for server errors)
                    server_msg_content = response.get('message')
                    log_msg_detail = str(server_msg_content) if server_msg_content is not None else "Server returned an error with null/empty message content."
                elif 'message_data' in response and isinstance(response['message_data'], dict) and 'message' in response['message_data']:
                     log_msg_detail = f"Error response contained 'message_data' with a message: {response['message_data']['message']}"
                elif 'message_data' in response: # Error response has message_data but no nested message
                     log_msg_detail = f"Error response contained 'message_data' but no nested message: {response['message_data']}"
                else:
                    log_msg_detail = "Server returned an error status without a 'message' or usable 'message_data' field for details."

                try:
                    safe_channel = current_channel.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                    safe_message_detail_for_log = log_msg_detail.encode('utf-8', errors='replace').decode('utf-8', errors='replace') 
                    # This is the problematic log you are seeing
                    print(f"[UI SYNC - FAILED] Failed to sync messages for {safe_channel} (specific error): {safe_message_detail_for_log}")
                except Exception as print_err: 
                    safe_print_err = str(print_err).encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                    print(f"[UI SYNC - Print Error] Could not display sync error message due to: {safe_print_err}")

        except ConnectionError as e:
             try:
                 safe_e = str(e).encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                 print(f"[UI SYNC - Connection Error] Connection lost during sync: {safe_e}")
             except Exception as print_err:
                 safe_print_err = str(print_err).encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                 print(f"[UI SYNC - Print Error] Could not display connection error message due to: {safe_print_err}")
        except Exception as e:
             print(f"--- [UI SYNC - UNEXPECTED ERROR] Unexpected error during message sync ---") 
             try:
                 error_type = type(e).__name__
                 error_msg = str(e)
                 print(f"Error Type: {error_type}")
                 safe_error_msg = error_msg.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                 print(f"Error Message: {safe_error_msg}")

                 print("Traceback:")
                 import traceback # Ensure traceback is imported
                 tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
                 for line in tb_lines:
                     try:
                         safe_line = line.strip().encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                         print(safe_line)
                     except Exception as print_tb_line_err:
                         safe_tb_err = str(print_tb_line_err).encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                         print(f"[Error printing traceback line: {safe_tb_err}]")
             except Exception as print_err: 
                  safe_print_err = str(print_err).encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                  print(f"[UI SYNC - Critical Error] Unexpected error during message sync AND error printing exception details: {safe_print_err}")
             print(f"--- End of unexpected error details ---")
    def start_auto_sync(interval=3):
        global sync_thread_running
        if sync_thread_running: return

        def auto_sync_loop():
            global sync_thread_running
            sync_thread_running = True
            print(f"Auto-sync thread started (interval: {interval}s).")
            # Sửa: Dùng while sync_thread_running
            while sync_thread_running:
                if client_socket and client_socket.fileno() != -1:
                    try: sync_messages()
                    except Exception as e: print(f"Error in auto-sync loop: {e}")
                else:
                    print("Auto-sync stopping: Invalid socket.")
                    sync_thread_running = False # Stop if socket invalid
                    # Không cần break vì vòng lặp sẽ tự thoát

                # Check flag again before sleeping
                if sync_thread_running:
                    time.sleep(interval)

            print("Auto-sync thread has stopped.")
            # sync_thread_running = False # Đã đặt ở trên

        sync_thread = threading.Thread(target=auto_sync_loop, name='AutoSyncThread', daemon=True)
        sync_thread.start()

    # --------------------------------------- Send Message ------------------------------
    def handle_send_message(event=None):
        global message_entry, send_button # Ensure access

        # 1. Check User Role
        if user_role == "guest":
            messagebox.showerror("Permission Denied", "Guests cannot send messages.")
            return

        message = message_entry.get()
        if not message: return
        if not current_channel:
            messagebox.showwarning("Warning", "Please select or join a channel first.")
            return

        # 2. Check User Status
        current_status_lower = current_status.get().lower()

        if current_status_lower in ["online", "invisible"]:
            # --- Send via Server ---
            try:
                response = send_message(client_socket, current_channel, message, username)

                if response:
                    response_status = response.get("status")
                    if response_status == "success":
                        message_entry.delete(0, tk.END)
                        # Optional: Immediately display sent message if server confirms
                        sent_message_data = response.get("message_data")
                        if sent_message_data and root.winfo_exists():
                             root.after(0, update_chat_display, [sent_message_data])
                    elif response_status == "offline_save":
                        # This case *shouldn't* happen if status is online/invisible,
                        # but handle defensively: means connection was lost during send.
                        messagebox.showwarning("Connection Lost", response.get("message", "Connection lost. Message saved locally."))
                        message_entry.delete(0, tk.END)
                        update_widget_state(message_entry, "disabled")
                        update_widget_state(send_button, "disabled")
                        # Update UI status to reflect likely disconnection? Maybe Offline?
                        # current_status.set("Offline") # Or trigger update_status("offline")? Careful with loops.
                    else:
                        # Server returned an error (e.g., validation, permissions)
                        messagebox.showerror("Send Error", response.get("message", "Unable to send message."))
                        # Do not delete message from entry if server rejected it
                else:
                    # No response from send_message (likely connection error)
                    messagebox.showerror("Error", "Failed to send message: No response from server. Saving locally.")
                    save_local_message(current_channel, username, message) # Save locally
                    message_entry.delete(0, tk.END)
                    update_widget_state(message_entry, "disabled")
                    update_widget_state(send_button, "disabled")
                    # current_status.set("Offline") # Consider updating status UI

            except Exception as e:
                # <<<=== SỬA KHỐI NÀY ===>>>
                # Attempt to print unexpected error and traceback safely using UTF-8
                print(f"--- Unexpected UI error sending message ---") # Header
                try:
                    # Print the error type and message safely
                    error_type = type(e).__name__
                    error_msg = str(e)
                    print(f"Error Type: {error_type}")
                    # Encode the error message explicitly using UTF-8
                    safe_error_msg = error_msg.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                    print(f"Error Message: {safe_error_msg}")

                    # Print traceback line by line safely
                    print("Traceback:")
                    import traceback
                    tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
                    for line in tb_lines:
                        try:
                            # Encode each line of the traceback using UTF-8
                            safe_line = line.strip().encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                            print(safe_line)
                        except Exception as print_tb_line_err:
                            # Fallback if even encoding fails for a line
                            safe_tb_err = str(print_tb_line_err).encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                            print(f"[Error printing traceback line: {safe_tb_err}]")

                except Exception as print_err: # Catch errors during printing exception/traceback itself
                     # Fallback if printing the details fails, encode the print error itself
                     safe_print_err = str(print_err).encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                     print(f"[Critical Error] Unexpected error during message send AND error printing exception details: {safe_print_err}")
                print(f"--- End of unexpected error details ---") # Footer
                # <<<=== KẾT THÚC SỬA ===>>>

                messagebox.showerror("Error", f"An unexpected error occurred. Saving locally.") # Keep message simple for user
                save_local_message(current_channel, username, message) # Save locally on unexpected error
                message_entry.delete(0, tk.END)
                update_widget_state(message_entry, "disabled")
                update_widget_state(send_button, "disabled")
                # current_status.set("Offline") # Consider updating status UI

        elif current_status_lower == "offline":
            # --- Save Locally ---
            print("Status is Offline. Saving message locally.")
            save_local_message(current_channel, username, message)
            messagebox.showinfo("Offline", "You are offline. Message saved locally and will be sent when you go online.")
            message_entry.delete(0, tk.END)
            # Input should already be disabled, but ensure it is.
            # update_widget_state(message_entry, "disabled")
            # update_widget_state(send_button, "disabled")

        else: # Should not happen (e.g., 'Guest' status for authenticated user?)
             messagebox.showerror("Error", f"Cannot send message with current status: {current_status.get()}")

    # Assign to global variable
    send_button = tk.Button(chat_frame, text="Send", command=handle_send_message)
    send_button.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
    message_entry.bind("<Return>", handle_send_message)

    if user_role == "guest":
        update_widget_state(message_entry, "disabled")
        update_widget_state(send_button, "disabled")
    else: # Authenticated
        # Initial status is 'Online' by default
        if current_status.get() == "Online":
             update_widget_state(message_entry, "normal")
             update_widget_state(send_button, "normal")
        else: # Should not happen initially, but handle defensively
             update_widget_state(message_entry, "disabled")
             update_widget_state(send_button, "disabled")

    # --- User List Update Logic ---
    def fetch_user_status():
        global online_users, offline_users
        # Thêm kiểm tra socket và kênh trước khi thực hiện
        if not current_channel or not client_socket or client_socket.fileno() == -1:
            # print("Skipping fetch_user_status: No channel or invalid socket.") # Bỏ comment nếu cần debug sâu hơn
            return
        try:
            # print(f"Fetching user status for channel: {current_channel}") # Bỏ comment nếu cần debug
            response = list_online_users(client_socket, current_channel)
            # !!! QUAN TRỌNG: In ra phản hồi từ server để chẩn đoán !!!
            print(f"[DEBUG UI - fetch_user_status] Server response for user list ({current_channel}): {response}") # Bỏ comment dòng này

            if response and response.get("status") == "success":
                new_online = response.get("online", [])
                new_offline = response.get("offline", [])

                # Chỉ cập nhật nếu danh sách thực sự thay đổi
                if new_online != online_users:
                    online_users = new_online
                    if online_users_list and online_users_list.winfo_exists():
                        online_users_list.delete(0, tk.END) # Xóa listbox online
                        for user in online_users:
                            online_users_list.insert(tk.END, user) # Thêm lại user online

                if new_offline != offline_users:
                    offline_users = new_offline
                    if offline_users_list and offline_users_list.winfo_exists():
                        offline_users_list.delete(0, tk.END) # Xóa listbox offline
                        for user in offline_users:
                            offline_users_list.insert(tk.END, user) # Thêm lại user offline

            # Xử lý trường hợp server báo lỗi hoặc không có status success
            elif response:
                 # Attempt to print server error safely
                 error_message = response.get('message', 'Unknown server error fetching status')
                 try:
                     print(f"Error fetching user status (Server Error): {error_message}")
                 except UnicodeEncodeError:
                     safe_message = str(error_message.encode('utf-8', errors='replace'))
                     print(f"Error fetching user status (Server Error): [Encoding Error] {safe_message}")
            else:
                 # Trường hợp không nhận được phản hồi nào
                 print("Error fetching user status: No response from server.")

        except ConnectionError as e:
            # Attempt to print connection error safely
            try:
                print(f"Connection lost while fetching user status: {e}")
            except UnicodeEncodeError:
                safe_e = str(e).encode('utf-8', errors='replace')
                print(f"Connection lost while fetching user status: [Encoding Error] {safe_e}")
            # Cân nhắc xóa danh sách trên UI khi mất kết nối
            # if online_users_list and online_users_list.winfo_exists(): online_users_list.delete(0, tk.END)
            # if offline_users_list and offline_users_list.winfo_exists(): offline_users_list.delete(0, tk.END)
            # online_users, offline_users = [], []
        except Exception as e:
            # <<<=== SỬA KHỐI NÀY ===>>>
            # Attempt to print unexpected error and traceback safely using UTF-8
            print(f"--- Unexpected error in fetch_user_status ---") # Header
            try:
                # Print the error type and message safely
                error_type = type(e).__name__
                error_msg = str(e)
                print(f"Error Type: {error_type}")
                # Encode the error message explicitly using UTF-8
                safe_error_msg = error_msg.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                print(f"Error Message: {safe_error_msg}")

                # Print traceback line by line safely
                print("Traceback:")
                import traceback
                tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
                for line in tb_lines:
                    try:
                        # Encode each line of the traceback using UTF-8
                        safe_line = line.strip().encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                        print(safe_line)
                    except Exception as print_tb_line_err:
                        # Fallback if even encoding fails for a line
                        safe_tb_err = str(print_tb_line_err).encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                        print(f"[Error printing traceback line: {safe_tb_err}]")

            except Exception as print_err: # Catch errors during printing exception/traceback itself
                 # Fallback if printing the details fails, encode the print error itself
                 safe_print_err = str(print_err).encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                 print(f"[Critical Error] Unexpected error during fetch_user_status AND error printing exception details: {safe_print_err}")
            print(f"--- End of unexpected error details ---") # Footer
            # <<<=== KẾT THÚC SỬA ===>>>

    def schedule_user_status_update(interval_ms=5000):
        global user_status_update_job
        # Check if polling should run
        if client_socket and client_socket.fileno() != -1 and current_channel and root.winfo_exists():
            fetch_user_status()
            # Schedule the next call
            user_status_update_job = root.after(interval_ms, schedule_user_status_update, interval_ms)
        else:
            # Stop polling if conditions aren't met
            user_status_update_job = None
            print("User status polling stopped.")

    # --- Avatar + Username ---
    avatar_frame = tk.Frame(left_frame, bg="lightgray")
    avatar_frame.pack(side=tk.BOTTOM, pady=20, fill=tk.X)
    try:
        user_img = Image.open("images/user.png").resize((40, 40))
        user_photo = ImageTk.PhotoImage(user_img)
        avatar_label = tk.Label(avatar_frame, image=user_photo, bg="lightgray")
        avatar_label.image = user_photo
        avatar_label.pack(side=tk.LEFT, padx=5)
    except FileNotFoundError:
        print("Warning: user.png not found.")
    except Exception as e:
        print(f"Error loading avatar: {e}")

    username_label = tk.Label(avatar_frame, text=username, font=("Arial", 10), bg="lightgray")
    username_label.pack(side=tk.LEFT, padx=5)

    # --- Initial Load and Startup ---
    # Fetch initial messages and user list for the default "General" channel
    sync_messages()
    fetch_user_status() # Fetch initial user list

    # Start auto-sync threads/schedules
    start_auto_sync(interval=3) # Start message sync
    schedule_user_status_update(interval_ms=5000) # Start user list polling

    # --- Cleanup on Close ---
    def on_closing():
        global sync_thread_running, user_status_update_job
        print("Closing application...")
        sync_thread_running = False # Signal sync thread to stop
        if user_status_update_job:
            try: root.after_cancel(user_status_update_job)
            except: pass
        # Socket closing and cache saving are handled by the finally block in main()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

def main():
    # Load local cache happens before connect
    load_local_cache() # Ensure cache is loaded at the start

    client_socket = connect_to_server()
    if not client_socket:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Connection Error", "Failed to connect to the server. Please check the server and your network connection.")
        root.destroy()
        save_local_cache() # Save cache even on connection failure
        return

    # --- Main application flow ---
    try:
        # Login screen handles auth and initial sync TO server
        login_screen(client_socket)
        # If login_screen completes successfully, it calls main_screen which enters the mainloop.
        # Code here will execute *after* the main Tkinter window is closed.
        print("Main UI window closed.")

    finally:
        # This block executes after the UI window is closed OR if an error occurs during setup
        print("Cleaning up client...")
        save_local_cache() # Save cache on exit
        if client_socket:
            try:
                # Attempt graceful shutdown notification? (Optional)
                # client_socket.send(...)
                print("Closing socket...")
                client_socket.close()
            except Exception as e:
                print(f"Error closing socket: {e}")
        print("Client finished.")

if __name__ == "__main__":
    main() # Start the application from ui.py