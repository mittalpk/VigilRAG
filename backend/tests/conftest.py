"""
Global pytest configuration and fixtures for backend tests.
Sets up secure test environment variables before module imports.
"""

import os

os.environ["INTERNAL_API_KEY"] = "secure-test-internal-api-key-9999"
os.environ["SECRET_KEY"] = "secure-test-secret-key-9999-jwt"
os.environ["ADMIN_PASSWORD"] = "secure-test-admin-password-9999"
os.environ["DEMO_MODE"] = "false"
