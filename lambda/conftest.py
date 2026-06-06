import os

# Set required env vars before any test module is imported.
# The module-level Config() in handler.py reads these at collection time.
os.environ.setdefault("WINDOW_TABLE", "test-windows")
os.environ.setdefault("ANOMALY_TABLE", "test-anomalies")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
# Prevent boto3 from making real AWS calls during tests
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
