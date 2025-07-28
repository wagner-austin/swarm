#!/usr/bin/env python
"""Start the Celery autoscaler in the background."""

import os
import subprocess
import sys

# Start Celery autoscaler as a detached process
if sys.platform == "win32":
    # Windows: use CREATE_NEW_PROCESS_GROUP to detach
    subprocess.Popen(
        [sys.executable, "-m", "scripts.celery_autoscaler"],
        stdout=open("celery_autoscaler.log", "w"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        cwd=os.getcwd(),
    )
else:
    # Unix: use start_new_session to detach
    subprocess.Popen(
        [sys.executable, "-m", "scripts.celery_autoscaler"],
        stdout=open("celery_autoscaler.log", "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=os.getcwd(),
    )

print("Celery autoscaler started in background. Check celery_autoscaler.log for output.")
