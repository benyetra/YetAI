#!/usr/bin/env python3
"""Test SMTP connection from Railway environment"""
import smtplib
import os
import sys
import socket

SMTP_HOST = os.getenv("SMTP_HOST", "smtp-relay.brevo.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

print(f"Testing SMTP connection to {SMTP_HOST}:{SMTP_PORT}")
print(f"SMTP_USER: {SMTP_USER}")
print(f"Environment: {os.getenv('ENVIRONMENT', 'unknown')}")
print()

# Test DNS resolution
try:
    print("Step 1: DNS Resolution")
    ip_address = socket.gethostbyname(SMTP_HOST)
    print(f"✅ {SMTP_HOST} resolves to {ip_address}")
except Exception as e:
    print(f"❌ DNS resolution failed: {e}")
    sys.exit(1)

# Test TCP connection
try:
    print("\nStep 2: TCP Connection")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect((SMTP_HOST, SMTP_PORT))
    print(f"✅ TCP connection successful to {SMTP_HOST}:{SMTP_PORT}")
    sock.close()
except Exception as e:
    print(f"❌ TCP connection failed: {e}")
    sys.exit(1)

# Test SMTP connection
try:
    print("\nStep 3: SMTP Connection")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        print(f"✅ SMTP connection established")

        print("\nStep 4: STARTTLS")
        server.starttls()
        print(f"✅ TLS negotiation successful")

        print("\nStep 5: Authentication")
        server.login(SMTP_USER, SMTP_PASSWORD)
        print(f"✅ Authentication successful")

    print("\n🎉 All SMTP tests passed!")
except socket.timeout as e:
    print(f"❌ Connection timed out: {e}")
    sys.exit(1)
except smtplib.SMTPException as e:
    print(f"❌ SMTP error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    sys.exit(1)
