# Video Analyzer System - Feature Summary

This document outlines the core capabilities, detection logic, and recording behavior of the Multi-Model Video Analyzer.

## 1. Core Architecture
*   **Hardware:** Optimized for NVIDIA Jetson Orin Nano.
*   **Pipeline:** 4-Channel RTSP Stream Analysis.
*   **AI Models:** 3-Stage Cascaded Inference.
    1.  **General (YOLOv11n):** Detects People and Cars (Every 4th frame).
    2.  **Fire/Smoke (YOLOv11n):** Scans full frame for hazards (Every 30th frame).
    3.  **Fight/Violence (YOLOv11n):** Smart-scanning; only runs on detected People.

## 2. Detection & Alerts
The system monitors for the following specific events. All critical events trigger "Visual Proof" (Video + Photos).

| Event Type | Condition / Logic | Priority |
| :--- | :--- | :--- |
| **Fire / Smoke** | Visual detection of Fire or Smoke objects. | **CRITICAL** |
| **Violence** | Visual detection of "Fight" or "Violence" class. | **CRITICAL** |
| **Crowd (Boss Cabin)** | More than **10 People** detected inside the Boss Cabin. | **CRITICAL** |
| **Intrusion (Time)** | Person detected in Office before/after hours (e.g., > 6:30 PM). | **HIGH** |
| **Intrusion (Zone)** | Person detected in Boss Cabin during restricted hours (11-4). | **HIGH** |
| **Camera Offline** | RTSP stream fails or disconnects for > 5 seconds. | **HIGH** |
| **Camera Warning** | Frame decoding errors or warnings. | **MEDIUM** |

## 3. Recording & Evidence (Visual Proof)
The system only records when an Alert is triggered. It does not record 24/7.

*   **Smart Buffering:** Automatically saves the **3 seconds BEFORE** the event happens (Pre-Event Buffer).
*   **Snapshots:** Captures high-res images:
    *   1x Previous Frame (Context)
    *   1x Current Frame (The Event)
    *   Subsequent snapshots every 2.0 seconds.
*   **Variable Duration:**
    *   **Crowd / Violence:** Records for **10 seconds** (plus buffer).
    *   **Other Alerts:** Records for **5 seconds** (plus buffer).

## 4. Data Logging
Two distinct data streams are generated in `detection_log.json`:

1.  **METRIC (Heartbeat):**
    *   Sent every **60 seconds**.
    *   Contains: People Count, System Status (SAFE), and Object Detections.
    *   *Purpose: Dashboard graphs and occupancy tracking.*

2.  **EVENT (Alert):**
    *   Sent **Immediately** upon detection.
    *   Contains: Specific Alert Name, Full Detection List, Trigger Flag.
    *   *Purpose: Real-time notification and evidence indexing.*
