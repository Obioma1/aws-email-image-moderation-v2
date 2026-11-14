
#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root.
cd "$(dirname "$0")/.."

IMAGE="public.ecr.aws/lambda/python:3.13"
PACKAGE_DIR="build/lambda"
ZIP_FILE="lambda.zip"

echo "Preparing Lambda build directory..."
rm -rf "$PACKAGE_DIR" "$ZIP_FILE"
mkdir -p "$PACKAGE_DIR"

echo "Installing dependencies in AWS Lambda Linux environment..."

# MSYS_NO_PATHCONV prevents Git Bash from changing Linux paths.
MSYS_NO_PATHCONV=1 docker run --rm \
  --platform linux/amd64 \
  --entrypoint /bin/bash \
  -v "$(pwd -W):/workspace" \
  -w /workspace \
  "$IMAGE" \
  -c "python -m pip install --no-cache-dir -r lambda/requirements.txt -t build/lambda"

echo "Copying Lambda handler..."
cp lambda/handler.py "$PACKAGE_DIR/handler.py"

echo "Creating Lambda deployment ZIP..."
python - "$PACKAGE_DIR" "$ZIP_FILE" <<'PY'
import os
import sys
import zipfile

source, destination = sys.argv[1:]

with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
    for root, directories, files in os.walk(source):
        directories.sort()
        for filename in sorted(files):
            path = os.path.join(root, filename)
            archive.write(path, os.path.relpath(path, source))

print(f"Created {destination}")
PY

echo "Lambda package build complete."
