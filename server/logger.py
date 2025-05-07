import os
from datetime import datetime

# Đường dẫn file log
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "server.log")
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB

# Đảm bảo thư mục logs tồn tại
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Hàm ghi log thông tin
def log_info(message):
    with open(LOG_FILE, "a") as log_file:
        log_file.write(f"[INFO] {datetime.now()} - {message}\n")
    print(f"[INFO] {message}")
    clear_logs()

# Hàm ghi log lỗi
def log_error(message):
    with open(LOG_FILE, "a") as log_file:
        log_file.write(f"[ERROR] {datetime.now()} - {message}\n")
    print(f"[ERROR] {message}")
    clear_logs()
def log_warning(message):
    """Logs a warning message using log_info with a prefix."""
    log_info(f"[WARNING] ChannelManager: {message}")
# Hàm xóa log khi vượt quá giới hạn
def clear_logs():
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_SIZE:
        with open(LOG_FILE, "w") as log_file:
            log_file.write(f"[INFO] {datetime.now()} - Log cleared due to size limit\n")
        print("[INFO] Log file cleared due to size limit")