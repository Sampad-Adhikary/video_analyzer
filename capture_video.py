import cv2
import threading
import time
import os
import datetime
import numpy as np
from collections import deque

class VideoRecorder:
    def __init__(self, cam_id, save_dir="alerts", buffer_seconds=3, post_event_seconds=5, fps=15, resolution=(1280, 720)):
        """
        Args:
            cam_id: Identifier for the camera.
            save_dir: Directory to save videos.
            buffer_seconds: How many seconds of pre-alert video to keep in memory.
            post_event_seconds: How many seconds to record AFTER the alert.
            fps: Frames per second of the stream.
            resolution: Tuple (width, height).
        """
        self.cam_id = cam_id
        self.save_dir = save_dir
        self.buffer_seconds = buffer_seconds
        self.post_event_seconds = post_event_seconds
        self.fps = fps
        self.resolution = resolution
        
        # Rolling buffer for pre-event frames
        self.buffer_len = buffer_seconds * fps
        self.frame_buffer = deque(maxlen=self.buffer_len)
        
        # Recording state
        self.is_recording = False
        self.remaining_frames_to_record = 0
        self.active_writer = None
        self.active_filename = None
        self.lock = threading.Lock()
        
        # Snapshot state
        self.snapshot_frames_left = 0
        self.last_alert_types = []
        self.last_snapshot_time = 0
        self.snapshot_cooldown = 3.0  # Seconds between snapshot sets

    def add_frame(self, frame_copy):
        """
        Adds a frame to the buffer. If recording, writes it to the file.
        Expects frame_copy to be a BGR numpy array compatible with VideoWriter.
        """
        with self.lock:
            # Always add to buffer (efficient pointer storage)
            self.frame_buffer.append(frame_copy)

            # Handle Video Recording
            if self.is_recording:
                if self.active_writer:
                    self.active_writer.write(frame_copy)
                
                self.remaining_frames_to_record -= 1
                if self.remaining_frames_to_record <= 0:
                    self._stop_recording()
            
            # Handle Snapshot Sequence
            if self.snapshot_frames_left > 0:
                self._save_snapshot(frame_copy, "seq")
                self.snapshot_frames_left -= 1

    def trigger_recording(self, alert_types, snapshot_sequence=True):
        """
        Starts recording if not already recording. 
        Dumps existing buffer to file and sets state to capture future frames.
        
        Args:
            alert_types: List of strings.
            snapshot_sequence: If True, saves prev/current/next frames as images.
        """
        with self.lock:
            self.last_alert_types = alert_types # Store for filenames
            current_time = time.time()

            # --- SNAPSHOT LOGIC ---
            # Rate Limit: Only take snapshots if cooldown has passed
            if snapshot_sequence and (current_time - self.last_snapshot_time > self.snapshot_cooldown):
                self.last_snapshot_time = current_time
                
                # 1. Save Previous Frame (if exists)
                if len(self.frame_buffer) >= 2:
                    # -1 is current (just added), -2 is previous
                    self._save_snapshot(self.frame_buffer[-2], "prev")
                
                # 2. Save Current Frame
                if len(self.frame_buffer) >= 1:
                     self._save_snapshot(self.frame_buffer[-1], "curr")
                
                # 3. Schedule Next 2 Frames
                self.snapshot_frames_left = 2

            # --- VIDEO LOGIC ---
            if self.is_recording:
                # Extend recording time
                self.remaining_frames_to_record = self.post_event_seconds * self.fps
                return

            # Start new video recording
            self.is_recording = True
            self.remaining_frames_to_record = self.post_event_seconds * self.fps
            
            # Setup file
            cam_dir = os.path.join(self.save_dir, str(self.cam_id))
            os.makedirs(cam_dir, exist_ok=True)
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            alert_suffix = "_".join(alert_types) if alert_types else "ALERT"
            alert_suffix = "".join([c if c.isalnum() else "_" for c in alert_suffix])
            
            filename = f"{timestamp}_{alert_suffix}.avi"
            filepath = os.path.join(cam_dir, filename)
            self.active_filename = filepath
            
            # Initialize VideoWriter
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            self.active_writer = cv2.VideoWriter(
                filepath, fourcc, self.fps, self.resolution
            )
            
            if not self.active_writer.isOpened():
                print(f"[ERROR] Failed to open video writer for {filepath}")
                self.is_recording = False
                return

            # Dump Pre-Event Buffer to Video
            # Start from beginning of buffer
            for old_frame in self.frame_buffer:
                self.active_writer.write(old_frame)

    def _save_snapshot(self, frame, suffix_tag):
        import capture_image
        # Use a dummy frame number or internal counter
        capture_image.capture_frame(frame, self.cam_id, f"{suffix_tag}_{time.time()}", self.last_alert_types, self.save_dir)

    def _stop_recording(self):
        # print(f"[INFO] Stopping recording for {self.cam_id}")
        self.is_recording = False
        if self.active_writer:
            self.active_writer.release()
            self.active_writer = None