#!/bin/bash
# Script to decompile NAVER App split APKs using JADX

# Exit immediately if a command exits with a non-zero status
set -e

# Define paths
JADX_BIN="/home/tech/.gemini/tmp/naver-app/jadx/bin/jadx"
APK_DIR="/home/tech/nshop_macro_v1/apks/naver_app"
OUT_DIR="$APK_DIR/jadx_out"

# Check if JADX exists
if [ ! -f "$JADX_BIN" ]; then
    echo "Error: JADX not found at $JADX_BIN"
    exit 1
fi

echo "============================================="
echo " NAVER App Decompilation Script"
echo "============================================="
echo "JADX Path:        $JADX_BIN"
echo "APK Directory:    $APK_DIR"
echo "Output Directory: $OUT_DIR"
echo "============================================="

# Parse arguments
NO_RES=""
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --no-res) NO_RES="--no-res" ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
    shift
done

# Prepare output directory
mkdir -p "$OUT_DIR"

# Run decompilation
echo "Decompiling base.apk and split config APKs..."
if [ -n "$NO_RES" ]; then
    echo "Running with --no-res (skipping resource decompilation for speed)..."
fi

"$JADX_BIN" \
    -d "$OUT_DIR" \
    $NO_RES \
    "$APK_DIR/base.apk" \
    "$APK_DIR/split_config.arm64_v8a.apk" \
    "$APK_DIR/split_config.xxhdpi.apk"

echo "============================================="
echo "Decompilation complete!"
echo "Outputs saved to: $OUT_DIR"
echo "============================================="
