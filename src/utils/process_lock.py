import os
import sys
import atexit
from src.utils.logger import log

class SingleInstanceLock:
    """
    Guarantees that only ONE instance of the bot process can run at any time.
    Uses a PID lockfile with cross-platform active process validation.
    """
    def __init__(self, pid_file: str = "data/bot.pid"):
        self.pid_file = os.path.abspath(pid_file)
        self.acquired = False

    def acquire(self) -> bool:
        os.makedirs(os.path.dirname(self.pid_file), exist_ok=True)
        
        # Check if lockfile already exists
        if os.path.exists(self.pid_file):
            try:
                with open(self.pid_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    existing_pid = int(content)
                    if self._is_pid_running(existing_pid):
                        # Another active process holds this lock
                        return False
                    else:
                        # Stale lockfile from a crashed process; safe to reclaim
                        log.warning(f"Reclaiming stale lockfile from dead PID {existing_pid}")
            except Exception:
                pass

        # Write our current PID into lockfile
        try:
            with open(self.pid_file, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            self.acquired = True
            atexit.register(self.release)
            return True
        except Exception as e:
            log.error(f"Failed to acquire PID lock at {self.pid_file}: {e}")
            return False

    def release(self):
        """Remove the PID lockfile if it belongs to this process."""
        if self.acquired:
            try:
                if os.path.exists(self.pid_file):
                    with open(self.pid_file, "r", encoding="utf-8") as f:
                        saved_pid = f.read().strip()
                    if saved_pid == str(os.getpid()):
                        os.remove(self.pid_file)
            except Exception:
                pass
            self.acquired = False

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        """Check if process with given PID is alive."""
        if pid <= 0:
            return False
            
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x100000
            process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if process != 0:
                kernel32.CloseHandle(process)
                return True
            return False
        else:
            # POSIX / Linux
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
