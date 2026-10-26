#!/usr/bin/env bash
# ==============================================================================
# Intelligent Tracker - OpenCV Installation Script
# Supports: Raspberry Pi OS Bookworm (64-bit / Debian 12), Ubuntu 24.04 / 22.04 LTS
# ==============================================================================

set -e

OPENCV_VERSION="4.10.0"
CORES=$(nproc 2>/dev/null || echo 4)
BUILD_FROM_SOURCE=false

print_usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  --apt               Install precompiled system packages (fastest, recommended)"
    echo "  --pip               Install opencv-contrib-python via pip in current environment"
    echo "  --source            Compile OpenCV ${OPENCV_VERSION} with opencv_contrib from source"
    echo "  --version <ver>     Specify custom OpenCV version for source compilation (default: ${OPENCV_VERSION})"
    echo "  --help              Display this help message"
    echo ""
}

# Parse Arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --apt) BUILD_MODE="apt"; shift ;;
        --pip) BUILD_MODE="pip"; shift ;;
        --source) BUILD_MODE="source"; shift ;;
        --version) OPENCV_VERSION="$2"; shift 2 ;;
        --help) print_usage; exit 0 ;;
        *) echo "Unknown option: $1"; print_usage; exit 1 ;;
    esac
done

# Default to APT package installation if not specified
BUILD_MODE="${BUILD_MODE:-apt}"

echo "======================================================================"
echo " Intelligent Tracker - OpenCV Installer"
echo " OS: $(grep -s PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"' || uname -s)"
echo " Mode: ${BUILD_MODE}"
echo "======================================================================"

if [ "$BUILD_MODE" = "apt" ]; then
    echo "[INFO] Updating package indices..."
    sudo apt-get update -y

    echo "[INFO] Installing OpenCV system packages and multimedia dependencies..."
    sudo apt-get install -y --no-install-recommends \
        python3-opencv \
        libopencv-dev \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        v4l-utils

    echo "[SUCCESS] OpenCV installed via system package manager."
    python3 -c "import cv2; print('[OK] Verified cv2 version:', cv2.__version__)"
    exit 0
fi

if [ "$BUILD_MODE" = "pip" ]; then
    echo "[INFO] Installing opencv-contrib-python via pip..."
    pip install --upgrade pip
    pip install "opencv-contrib-python>=4.8.0"
    python3 -c "import cv2; print('[OK] Verified cv2 version:', cv2.__version__)"
    exit 0
fi

if [ "$BUILD_MODE" = "source" ]; then
    echo "[INFO] Installing build prerequisites for OpenCV ${OPENCV_VERSION}..."
    sudo apt-get update -y
    sudo apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        pkg-config \
        python3-dev \
        python3-numpy \
        libgl1-mesa-dev \
        libgtk-3-dev \
        libv4l-dev \
        libgstreamer1.0-dev \
        libgstreamer-plugins-base1.0-dev \
        libavcodec-dev \
        libavformat-dev \
        libswscale-dev \
        libtbb-dev \
        libjpeg-dev \
        libpng-dev \
        libtiff-dev

    SRC_DIR="/tmp/opencv_build"
    mkdir -p "${SRC_DIR}"
    cd "${SRC_DIR}"

    if [ ! -d "opencv" ]; then
        echo "[INFO] Cloning opencv ${OPENCV_VERSION}..."
        git clone --depth 1 --branch "${OPENCV_VERSION}" https://github.com/opencv/opencv.git
    fi

    if [ ! -d "opencv_contrib" ]; then
        echo "[INFO] Cloning opencv_contrib ${OPENCV_VERSION}..."
        git clone --depth 1 --branch "${OPENCV_VERSION}" https://github.com/opencv/opencv_contrib.git
    fi

    mkdir -p opencv/build
    cd opencv/build

    echo "[INFO] Configuring CMake build..."
    cmake -D CMAKE_BUILD_TYPE=RELEASE \
          -D CMAKE_INSTALL_PREFIX=/usr/local \
          -D OPENCV_EXTRA_MODULES_PATH=../../opencv_contrib/modules \
          -D OPENCV_ENABLE_NONFREE=ON \
          -D WITH_GSTREAMER=ON \
          -D WITH_V4L=ON \
          -D WITH_TBB=ON \
          -D WITH_GTK=ON \
          -D BUILD_EXAMPLES=OFF \
          -D BUILD_TESTS=OFF \
          -D BUILD_PERF_TESTS=OFF \
          -D BUILD_opencv_python3=ON ..

    echo "[INFO] Compiling on ${CORES} CPU core(s)..."
    make -j"${CORES}"

    echo "[INFO] Installing OpenCV to /usr/local..."
    sudo make install
    sudo ldconfig

    echo "[SUCCESS] OpenCV ${OPENCV_VERSION} compiled and installed successfully!"
    python3 -c "import cv2; print('[OK] Verified cv2 version:', cv2.__version__)"
    exit 0
fi
