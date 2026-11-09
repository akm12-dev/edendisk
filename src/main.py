from ui import EdenDiskDashboard
from backend import is_admin, relaunch_as_admin
import sys

if __name__ == "__main__":
    if not is_admin():
        relaunch_as_admin()
        sys.exit(0)
    app = EdenDiskDashboard()
    app.mainloop()