import unittest
from unittest.mock import Mock, patch
from main import create_channel

class TestCreateChannel(unittest.TestCase):
    @patch('main.socket.socket')  # Mock socket
    def test_create_channel_success(self, mock_socket):
        # Mock client socket
        mock_client_socket = Mock()
        mock_socket.return_value = mock_client_socket

        # Mock server response
        mock_client_socket.recv.return_value = b'{"status": "success", "message": "Channel created"}'

        # Call the function
        response = create_channel(mock_client_socket, "test_channel", "test_user")

        # Assertions
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["message"], "Channel created")
        mock_client_socket.send.assert_called_once()

if __name__ == "__main__":
    unittest.main()