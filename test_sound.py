import pygame
import os
import time

sound_path = "alert.mpeg"

if not os.path.exists(sound_path):
    print(f"Sound file {sound_path} not found.")
    exit(1)

try:
    print("Initializing pygame.mixer...")
    pygame.mixer.init()
    print("Loading sound...")
    pygame.mixer.music.load(sound_path)
    print("Setting volume...")
    pygame.mixer.music.set_volume(0.75)
    print("Playing sound...")
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.1)
    print("Done.")
    pygame.mixer.quit()
except Exception as e:
    print(f"Error: {e}")
