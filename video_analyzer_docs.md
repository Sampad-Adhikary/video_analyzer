# Video Analyzer Code Documentation

This document explains the structure and functionality of the `video_analyzer.py` script.

## 1. Imports and Global Configuration
The script starts by importing necessary libraries (`sys`, `time`, `json`, `datetime`) and GStreamer bindings (`gi.repository`).

### Key Constants
-   `PGIE_CONFIG_FILE`: Path to the YOLOv8 model configuration file (Primary GIE).
-   `TRACKER_CONFIG_FILE`: Path to the NvDCF tracker configuration.
-   `TILED_OUTPUT_WIDTH/HEIGHT`: Resolution of the combined video output (used by Tiler).
-   **Deployment Config**:
    -   `CLIENT_ID`, `SITE_ID`, `DEVICE_ID`: Metadata for identifying the edge device context in the logs.
    -   `CAMERA_MAP`: A dictionary mapping internal Source IDs (0, 1, 2, 3) to human-readable camera names (e.g., "RECEPTION_AREA").

## 2. Helper Functions

### `write_json_log(data)`
-   **Purpose**: Appends detection data to `detection_log.json`.
-   **Format**: Writes one JSON object per line.
-   **Optimization**: Uses `json.dump(..., separators=(',', ':'))` to minify the output (remove whitespace) and adds a trailing comma for list compatibility.

### `bus_call(bus, message, loop)`
-   **Purpose**: Handles GStreamer bus messages (events from the pipeline).
-   **Logic**:
    -   `EOS` (End Of Stream): Stops the loop.
    -   `ERROR`: Prints error details and stops the loop.

## 3. Core Logic: The Buffer Probe (`tiler_sink_pad_buffer_probe`)
This function is the heart of the application. It runs on every batch of frames passing through the `nvmultistreamtiler`.

### Steps:
1.  **Get Metadata**: Retrieves `batch_meta` from the GStreamer buffer. This contains deep learning inference results.
2.  **Iterate Frames**: Loops through each frame in the batch (since we have 4 cameras, a batch contains 4 frames).
3.  **Extract Camera ID**: Reads `frame_meta.source_id` to know which camera the frame belongs to.
4.  **Iterate Objects**: Loops through objects detected by YOLO (People, etc.).
5.  **Build Object Data**: Extracts class ID, label, confidence, and bounding box coordinates for each object.
6.  **Filter & Aggregate**:
    -   Filters for specific classes (currently "person").
    -   Counts the number of people (`num_people`).
    -   Resolves the Camera Name using `CAMERA_MAP`.
7.  **Create Payload**: Constructs a structured JSON payload with two sections:
    -   `meta`: Static context (Client, Site, Device, Camera Name).
    -   `data`: Dynamic data (Frame ID, People Count, Detections list).
8.  **Output**: Prints a summary to the console and calls `write_json_log` to save to file.

## 4. Main Pipeline Setup (`main`)
This function constructs the GStreamer pipeline graph.

### Pipeline Elements:
1.  **Sources (`uridecodebin`)**: Reads RTSP streams.
2.  **Muxer (`nvstreammux`)**: Batches 4 video streams into a single buffer for parallel processing.
3.  **Inference (`nvinfer`)**: Runs the YOLO model on the batched frames.
4.  **Tracker (`nvtracker`)**: Assigns IDs to objects across frames (crucial for filling gaps when `interval` > 0).
5.  **Tiler (`nvmultistreamtiler`)**: Composes the 4 streams into a 2x2 grid (1280x720 output).
6.  **Probe Attachment**: `tiler_sink_pad.add_probe(...)` attaches the Core Logic function to this point in the pipeline.
7.  **Sinks (`fakesink`)**: Ends the pipeline. We use `fakesink` because we are headless (no monitor attached).

### Linking Order:
`Source -> StreamMux -> PGIE (YOLO) -> Tracker -> Tiler -> VideoConvert -> FakeSink`
