# Development Environment Setup Guide

**Goal:** Configure your Ubuntu 24.04 PC (RTX 3060) to match your Jetson Orin Nano (DeepStream 7.1) for seamless development.

**Method:** We will use **Docker**. Do NOT install DeepStream or CUDA directly on your host Ubuntu 24.04 OS. It is cleaner and safer to run everything inside the official NVIDIA container.

---

## Phase 1: Host Preparation (Run these once on your PC)

### 1. Install NVIDIA Drivers
Ensure you have the proprietary drivers installed.
```bash
sudo apt update
sudo apt install -y nvidia-driver-535
# REBOOT is required here!
sudo reboot
```

### 2. Install Docker
```bash
sudo apt update
sudo apt install -y docker.io
sudo systemctl enable docker
sudo systemctl start docker

# Allow running docker without 'sudo'
sudo usermod -aG docker $USER
# Log out and log back in for this to take effect!
```

### 3. NVIDIA Container Toolkit
**For Docker Desktop Users:** The NVIDIA Container Toolkit is **included** in Docker Desktop. You can **SKIP** the manual installation commands below. Just ensure your GPU drivers (Step 1) are installed.

**For Standard Docker Engine Users:**
Run the following to allow Docker to access your GPU:
```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Configure Docker runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

---

## Phase 2: The Development Workflow

You do **not** need to create your own Dockerfile or "dockerize" your script. You simply **run** the official NVIDIA container and mount your code folder into it. This gives you a terminal that *looks and feels* just like your Jetson.

### 1. Pull the Matching DeepStream Image
Since your Jetson has **DS 7.1**, we pull the exact matching x86 version.
```bash
docker pull nvcr.io/nvidia/deepstream:7.1-gc-triton-devel
```

### 2. Create Your Persistent Dev Environment
Run this command **once** to create a named container that survives reboots and keeps your installed packages intact.
*Replace `/home/sampad/work/video_analyzer` with the absolute path to your folder.*

```bash
docker run -d \
    --name deepstream-dev \
    --restart always \
    --gpus all \
    --net=host \
    --privileged \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -e DISPLAY=$DISPLAY \
    -v /home/sampad/work/video_analyzer:/opt/nvidia/deepstream/deepstream/sources/apps/video_analyzer \
    -w /opt/nvidia/deepstream/deepstream/sources/apps/video_analyzer \
    nvcr.io/nvidia/deepstream:7.1-gc-triton-devel \
    sleep infinity
```

### 3. Enter the Environment
Because we started the container in the background (using `-d`), you "enter" it like this:
```bash
docker exec -it deepstream-dev bash
```

> [!TIP]
> **Why this is better:** 
> - **Persistence:** Anything you `apt install` or `pip install` stays there even if you close the terminal.
> - **Auto-Restart:** If your PC reboots, the container starts itself automatically.
> - **Safety:** Your code is safely mounted from your host, so it's never lost if the container is deleted.

### 3. Install Python Bindings (Inside the Container)
Once you are inside the container prompt (it will look like `root@hostname:/...#`), run these setup commands **once** every time you restart the container (or create a tailored image later).

```bash
# 1. Install Python GStreamer prerequisites
apt update
apt install -y python3-gi python3-dev python3-gst-1.0 python-gi-dev git python3 python3-pip cmake g++ build-essential libglib2.0-dev libglib2.0-dev-bin libgstreamer1.0-dev libtool m4 autoconf automake libgirepository1.0-dev libcairo2-dev

# 2. Install pyds (DeepStream Python Bindings)
# DS 7.1 usually includes wheels, check /opt/nvidia/deepstream/deepstream/lib/pyds-*.whl
# If present:
pip3 install /opt/nvidia/deepstream/deepstream/lib/pyds-*.whl

# 3. Install your project dependencies
pip3 install opencv-python numpy pyyaml
```

---

## Installing YOLO / Ultralytics (Optional)

If you plan to run YOLO models (like YOLOv8 or YOLO11) inside your container, follow these steps. 

> [!CAUTION]
> **Architecture Warning:** The `.whl` links you see for Jetson (ending in `aarch64`) will **NOT** work on your x86 PC. 

### For your PC (x86 + RTX 3060)
On a PC, installation is much simpler than on Jetson. You don't need manual `.whl` links; the standard `pip` command handles CUDA compatibility for you.

Run these inside the container:
```bash
# 1. Install PyTorch with CUDA 12.4 support (Compatible with DS 7.1's CUDA 12.6)
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# 2. Install Ultralytics
pip3 install ultralytics
```

### For your Jetson (Orin Nano)
Only use the `aarch64` wheels when you are working **on the Jetson itself**. 
On Jetson, you would use:
```bash
# Example only (Run on Jetson, NOT on PC)
pip install torch-2.5.0...linux_aarch64.whl
pip install torchvision-0.20.0...linux_aarch64.whl
```

---

## Compiling the Custom YOLO Library

Before running the pipeline, you **must** compile the custom bounding box parser for YOLO.

1. **Enter the directory:**
   ```bash
   cd /opt/nvidia/deepstream/deepstream/sources/apps/video_analyzer/DeepStream-Yolo/nvdsinfer_custom_impl_Yolo
   ```

2. **Build the library:**
   Note: We specify `CUDA_VER=12.6` which matches the DeepStream 7.1 container.
   ```bash
   make clean
   CUDA_VER=12.6 make
   ```

3. **Verify compilation:**
   You should see `libnvdsinfer_custom_impl_Yolo.so` in the folder.
   ```bash
   ls -l libnvdsinfer_custom_impl_Yolo.so
   ```

4. **Return and Run:**
   ```bash
   cd ../..
   python3 video_analyzer.py
   ```
Now you are ready. Just run it like normal!
```bash
python3 video_analyzer.py --input rtsp://...
```

---

## Managing Your Environment

### How to "Reboot" the Container
The `reboot` command does **not** work inside a Docker container. If you need to refresh the environment (e.g., after installing a complex package like `ultralytics` which might need a path update), do this from your **Host Terminal**:

```bash
# Restart the container
docker restart deepstream-dev

# Re-enter it
docker exec -it deepstream-dev bash
```

> [!NOTE]
> For most Python packages (like `pip install ultralytics`), you don't even need to restart. Just running your script again is enough!

### Stopping/Starting
If you want to stop the container to save resources:
```bash
docker stop deepstream-dev
# To start again later:
docker start deepstream-dev
```

## Summary of Logic
1.  **Edit Code:** Use VS Code / IDE on your **Host Windows/Linux** machine.
2.  **Run Code:** Re-enter your persistent container with `docker exec -it deepstream-dev bash` and run your script.
3.  **Persistence:** Any dependencies you install (pip/apt) will be saved in the `deepstream-dev` container.
4.  **Deployment:** Copy the code folder to Jetson. It will just work (except you need to let it rebuild `.engine` files).
