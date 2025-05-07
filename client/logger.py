import os
from datetime import datetime
import traceback

# Đường dẫn file log
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "client.log")
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB

# Đảm bảo thư mục logs tồn tại
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Hàm ghi log thông tin
def log_info(message):
    with open(LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(f"[INFO] {datetime.now()} - {message}\n")
    print(f"[INFO] {message}")
    clear_logs()

# Hàm ghi log lỗi
def log_error(message, exc_info=False):
    log_entry = f"[ERROR] {datetime.now()} - {message}\n"
    if exc_info:
        log_entry += traceback.format_exc() + "\n"
    with open(LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(log_entry)
    print(f"[ERROR] {message}")
    if exc_info:
        print(traceback.format_exc())
    clear_logs()

# Hàm ghi log cảnh báo
def log_warning(message):
    with open(LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(f"[WARNING] {datetime.now()} - {message}\n")
    print(f"[WARNING] {message}")
    clear_logs()

# Hàm ghi log debug (tùy chọn bật/tắt)
def log_debug(message):
    # print(f"[DEBUG] {datetime.now()} - {message}")
    pass
    # with open(LOG_FILE, "a", encoding="utf-8") as log_file:
    #     log_file.write(f"[DEBUG] {datetime.now()} - {message}\n")
    # clear_logs()

# Hàm xóa log khi vượt quá giới hạn
def clear_logs():
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_SIZE:
            with open(LOG_FILE, "w", encoding="utf-8") as log_file:
                log_file.write(f"[INFO] {datetime.now()} - Log cleared due to size limit\n")
            print("[INFO] Log file cleared due to size limit")
    except Exception as e:
        print(f"[ERROR] Failed to check/clear log file: {e}")
