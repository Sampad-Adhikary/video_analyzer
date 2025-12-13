#!/usr/bin/env python3
import sys
import time
import json
import datetime
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
TILED_OUTPUT_WIDTH = 1280
TILED_OUTPUT_HEIGHT = 720
# ---------------------

def write_json_log(data):
    """Appends a single frame's data as a JSON line to the file."""
    with open(OUTPUT_JSON_FILE, 'a') as f:
        json.dump(data, f)
        f.write('\n')

def tiler_sink_pad_buffer_probe(pad, info, u_data):
    """
    This is the core logic. It intercepts the pipeline data, 
    extracts metadata, and formats it to JSON.
    """
    gst_buffer = info.get_buffer()
    if not gst_buffer:
        print("Unable to get GstBuffer")
        return Gst.PadProbeReturn.OK

    # Retrieve the batch metadata (contains info for all 4 cameras)
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    
    l_frame = batch_meta.frame_meta_list
    while l_frame is not None:
        try:
            frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        except StopIteration:
            break

        # Basic Frame Info
        frame_number = frame_meta.frame_num
        source_id = frame_meta.source_id # Camera ID (0, 1, 2, 3)
        
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
            
            try: 
                l_obj = l_obj.next
            except StopIteration:
                break

        # Construct Final JSON Payload for this Frame
        if frame_objects: # Only log if something is detected
            payload = {
                "timestamp": datetime.datetime.now().isoformat(),
                "camera_id": source_id,
                "frame_id": frame_number,
                "detections": frame_objects
            }
            
            # Print to Console (Optional)
            print(f"Cam {source_id}: Found {len(frame_objects)} objects")
            
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
    elif t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        sys.stderr.write("Error: %s: %s\n" % (err, debug))
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
    for i in range(len(args)):
        print(f"Creating source_bin for stream {i} url: {args[i]}")

        source = Gst.ElementFactory.make("uridecodebin", f"uri-decode-bin-{i}")
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

        def pad_added_callback(element, pad, index):
            caps = pad.get_current_caps()
            if not caps:
                caps = pad.get_caps()
            name = caps.get_structure(0).get_name()

            if not name.startswith("video"):
                return

            sink_pad = queue.get_static_pad("sink")
            if not sink_pad.is_linked():
                pad.link(sink_pad)

        source.connect("pad-added", pad_added_callback, i)

        mux_sink_pad = streammux.request_pad_simple(f"sink_{i}")
        src_pad = capsfilter.get_static_pad("src")
        src_pad.link(mux_sink_pad)

    # Configure Muxer
    streammux.set_property('width', 1280)   # 1280p
    streammux.set_property('height', 720)   # 720p
    streammux.set_property('batch-size', 4) # 4 streams
    streammux.set_property('batched-push-timeout', 4000000)

    # Inference Engine (PGIE)
    pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
    pgie.set_property('config-file-path', PGIE_CONFIG_FILE)

    # Tiler (Grid view - optional but good for combining streams before probe)
    tiler = Gst.ElementFactory.make("nvmultistreamtiler", "nvtiler")
    tiler.set_property("width", TILED_OUTPUT_WIDTH)
    tiler.set_property("height", TILED_OUTPUT_HEIGHT)

    # Video Converter & FakeSink (We don't need a display)
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "nvvideo-converter")
    
    # We use fakesink because we only care about the JSON side effect
    sink = Gst.ElementFactory.make("fakesink", "nvvideo-renderer")

    pipeline.add(pgie)
    pipeline.add(tiler)
    pipeline.add(nvvidconv)
    pipeline.add(sink)

    streammux.link(pgie)
    pgie.link(tiler)
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
