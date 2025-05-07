import socket
import cv2
import pickle
import struct
import threading
import json
import time # Added for potential delays/checks

# Define a constant for the stream end signal
STREAM_END_SIGNAL = b"__STREAM_ENDED__"

def handle_client(conn, cap, streamer_active_flag):
    """Xử lý việc gửi dữ liệu video đến client."""
    print(f"Starting to send stream to {conn.getpeername()}")
    try:
        while cap.isOpened() and streamer_active_flag.is_set():
            ret, frame = cap.read()
            if not ret:
                print("Streamer: Cannot read frame from camera or stream ended.")
                break

            # Serialize frame
            try:
                # Optional: Resize frame to reduce bandwidth
                # frame = cv2.resize(frame, (640, 480))
                data = pickle.dumps(frame)
                size = struct.pack("Q", len(data))
            except Exception as e:
                print(f"Streamer: Error serializing frame: {e}")
                continue # Skip this frame

            # Send frame size and data
            try:
                conn.sendall(size)
                conn.sendall(data)
            except (ConnectionResetError, BrokenPipeError, socket.error) as e:
                print(f"Streamer: Connection lost with viewer {conn.getpeername()}: {e}")
                break # Stop sending to this viewer
            except Exception as e:
                 print(f"Streamer: Unexpected error sending frame to {conn.getpeername()}: {e}")
                 break # Stop sending to this viewer

            # Optional: Add a small delay to control frame rate
            # time.sleep(0.03) # ~30 fps

        print(f"Streamer: Stopped sending frames to {conn.getpeername()}.")

    except Exception as e:
        print(f"Streamer: Error in handle_client for {conn.getpeername()}: {e}")
    finally:
        # Send end signal before closing
        try:
            print(f"Streamer: Sending end signal to {conn.getpeername()}")
            conn.sendall(struct.pack("Q", len(STREAM_END_SIGNAL)))
            conn.sendall(STREAM_END_SIGNAL)
        except Exception as e_sig:
            print(f"Streamer: Could not send end signal to {conn.getpeername()}: {e_sig}")
        finally:
             conn.close()
             print(f"Streamer: Closed connection with {conn.getpeername()}")


def start_livestream(host="0.0.0.0", port=5001, client_socket=None, channel_name=None, username=None):
    """Starts the P2P livestream server and notifies the main server."""
    server_socket = None
    cap = None
    streamer_active_flag = threading.Event() # Flag to signal streamer threads to stop
    streamer_active_flag.set() # Start as active

    try:
        # --- 1. Notify the Centralized Server ---
        if client_socket and channel_name and username:
            # The server needs to know the *public* IP and the P2P port
            # The server usually gets the public IP from the client_socket connection.
            # We just need to tell it the P2P port we will listen on.
            request = {
                "type": "livestream",
                "action": "start_livestream",
                "channel_name": channel_name,
                "username": username,
                "port": port # The port viewers should connect to
            }
            try:
                # Add newline for server protocol consistency
                client_socket.sendall((json.dumps(request) + "\n").encode('utf-8'))
                print(f"Livestream start notification sent to server for channel '{channel_name}' on P2P port {port}.")
                # Optionally wait for a confirmation from the server? Depends on server design.
            except (ConnectionError, BrokenPipeError, socket.error) as e:
                 print(f"Error: Failed to send livestream notification to server: {e}. Aborting livestream.")
                 return # Don't start P2P server if notification fails
            except Exception as e:
                 print(f"Error: Unexpected error sending notification: {e}. Aborting livestream.")
                 return
        else:
            print("Error: Missing client_socket, channel_name, or username. Cannot notify server.")
            return

        # --- 2. Set up P2P Server Socket ---
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Allow reusing address quickly
        server_socket.bind((host, port)) # Bind to specified host (e.g., 0.0.0.0 for all interfaces)
        server_socket.listen(5)
        print(f"P2P Livestream server listening on {host}:{port}")

        # --- 3. Open Camera ---
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("Error: Camera not found or cannot be opened.")
            raise RuntimeError("Failed to open camera") # Raise error to trigger finally block

        # --- 4. Local Display Thread (Optional but helpful for streamer) ---
        def display_video():
            print("Starting local camera preview.")
            while cap.isOpened() and streamer_active_flag.is_set():
                ret, frame = cap.read()
                if not ret:
                    print("Local Preview: Cannot read frame.")
                    break
                cv2.imshow(f"My Livestream ({username}) - Press 'q' in this window to stop", frame)
                # Check for 'q' key press to stop the stream
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    print("Local Preview: 'q' pressed, stopping stream.")
                    streamer_active_flag.clear() # Signal other threads to stop
                    break
            print("Local preview thread stopping.")
            # Release resources if this thread initiated the stop
            if not streamer_active_flag.is_set():
                if cap and cap.isOpened():
                    cap.release()
                cv2.destroyAllWindows()
                # Attempt to gracefully close the server socket to stop accepting new connections
                if server_socket:
                    print("Attempting to close server socket...")
                    # Closing the socket here will cause accept() to raise an error in the main loop
                    server_socket.close()
                    print("Server socket closed.")


        display_thread = threading.Thread(target=display_video, daemon=True)
        display_thread.start()

        # --- 5. Accept Viewer Connections ---
        print("Waiting for viewer connections...")
        viewer_threads = []
        while streamer_active_flag.is_set():
            try:
                conn, addr = server_socket.accept() # This will block until a connection or socket is closed
                if not streamer_active_flag.is_set(): # Check flag again after accept returns
                    conn.close()
                    break
                print(f"Viewer connected: {addr}")
                # Pass the flag to the handler thread
                thread = threading.Thread(target=handle_client, args=(conn, cap, streamer_active_flag), daemon=True)
                viewer_threads.append(thread)
                thread.start()
            except socket.error as e:
                # Check if the error is due to the socket being closed intentionally
                if streamer_active_flag.is_set():
                    # If the flag is still set, it's an unexpected error
                    print(f"P2P Server: Socket error during accept: {e}")
                else:
                    # If the flag is cleared, the socket was likely closed intentionally
                    print("P2P Server: Socket closed, stopping accept loop.")
                break # Exit loop on socket error
            except Exception as e:
                 print(f"P2P Server: Unexpected error during accept: {e}")
                 # Decide whether to continue or break based on the error

    except RuntimeError as e: # Catch camera opening error
         print(f"Error starting livestream: {e}")
    except Exception as e:
        print(f"Error in start_livestream main loop: {e}")
    finally:
        print("Cleaning up livestream resources...")
        streamer_active_flag.clear() # Ensure flag is cleared

        if cap and cap.isOpened():
            print("Releasing camera...")
            cap.release()
        print("Destroying OpenCV windows...")
        cv2.destroyAllWindows() # Close preview window if it's still open

        if server_socket:
            print("Closing P2P server socket...")
            try:
                # Ensure the socket is fully closed
                server_socket.close()
            except Exception as e_close:
                print(f"Error closing server socket: {e_close}")

        # Wait briefly for viewer threads to potentially finish sending end signal
        # print("Waiting for viewer threads to finish...")
        # for t in viewer_threads:
        #     t.join(timeout=1.0) # Wait max 1 second per thread

        print("Livestream cleanup finished.")


# Hàm kết nối với peer khác
def connect_to_peer(host, port):
    """Establishes a TCP connection to a peer."""
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.settimeout(10)  # Timeout for connection attempt
        print(f"Attempting to connect to peer at {host}:{port}...")
        client_socket.connect((host, port))
        client_socket.settimeout(None) # Reset timeout after connection
        print(f"Successfully connected to peer at {host}:{port}")
        return client_socket
    except socket.timeout:
        print(f"Connection to peer at {host}:{port} timed out.")
        return None
    except ConnectionRefusedError:
        print(f"Connection to peer at {host}:{port} refused. Is the stream active?")
        return None
    except Exception as e:
        print(f"Error connecting to peer {host}:{port}: {e}")
        return None

# Hàm nhận dữ liệu video từ peer
def receive_stream(client_socket):
    """Receives and displays video frames from a peer connection."""
    if not client_socket:
        print("Viewer: Invalid socket provided to receive_stream.")
        return

    print("Viewer: Starting to receive stream...")
    data = b""
    payload_size = struct.calcsize("Q")
    window_name = f"Viewing Stream from {client_socket.getpeername()}"

    try:
        while True:
            # --- Receive message size ---
            while len(data) < payload_size:
                try:
                    # Use a timeout for recv to prevent indefinite blocking if peer hangs
                    client_socket.settimeout(15.0) # 15 second timeout for receiving data
                    packet = client_socket.recv(4 * 1024)
                    client_socket.settimeout(None) # Reset after successful recv
                except socket.timeout:
                     print("Viewer: Timeout waiting for data from peer. Assuming stream ended.")
                     packet = None # Treat as connection closed
                except (ConnectionResetError, BrokenPipeError, socket.error) as e:
                     print(f"Viewer: Connection lost while receiving size: {e}")
                     packet = None # Treat as connection closed
                except Exception as e:
                     print(f"Viewer: Unexpected error receiving size: {e}")
                     packet = None

                if not packet:
                    print("Viewer: Connection closed by peer (or error) while waiting for size.")
                    return # Exit function if connection closed
                data += packet

            # --- Extract message size ---
            packed_msg_size = data[:payload_size]
            data = data[payload_size:]
            try:
                msg_size = struct.unpack("Q", packed_msg_size)[0]
            except struct.error as e:
                 print(f"Viewer: Error unpacking message size: {e}. Data: {packed_msg_size}")
                 return # Exit on error

            # --- Receive message data ---
            while len(data) < msg_size:
                 try:
                    client_socket.settimeout(15.0)
                    packet = client_socket.recv(4 * 1024)
                    client_socket.settimeout(None)
                 except socket.timeout:
                     print("Viewer: Timeout waiting for data chunk from peer. Assuming stream ended.")
                     packet = None
                 except (ConnectionResetError, BrokenPipeError, socket.error) as e:
                     print(f"Viewer: Connection lost while receiving data: {e}")
                     packet = None
                 except Exception as e:
                     print(f"Viewer: Unexpected error receiving data: {e}")
                     packet = None

                 if not packet:
                    print("Viewer: Connection closed by peer (or error) while waiting for data.")
                    return # Exit function
                 data += packet

            # --- Extract frame data ---
            frame_data = data[:msg_size]
            data = data[msg_size:] # Keep remaining data for next message

            # --- Check for end signal ---
            if frame_data == STREAM_END_SIGNAL:
                print("Viewer: Received stream end signal.")
                break # Exit the loop gracefully

            # --- Deserialize and display frame ---
            try:
                frame = pickle.loads(frame_data)
                cv2.imshow(window_name, frame)
                # Check for 'q' key press to close the window locally
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("Viewer: 'q' pressed, closing stream window.")
                    break # Exit loop
            except pickle.UnpicklingError as e:
                 print(f"Viewer: Error unpickling frame data: {e}. Skipping frame.")
                 continue # Try to receive the next frame
            except Exception as e:
                 print(f"Viewer: Error processing/displaying frame: {e}")
                 # Decide whether to continue or break

    except Exception as e:
        print(f"Viewer: Error in receive_stream loop: {e}")
    finally:
        print("Viewer: Cleaning up receive_stream...")
        if client_socket:
            client_socket.close()
        cv2.destroyAllWindows() # Close the specific window or all windows
        print("Viewer: Stream window closed.")