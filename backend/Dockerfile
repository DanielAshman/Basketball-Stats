FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    libglib2.0-0 \
    curl \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install CPU-only torch/torchvision first. `ultralytics` depends on `torch`
# without pinning a build, so pip's resolver otherwise grabs the full CUDA
# wheels (2.5GB+ of NVIDIA drivers) even though Docker Desktop on macOS has
# no GPU passthrough to use them. Installing these first satisfies that
# dependency before pip ever considers the CUDA variant.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install remaining Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Create directories
RUN mkdir -p /app/videos /app/data

# Download YOLO11 models (detection + pose) at build time so they're baked
# into the image and don't need to be downloaded on first request.
# This adds ~100MB to the image but eliminates first-request latency.
RUN python -c "from ultralytics import YOLO; YOLO('yolo11m.pt'); YOLO('yolo11m-pose.pt')" || echo "Model download failed - will retry on first request"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
