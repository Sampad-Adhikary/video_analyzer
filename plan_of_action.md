### Part 1: Optimization Strategy (Reducing GPU Load)

**Your current GPU load (100%) is due to running a complex model on every single frame. The Orin Nano cannot sustain this for 4 streams. You must offload work from the Inference Engine (GPU Compute) to the Tracker (Motion Vectors).**

**1. Inference Interval (The most critical fix)**

* **Current:**interval=0** (Inference runs 60 times/sec for 4 cams @ 15fps).**
* **Recommended:** Set **interval=2** or **interval=3** in your DeepStream config.
* **Why:** This runs the heavy AI model only once every 3 or 4 frames. The intermediate frames are handled by the **NvTracker**, which uses much cheaper optical flow algorithms. This will immediately drop GPU load by ~50-60%.

**2. Model Selection**

* **Current:** YOLOv11s ("Small").
* **Recommended:** Switch to **YOLOv8n** or **YOLOv11n** ("Nano").
* **Why:** The "Nano" versions are specifically designed for edge devices. For detecting "People" and "Fire," the accuracy difference between Small and Nano is negligible, but Nano is ~3x faster.

**3. Tracker Configuration**

* **Recommendation:** Use **NvDCF** (accuracy) or **IOU** (speed) tracker.
* **Why:** A good tracker compensates for the skipped frames caused by the **interval** setting. Ensure your tracker config is tuned to keep IDs stable for your "Time/Attendance" KPIs.

---

### Part 2: Addressing Your KPIs

**You do not need multiple models. Running a second model (SGIE) will crash your system given the current load. You need a **Single Model + Logic** strategy.**

**The Model Strategy:**
You need a single custom-trained **YOLOv11n (Nano)** model with exactly these 3 classes:

* **Person**
* **Fire**
* **Smoke**

**Note: Do not look for a separate "Violence" model; it is too heavy for this hardware.**

**The KPI Implementation Guide:**

#### 1. Unauthorized Area (Critical)

* **Technology:**NvDsAnalytics (Zones)**.**
* **Implementation:** Define a polygon zone in the configuration file for the "Restricted Area."
* **Logic:** If **Class ID == Person** AND **ROI == Restricted_Zone**, trigger alert.

#### 2. Fire and Smoke Detection (Critical)

* **Technology:**YOLO Object Detection**.**
* **Implementation:** These are direct class detections from your custom YOLO model.
* **Logic:** If **Class ID == Fire** OR **Class ID == Smoke** with Confidence > 0.6, trigger alert.

#### 3. Early Departure / Extended Break (High/Medium)

* **Technology:**NvDsAnalytics (Line Crossing/ROI) + Python Logic**.**
* **Implementation:**

  * **Define an "Exit Door" zone or tripwire.**
  * **Define a "Break Room" zone.**
* **Logic (Early Departure):** If **Person** crosses "Exit Tripwire" AND **Time < Shift_End_Time**, trigger alert.
* **Logic (Extended Break):** If **Person** enters "Break Zone", start a timer in Python (using their Object ID). If **Time_In_Zone > 30 mins**, trigger alert. **Note: This requires a stable Tracker ID.**

#### 4. Camera Offline (High)

* **Technology:**GStreamer Bus Messages**.**
* **Implementation:** This is not AI. This is pipeline state monitoring.
* **Logic:** In your Python **bus_call** function, listen for **GST_MESSAGE_ERROR** or **EOS** (End of Stream). If a source stops sending buffers for > 5 seconds, flag as "Offline".

#### 5. Workplace Violence (Critical) - **The Hardest One**

* **Problem:** True violence detection (punching/kicking) requires **Action Recognition (3D-CNNs)**, which is too computationally expensive for 4 streams on an Orin Nano.
* **Orin Nano Workaround:** Use **Proximity & Density Heuristics**.
* **Implementation:**

  * **Calculate the distance between centroids of different "Person" bounding boxes.**
  * **Logic:** If 2+ People are extremely close (overlap) AND the Tracker reports high velocity/erratic movement (jitter) for > 2 seconds, flag as "Physical Aggression / Crowd Anomaly."
  * **Trade-off:** This will have false positives (e.g., hugging), but it is the only way to do it on this specific hardware without dropping streams.

### Summary of Next Steps

* **Retrain/Download** a YOLOv11n (Nano) model for [Person, Fire, Smoke].
* **Update Config:** Set **interval=2** and point to the new Nano model engine.
* **Map Zones:** Update your **nvdsanalytics** config with polygons for Restricted Areas and Break Rooms.
* **Write Logic:** Use Python to handle the timing (breaks/departure) and state checks (offline).
