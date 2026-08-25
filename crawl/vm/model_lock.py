"""
共享模型加载锁 — transcribe_daemon 和 ocr_daemon 共用
路径: /tmp/model-loading.lock
谁先加载模型谁占锁，另一个等到对方释放再继续。
"""
import os, time, fcntl
LOCK_PATH = "/tmp/model-loading.lock"
WAIT_TIMEOUT = 1800  # 最多等30分钟（FunASR加载很慢）
POLL_INTERVAL = 5    # 每5秒轮询一次

def acquire(wait=True):
    """占用锁。如果另一个进程正占着锁，wait=True 时阻塞等待，False 时立即失败。"""
    LOCK_DIR = os.path.dirname(LOCK_PATH)
    os.makedirs(LOCK_DIR, exist_ok=True)
    fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if not wait else 0))
        os.write(fd, f"{os.getpid()}".encode())
        return fd
    except (IOError, OSError):
        os.close(fd)
        return None

def wait_for_unlock():
    """轮询等待另一个进程的模型加载完成（锁文件消失）"""
    waited = 0
    while os.path.exists(LOCK_PATH) and waited < WAIT_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
        print(f"[model-lock] 等待另一个进程释放模型加载锁 ... {waited}s", flush=True)

def release(fd):
    """主动释放锁（加载完毕后调用）"""
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        # 删掉锁文件让对方知道已释放
        try:
            os.unlink(LOCK_PATH)
        except FileNotFoundError:
            pass
    except Exception:
        pass
