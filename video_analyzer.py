#!/usr/bin/env python3
import sys
import time
import json
import datetime
import socket
from pathlib import Path
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

# Cache streammux sink pads to avoid duplicate requests
streammux_sinkpads = {}

# Import DeepStream bindings
try:
    import pyds
except ImportError:
    sys.stderr.write("ERROR: pyds not found! Is deepstream-python installed?\n")
    sys.exit(1)
    
# --- CONFIGURATION ---
OUTPUT_JSON_FILE = "detection_log.json"
# REPLACE THIS with the path to your YOLO config file
PGIE_CONFIG_FILE = "config_infer_primary_yoloV8.txt" 
TRACKER_CONFIG_FILE = "config_tracker.yml" 
TILED_OUTPUT_WIDTH = 1280
TILED_OUTPUT_HEIGHT = 720
# ---------------------

# --- DEPLOYMENT CONFIGURATION ---
# In production, these should be loaded from Environment Variables (e.g., Docker ENV)
# using os.getenv("CLIENT_ID", "default_client")

CLIENT_ID = "INVINCIBLE_OCEAN"           # Who is the customer?
SITE_ID = "HEAD_OFFICE"      # Physical location
DEVICE_ID = socket.gethostname()  # Or manual ID like "JETSON_ORIN_01"

# Map the Source ID (0, 1, 2...) to unique Camera UUIDs/Names
# You must match these to your RTSP URI order in the command line arguments
CAMERA_MAP = {
    0: "RECEPTION_AREA",
    1: "EMPLOYEE_AREA",
    2: "BOSS_CABIN",
    3: "CAFETERIA"
}

# --- ACCESS CONTROL POLICIES ---
# Times are in 24-hour format (e.g., 14 = 2 PM)

# Rule 1: Boss Cabin (Restricted before 11 AM and after 4 PM)
BOSS_CABIN_OPEN_HOUR = 11  #(10:30 AM IST)
BOSS_CABIN_CLOSE_HOUR = 16 #(4:30 PM IST)

# Rule 2: General Office (Restricted before Open Time and after 6:30 PM + All day Sunday)
OFFICE_OPEN_HOUR = 9      # Defaulting to 8:00 AM IST
OFFICE_OPEN_MIN = 30
OFFICE_CLOSE_HOUR = 18    # 6 PM IST
OFFICE_CLOSE_MIN = 15     # 30 Minutes -> 6:30 PM IST
# --------------------------------

# Ensure file exists and is initialized as an empty array if missing
if not os.path.exists(OUTPUT_JSON_FILE):
    with open(OUTPUT_JSON_FILE, 'w') as f:
        f.write("[]")

def write_json_log(data):
    """
    Appends to a JSON array file. 
    Handles empty arrays [] correctly (no leading comma).
    Handles populated arrays [{...}] correctly (adds leading comma).
    """
    try:
        with open(OUTPUT_JSON_FILE, 'r+') as f:
            # 1. Move to the end of the file
            f.seek(0, os.SEEK_END)
            filesize = f.tell()
            
            # 2. Find the last closing bracket ']'
            # Scan backwards from the end to skip potential whitespace/newlines
            pos = filesize
            found_bracket = False
            
            while pos > 0:
                pos -= 1
                f.seek(pos)
                char = f.read(1)
                if char == ']':
                    found_bracket = True
                    break
            
            if not found_bracket:
                # Fallback: File is corrupted or empty, reset to new array
                f.seek(0)
                f.truncate()
                f.write("[\n")
                json.dump(data, f, separators=(',', ':'))
                f.write("\n]")
                return

            # 3. Check if the array is empty
            # We are currently at the ']' position. We need to look backwards again
            # to see if the previous non-whitespace character is '['
            is_array_empty = False
            scan_pos = pos
            
            while scan_pos > 0:
                scan_pos -= 1
                f.seek(scan_pos)
                prev_char = f.read(1)
                if prev_char.isspace():
                    continue # Skip spaces/newlines
                
                if prev_char == '[':
                    is_array_empty = True
                break # We found the previous meaningful character

            # 4. Write Data
            # Reset pointer to overwrite the existing ']'
            f.seek(pos)
            
            if is_array_empty:
                # Case: [] -> [{data}]
                # No comma needed
                f.write("\n") 
                json.dump(data, f, separators=(',', ':'))
                f.write("\n]")
            else:
                # Case: [{old}] -> [{old}, {data}]
                # Comma needed
                f.write(",\n") 
                json.dump(data, f, separators=(',', ':'))
                f.write("\n]")

    except Exception as e:
        print(f"[ERROR] Failed to write JSON: {e}")

def check_policy_violation(camera_name, current_time):
    """
    Checks if presence is unauthorized based on time and location.
    Returns a list of alert strings (e.g., ["UNAUTHORIZED_ACCESS"]).
    """
    alerts = []
    
    # 0 = Monday, 6 = Sunday
    is_sunday = (current_time.weekday() == 6)
    hour = current_time.hour
    minute = current_time.minute

    # --- Rule 1: Boss Cabin ---
    if camera_name == "BOSS_CABIN":
        # Safe hours: 11:00 to 15:59 (Before 16:00)
        # If earlier than 11 OR later/equal to 16, it's a violation
        if hour < BOSS_CABIN_OPEN_HOUR or hour >= BOSS_CABIN_CLOSE_HOUR:
            alerts.append("RESTRICTED_ACCESS_BOSS_CABIN")
            
    # --- Rule 2: General Office (All other cameras) ---
    else:
        # Condition A: Sunday (All day restricted)
        if is_sunday:
            alerts.append("RESTRICTED_ACCESS_SUNDAY")
        
        # Condition B: Before Open Time
        elif hour < OFFICE_OPEN_HOUR or (hour == OFFICE_OPEN_HOUR and minute < OFFICE_OPEN_MIN):
             alerts.append("RESTRICTED_ACCESS_BEFORE_HOURS")
             
        # Condition C: After Close Time (6:30 PM)
        # Violation if Hour > 18 OR (Hour == 18 AND Min >= 30)
        elif hour > OFFICE_CLOSE_HOUR or (hour == OFFICE_CLOSE_HOUR and minute >= OFFICE_CLOSE_MIN):
            alerts.append("RESTRICTED_ACCESS_AFTER_HOURS")
            
    return alerts


def tiler_sink_pad_buffer_probe(pad, info, u_data):
    """
    This is the core logic. It intercepts the pipeline data, 
    extracts metadata, and formats it to JSON.
    """
    print("[DEBUG] tiler_sink_pad_buffer_probe called")
    gst_buffer = info.get_buffer()
    if not gst_buffer:
        print("[WARN] Unable to get GstBuffer")
        return Gst.PadProbeReturn.OK

    # Retrieve the batch metadata (contains info for all 4 cameras)
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    if not batch_meta:
        print("[WARN] No batch_meta retrieved from buffer")
        return Gst.PadProbeReturn.OK

    l_frame = batch_meta.frame_meta_list
    while l_frame is not None:
        try:
            frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        except StopIteration:
            break

        # Basic Frame Info
        frame_number = frame_meta.frame_num
        source_id = frame_meta.source_id  # Camera ID (0, 1, 2, 3)
        print(f"[DEBUG] Processing frame -> camera={source_id} frame={frame_number}")
        
        # List to hold objects in this frame
        frame_objects = []

        # Iterate through objects (People, Fire, etc.)
        l_obj = frame_meta.obj_meta_list
        while l_obj is not None:
            try:
                obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
            except StopIteration:
                break
            
            # Extract Object Data
            # FILTER: Ignore objects with negative confidence (Tracker updates only)
            if obj_meta.confidence < 0:
                try:
                    l_obj = l_obj.next
                except StopIteration:
                    break
                continue

            obj_data = {
                "class_id": obj_meta.class_id,
                "label": obj_meta.obj_label,
                "confidence": round(obj_meta.confidence, 4),
                "bbox": {
                    "top": round(obj_meta.rect_params.top),
                    "left": round(obj_meta.rect_params.left),
                    "width": round(obj_meta.rect_params.width),
                    "height": round(obj_meta.rect_params.height)
                }
            }
            frame_objects.append(obj_data)
            # print(f"[DEBUG] Obj: label={obj_data['label']} conf={obj_data['confidence']} bbox={obj_data['bbox']}")
            
            try: 
                l_obj = l_obj.next
            except StopIteration:
                break

        # Construct Final JSON Payload for this Frame
        if frame_objects and any(obj["label"].lower() in ["person", "tv"] for obj in frame_objects):  # Only log if something is detected
            # Count the number of person
            num_people = len([obj for obj in frame_objects if obj["label"].lower() == "person"])

            # Resolve the unique Camera ID (Fallback to index if not in map)
            unique_cam_id = CAMERA_MAP.get(source_id, f"UNKNOWN_CAM_{source_id}")

            # Creating payload to dump in JSON file

            # Old Payload
            # payload = {
            #     "timestamp": datetime.datetime.now().isoformat(),
            #     "camera_id": source_id,
            #     "frame_id": frame_number,
            #     "detections": frame_objects
            # }

            # New Payload
            payload = {
                # METADATA HEADER (The "Who, Where, When")
                "meta": {
                    "ver": "1.0", # Schema version
                    "ts": datetime.datetime.now().isoformat() + "Z", # Always use UTC for multi-site
                    "client": CLIENT_ID,
                    "site": SITE_ID,
                    "device": DEVICE_ID,
                    "device": DEVICE_ID,
                    "cam_id": unique_cam_id,
                    "src_id": source_id # Keep the raw index for debugging
                },
                # DATA BODY (The "What")
                "data": {
                    "fid": frame_number,
                    "people_count": num_people,
                    "detections": frame_objects
                }
            }

            # --- Check for Policy Violations ---
            # using current system time for checks
            now = datetime.datetime.now()
            site_alerts = check_policy_violation(unique_cam_id, now)
            
            if site_alerts:
                payload["alerts"] = site_alerts
                # Also print to console for immediate visibility
                print(f"[ALERT] {unique_cam_id}: {site_alerts}")

            # -----------------------------------
            
            # Print to Console (Optional)
            print(f"Cam {source_id}: Found {num_people} objects")
            # Print payload summary (truncated)
            try:
                payload_preview = json.dumps(payload)
                print(f"[DEBUG] Payload preview: {payload_preview[:400]}")
            except Exception:
                print("[DEBUG] Payload preview unavailable")

            # Write to File
            write_json_log(payload)

        try:
            l_frame = l_frame.next
        except StopIteration:
            break
            
    return Gst.PadProbeReturn.OK

def bus_call(bus, message, loop):
    t = message.type
    if t == Gst.MessageType.EOS:
        sys.stdout.write("End of stream\n")
        loop.quit()
    elif t == Gst.MessageType.WARNING:
        err, debug = message.parse_warning()
        sys.stderr.write("Warning: %s: %s\n" % (err, debug))
        
        # Also check warnings for camera issues (e.g. initial disconnects)
        error_context = f"{message.src.get_name()} {debug}"
        if "uri-decode-bin-" in error_context:
            try:
                import re
                match = re.search(r"uri-decode-bin-(\d+)", error_context)
                if match:
                    stream_index = int(match.group(1))
                    cam_name = CAMERA_MAP.get(stream_index, f"UNKNOWN_CAM_{stream_index}")
                    
                    alert_payload = {
                         "meta": {
                            "ver": "1.0",
                            "ts": datetime.datetime.now().isoformat() + "Z",
                            "client": CLIENT_ID,
                            "site": SITE_ID,
                            "device": DEVICE_ID,
                            "cam_id": cam_name,
                            "src_id": stream_index
                        },
                        "alerts": ["CAMERA_WARNING"],
                        "error_msg": str(err)
                    }
                    write_json_log(alert_payload)
                    print(f"[WARNING] Camera Issue Detected: {cam_name}")
            except Exception as e:
                print(f"[ERROR] Failed to log camera warning: {e}")

    elif t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        sys.stderr.write("Error: %s: %s\n" % (err, debug))
        
        # Robust check: Search for 'uri-decode-bin-X' in the debug string or source name
        # The error often comes from GstRTSPSrc which is INSIDE the bin.
        # Debug string looks like: "... /GstPipeline:pipeline0/GstURIDecodeBin:uri-decode-bin-2/..."
        error_context = f"{message.src.get_name()} {debug}"
        
        if "uri-decode-bin-" in error_context:
            try:
                # Regex or string splitting to find the ID
                # Find substring after "uri-decode-bin-"
                # Simple parsing assuming standard naming
                import re
                match = re.search(r"uri-decode-bin-(\d+)", error_context)
                if match:
                    stream_index = int(match.group(1))
                    cam_name = CAMERA_MAP.get(stream_index, f"UNKNOWN_CAM_{stream_index}")
                    
                    # Create detailed alert payload
                    alert_payload = {
                         "meta": {
                            "ver": "1.0",
                            "ts": datetime.datetime.now().isoformat() + "Z",
                            "client": CLIENT_ID,
                            "site": SITE_ID,
                            "device": DEVICE_ID,
                            "cam_id": cam_name,
                            "src_id": stream_index
                        },
                        "alerts": ["CAMERA_OFFLINE"],
                        "error_msg": str(err)
                    }
                    write_json_log(alert_payload)
                    print(f"[CRITICAL] Camera Offline Detected: {cam_name}")
                    
                    # DO NOT QUIT LOOP - Let other cameras continue
                    return True
                    
            except Exception as e:
                print(f"[ERROR] Failed to log camera offline: {e}")

        # For critical pipeline errors (not individual camera sources), we quit
        loop.quit()
    return True

def main(args):
    # Standard GStreamer Initialization
    Gst.init(None)

    # Create Pipeline
    pipeline = Gst.Pipeline()
    streammux = Gst.ElementFactory.make("nvstreammux", "Stream-muxer")
    pipeline.add(streammux)

    # Handle RTSP Inputs
    for i, uri in enumerate(args):
        print(f"Creating source_bin for stream {i} url: {uri}")

        source = Gst.ElementFactory.make("uridecodebin", f"uri-decode-bin-{i}")
        source.set_property("uri", uri)
        
        # Revert to standard properties (nvurisrcbin props like rtsp-reconnect-interval removed)

        queue = Gst.ElementFactory.make("queue", f"queue-{i}")
        conv = Gst.ElementFactory.make("nvvideoconvert", f"conv-{i}")
        capsfilter = Gst.ElementFactory.make("capsfilter", f"caps-{i}")
        capsfilter.set_property(
            "caps",
            Gst.Caps.from_string("video/x-raw(memory:NVMM)")
        )

        pipeline.add(source)
        pipeline.add(queue)
        pipeline.add(conv)
        pipeline.add(capsfilter)

        queue.link(conv)
        conv.link(capsfilter)

        def on_pad_added(src, pad, queue=queue):
            caps = pad.get_current_caps() or pad.get_caps()
            name = caps.get_structure(0).get_name()
            if not name.startswith("video"):
                return
            sink_pad = queue.get_static_pad("sink")
            if not sink_pad.is_linked():
                pad.link(sink_pad)

        source.connect("pad-added", on_pad_added)

        mux_sink_pad = streammux.request_pad_simple(f"sink_{i}")
        capsfilter.get_static_pad("src").link(mux_sink_pad)


    # Configure Muxer
    streammux.set_property('width', 1280)   # 1280p
    streammux.set_property('height', 720)   # 720p
    streammux.set_property('batch-size', 4) # 4 streams
    streammux.set_property('batched-push-timeout', 4000000)

    # Inference Engine (PGIE)
    pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
    pgie.set_property('config-file-path', PGIE_CONFIG_FILE)

    # Tracker
    tracker = Gst.ElementFactory.make("nvtracker", "tracker")
    tracker.set_property('ll-config-file', TRACKER_CONFIG_FILE)
    tracker.set_property('ll-lib-file', '/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so')

    tracker.set_property('tracker-width', 640)
    tracker.set_property('tracker-height', 384)

    # Tiler (Grid view - optional but good for combining streams before probe)
    tiler = Gst.ElementFactory.make("nvmultistreamtiler", "nvtiler")
    tiler.set_property("width", TILED_OUTPUT_WIDTH)
    tiler.set_property("height", TILED_OUTPUT_HEIGHT)

    # Video Converter & FakeSink (We don't need a display)
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "nvvideo-converter")
    
    # We use fakesink because we only care about the JSON side effect
    sink = Gst.ElementFactory.make("fakesink", "nvvideo-renderer")

    pipeline.add(pgie)
    pipeline.add(tracker)
    pipeline.add(tiler)
    pipeline.add(nvvidconv)
    pipeline.add(sink)

    streammux.link(pgie)
    pgie.link(tracker)
    tracker.link(tiler)
    tiler.link(nvvidconv)
    nvvidconv.link(sink)

    # Add Probe to Tiler Sink Pad (This is where we extract JSON)
    tiler_sink_pad = tiler.get_static_pad("sink")
    if not tiler_sink_pad:
        sys.stderr.write(" Unable to get src pad \n")
    else:
        tiler_sink_pad.add_probe(Gst.PadProbeType.BUFFER, tiler_sink_pad_buffer_probe, 0)

    # Event Loop
    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)

    print("Starting pipeline... Check 'detection_log.json' for output.")
    pipeline.set_state(Gst.State.PLAYING)
    
    try:
        loop.run()
    except:
        pass
    pipeline.set_state(Gst.State.NULL)

if __name__ == '__main__':
    # Usage: python3 rtsp_to_json.py rtsp://url1 rtsp://url2 ...
    rtsp_uris = [
        "rtsp://admin:hik%402024@192.168.0.64:554/Streaming/Channels/101",
        "rtsp://admin:hik%402024@192.168.0.65:554/Streaming/Channels/101",
        "rtsp://admin:hik%402024@192.168.0.66:554/Streaming/Channels/101",
        "rtsp://admin:hik%402024@192.168.0.67:554/Streaming/Channels/101"
    ]
    sys.exit(main(rtsp_uris))
