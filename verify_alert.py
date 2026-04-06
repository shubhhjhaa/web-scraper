import sys
import os
import time
from pathlib import Path

# Add current directory to path so we can import main
sys.path.append(os.getcwd())

import main

print("--- Sound Alert Verification ---")
print(f"Alert sound path: {main.ALERT_SOUND_PATH}")
print(f"File exists: {main.ALERT_SOUND_PATH.exists()}")

# Reset state to ensure it fires
main.reset_alert_for_new_session()

print("\nTriggering first block alert...")
main.on_blocking_detected("https://example.com/blocked", "Manual Verification Trigger")

print("\nWaiting for sound execution (3 seconds)...")
time.sleep(3)

print("\nTriggering second block alert (should be silent due to global state)...")
main.on_blocking_detected("https://example.com/blocked2", "Second Trigger (Silent)")

print("\nVerifying if global state is blocked: ", main._is_blocked)

print("\nResetting state (simulating success)...")
main.reset_blocking_state()
print("Global state is blocked: ", main._is_blocked)

print("\ndone.")
