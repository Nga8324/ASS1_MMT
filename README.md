# Project Title: Chat Application 

## Description

This project is a client-server chat application built with Python. It features real-time messaging in channels, user authentication, status updates, and a peer-to-peer (P2P) livestreaming capability. The client-side user interface is built using Tkinter.

## Features

*   **User Authentication:** Login, registration, and guest access.
*   **Channel-based Chat:** Users can create, join, and delete chat channels. "General" is a default channel.
*   **Real-time Messaging:** Send and receive messages within channels.
*   **User Status:** Users can set their status to Online, Offline, or Invisible.
*   **User Lists:** View online and offline users in the current channel.
*   **Search Users:** Filter the user list by name.
*   **P2P Livestreaming:** Authenticated users can start a livestream within a channel, and other users in that channel can join and view the stream.
*   **Offline Message Caching:** Messages sent while offline or if the server is unreachable are saved locally and synced when back online.
*   **Server-side Management:** The server handles user connections, message broadcasting, channel management, and user status tracking.
*   **Logging:** Both client and server applications maintain logs for debugging and monitoring.

## Setup and Installation

1.  **Prerequisites:**
    *   Python 3.x
    *   `pip` (Python package installer)

2.  **Clone the repository (if applicable):**
    ```bash
    git clone <your-repository-url>
    cd <project-directory>
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *Note: Make sure `requirements.txt` includes all necessary packages like `Pillow` (for PIL/ImageTk) and `opencv-python` (for cv2).*

## Usage

1.  **Start the Server:**
    Navigate to the `server` directory and run the server's main script:
    ```bash
    cd server
    python main.py
    ```
    The server will start listening for client connections.

2.  **Run the Client:**
    Open a new terminal, navigate to the `client` directory, and run the client's UI script:
    ```bash
    cd client
    python ui.py
    ```
    This will open the login/register screen.

3.  **Client Interaction:**
    *   **Login/Register:** Authenticated users can log in with their credentials or register a new account. Guests can log in by providing a name.
    *   **Channels:** Create, join, or delete channels (guests have limited permissions).
    *   **Messaging:** Send messages in the active channel.
    *   **Status:** Authenticated users can change their status (Online, Offline, Invisible).
    *   **User List:** Toggle the user list panel to see online/offline users in the channel. Search for users.
    *   **Livestreaming:**
        *   Authenticated users can click "Start Livestream" to begin broadcasting their webcam.
        *   A notification will appear in the chat for others in the channel.
        *   Users can click the "[Click to Join]" link on the notification to view the livestream.

## Potential Future Enhancements

*   Private (Direct) Messaging
*   Message Editing/Deletion
*   Enhanced Notifications (Desktop, Sound)
*   File Sharing
*   User Profiles & Avatars
*   Message Search
*   Customizable Themes/UI
*   Emoji Support
*   Typing Indicators
*   Advanced Channel Management (Moderation, Invites)

## Project Structure

```
.
├── client/                 # Client-side application
│   ├── main.py             # Client main logic, connection, requests
│   ├── ui.py               # Tkinter-based User Interface
│   ├── peer.py             # P2P livestreaming (sending and receiving)
│   ├── utils.py            # Client utility functions
│   ├── logger.py           # Client-side logging
│   └── client_cache.json   # Local cache for messages
├── server/                 # Server-side application
│   ├── main.py             # Server main logic, connection handling
│   ├── channel_manager.py  # Manages chat channels and messages
│   ├── tracker.py          # (Potentially for P2P peer discovery - if fully implemented)
│   ├── users.json          # Stores user credentials and status
│   ├── channels.json       # Stores channel information
│   ├── shared.py           # Shared data structures for server modules
│   ├── utils.py            # Server utility functions
│   └── logger.py           # Server-side logging
├── images/                 # UI images (user.png, group_people.png)
├── logs/                   # Log files (client.log, server.log)
├── requirements.txt        # Python dependencies
└── README.md               # This file
```


