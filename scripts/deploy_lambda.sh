#!/usr/bin/env bash
# deploy_lambda.sh — package and deploy the anomaly detector Lambda.
#
# Usage:
#   ./scripts/deploy_lambda.sh                        # deploy to dev
#   ./scripts/deploy_lambda.sh --env prod             # deploy to prod
#   ./scripts/deploy_lambda.sh --env dev --dry-run    # show what would happen
#
# This script is the manual alternative to `terraform apply` for code-only
# changes. Use terraform for infrastructure changes; use this for quick
# code iteration without a full plan/apply cycle.

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
ENV="dev"
DRY_RUN=false
REGION="${AWS_REGION:-us-east-1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAMBDA_SRC="$PROJECT_ROOT/lambda/anomaly_detector"
BUILD_DIR="$PROJECT_ROOT/.lambda_build"
ZIP_PATH="$BUILD_DIR/anomaly_detector.zip"

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case $1 in
    --env)       ENV="$2"; shift 2 ;;
    --region)    REGION="$2"; shift 2 ;;
    --dry-run)   DRY_RUN=true; shift ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

FUNCTION_NAME="tickwatch-anomaly-detector-$ENV"

echo "==> TickWatch Lambda deploy"
echo "    Function : $FUNCTION_NAME"
echo "    Region   : $REGION"
echo "    Dry run  : $DRY_RUN"
echo ""

# ---------------------------------------------------------------------------
# Step 1 — clean build dir
# ---------------------------------------------------------------------------
echo "[1/4] Preparing build directory..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/package"

# ---------------------------------------------------------------------------
# Step 2 — install runtime dependencies (boto3 is pre-installed in Lambda
# runtime, but we include it for an exact version pin)
# ---------------------------------------------------------------------------
echo "[2/4] Installing dependencies..."
pip install -q \
  --target "$BUILD_DIR/package" \
  --requirement "$LAMBDA_SRC/requirements.txt"

# ---------------------------------------------------------------------------
# Step 3 — copy source and zip
# ---------------------------------------------------------------------------
echo "[3/4] Packaging Lambda source..."
cp -r "$LAMBDA_SRC"/. "$BUILD_DIR/package/"

cd "$BUILD_DIR/package"
zip -r "$ZIP_PATH" . \
  --exclude "*.pyc" \
  --exclude "__pycache__/*" \
  --exclude "*.dist-info/*" \
  > /dev/null
cd - > /dev/null

ZIP_SIZE=$(du -sh "$ZIP_PATH" | cut -f1)
echo "      Package size: $ZIP_SIZE  →  $ZIP_PATH"

# ---------------------------------------------------------------------------
# Step 4 — upload to Lambda
# ---------------------------------------------------------------------------
if $DRY_RUN; then
  echo "[4/4] Dry run — skipping upload."
else
  echo "[4/4] Uploading to Lambda..."
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_PATH" \
    --region "$REGION" \
    --query "FunctionArn" \
    --output text

  # Wait for the update to complete before returning
  aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

  echo ""
  echo "==> Deploy complete. Tail logs:"
  echo "    aws logs tail /aws/lambda/$FUNCTION_NAME --follow --region $REGION"
fi
