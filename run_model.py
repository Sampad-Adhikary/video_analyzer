#!/usr/bin/env python3
import sys
import gi
import argparse
import time

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

# --- MAPPING ALIASES TO CONFIG FILES ---
MODEL_MAP = {
    "person": "config_infer_primary_yoloV8.txt",
    "fire": "config_infer_secondary_fire.txt",
    "fight": "config_infer_secondary_fight.txt",
    "yolo11n": "config_infer_primary_yoloV8.txt" # Alias
}

def bus_call(bus, message, loop):
    t = message.type
    if t == Gst.MessageType.EOS:
        print("End of stream")
        loop.quit()
    elif t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"Error: {err}: {debug}")
        loop.quit()
    return True

def main():
    parser = argparse.ArgumentParser(description="DeepStream Single Model Tester")
    parser.add_argument("-m", "--model", required=True, help="Model alias: 'person', 'fire', 'fight', 'yolo11n'")
    parser.add_argument("-i", "--input", required=True, help="Input URI (e.g., rtsp://... or file:///...)")
    args = parser.parse_args()

    config_file = MODEL_MAP.get(args.model.lower())
    if not config_file:
        print(f"Error: Unknown model '{args.model}'. Available: {list(MODEL_MAP.keys())}")
        sys.exit(1)

    print(f"Loading Model: {args.model} -> {config_file}")
    
    # Initialize GStreamer
    Gst.init(None)

    # Create Pipeline
    pipeline = Gst.Pipeline()
    
    # Elements
    source = Gst.ElementFactory.make("uridecodebin", "uri-decode-bin")
    source.set_property("uri", args.input)
    
    streammux = Gst.ElementFactory.make("nvstreammux", "Stream-muxer")
    streammux.set_property('width', 1280)
    streammux.set_property('height', 720)
    streammux.set_property('batch-size', 1)
    streammux.set_property('batched-push-timeout', 4000000)

    pgie = Gst.ElementFactory.make("nvinfer", "primary-nvinference-engine")
    pgie.set_property('config-file-path', config_file)
    # CRITICAL: Force Process Mode = 1 (Primary) for testing
    # This allows testing "Secondary" models (like Fight) on the full frame
    # without needing a preceding detector.
    print("Forcing process-mode=1 (Primary) for standalone testing...")
    pgie.set_property('process-mode', 1)

    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "nvvideo-converter")
    
    nvosd = Gst.ElementFactory.make("nvdsosd", "nv-onscreendisplay")
    
    # Try Jetson sink first, fallback to Auto
    sink = Gst.ElementFactory.make("nveglglessink", "nvvideo-renderer")
    if not sink:
        print("nveglglessink not found, falling back to autovideosink")
        sink = Gst.ElementFactory.make("autovideosink", "nvvideo-renderer")

    if not all([source, streammux, pgie, nvvidconv, nvosd, sink]):
        print("Failed to create some elements")
        sys.exit(1)

    # Add to Pipeline
    pipeline.add(source)
    pipeline.add(streammux)
    pipeline.add(pgie)
    pipeline.add(nvvidconv)
    pipeline.add(nvosd)
    pipeline.add(sink)

    # Linkage
    # uridecodebin uses dynamic pads, handled by callback
    def on_pad_added(src, pad):
        # 1. Check if it's a video pad
        caps = pad.get_current_caps() or pad.get_caps()
        name = caps.get_structure(0).get_name()
        if not name.startswith("video"):
            # Ignore audio/subtitle pads
            return

        # 2. Get Sink Pad
        sink_pad = streammux.get_request_pad("sink_0")
        if not sink_pad:
            print("Unable to get sink pad from streammux")
            return
            
        # 3. Link
        try:
            pad.link(sink_pad)
        except Exception as e:
            print(f"Failed to link pad: {e}")


    source.connect("pad-added", on_pad_added)

    streammux.link(pgie)
    pgie.link(nvvidconv)
    nvvidconv.link(nvosd)
    nvosd.link(sink)

    # Event Loop
    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)

    print(f"Starting pipeline for {args.input}...")
    pipeline.set_state(Gst.State.PLAYING)

    try:
        loop.run()
    except KeyboardInterrupt:
        print("Exiting...")
    finally:
        pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    main()
