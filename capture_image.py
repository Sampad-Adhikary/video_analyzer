import cv2
import os
import datetime

def capture_frame(frame_copy, cam_name, frame_num, alert_types, output_dir="alerts"):
    """
    Saves a single frame as a JPEG image.
    
    Args:
        frame_copy: The numpy array of the frame (expected BGR or RGBA).
        cam_name: Name/ID of the camera.
        frame_num: Frame number.
        alert_types: List of alert strings (e.g., ["UNAUTHORIZED"]).
        output_dir: Base directory to save alerts.
    """
    try:
        # Create directory: alerts/CAM_NAME/
        cam_dir = os.path.join(output_dir, str(cam_name))
        os.makedirs(cam_dir, exist_ok=True)

        # Timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Filename: YYYYMMDD_HHMMSS_FrameX_Alert.jpg
        alert_suffix = "_".join(alert_types) if alert_types else "ALERT"
        # Sanitize filename
        alert_suffix = "".join([c if c.isalnum() else "_" for c in alert_suffix])
        
        filename = f"{timestamp}_{frame_num}_{alert_suffix}.jpg"
        filepath = os.path.join(cam_dir, filename)

        # Ensure frame is BGR for OpenCV saving
        if frame_copy.shape[2] == 4:
            frame_copy = cv2.cvtColor(frame_copy, cv2.COLOR_RGBA2BGR)

        cv2.imwrite(filepath, frame_copy)
        # print(f"[INFO] Saved alert image: {filepath}")
        return filepath

    except Exception as e:
        print(f"[ERROR] Failed to save image for {cam_name}: {e}")
        return None
