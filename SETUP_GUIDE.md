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

### 3. Install NVIDIA Container Toolkit (Crucial)
This packages allows Docker to access your RTX 3060 GPU.
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

### 2. Enter Your Dev Environment
Run this command from your terminal to "step inside" the DeepStream environment.
*Replace `/path/to/your/code` with the actual path to your `video_analyzer` folder.*

```bash
docker run --gpus all -it --rm \
    -v /home/youruser/work/video_analyzer:/opt/nvidia/deepstream/deepstream/sources/apps/video_analyzer \
    -w /opt/nvidia/deepstream/deepstream/sources/apps/video_analyzer \
    --net=host \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    nvcr.io/nvidia/deepstream:7.1-gc-triton-devel
```

*(Note: The `-e DISPLAY` lines allow the container to pop up video windows on your desktop if you need to see the output).*

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

### 4. Run Your Code
Now you are ready. Just run it like normal!
```bash
python3 video_analyzer.py --input rtsp://...
```

---

## Summary of Logic
1.  **Edit Code:** Use VS Code / IDE on your **Host Windows/Linux** machine.
2.  **Run Code:** Switch to the **Docker Terminal** to run `python3 video_analyzer.py`.
3.  **Deployment:** Copy the code folder to Jetson. It will just work (except you need to let it rebuild `.engine` files).
