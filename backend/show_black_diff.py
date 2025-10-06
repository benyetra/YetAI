#!/usr/bin/env python3
"""Show what Black would change without modifying files"""
import subprocess
import sys

files = [
    "app/services/unified_bet_verification_service.py",
    "app/services/simple_unified_bet_service.py",
    "app/services/bet_scheduler_service.py",
    "test_unified_bet_verification.py",
]

print("Checking what Black would change...\n")

for file in files:
    print(f"=== {file} ===")
    result = subprocess.run(
        ["python3", "-m", "black", "--diff", "--line-length=88", file],
        capture_output=True,
        text=True,
    )

    if result.stdout:
        print(result.stdout[:2000])  # Show first 2000 chars
        print(f"\n... (showing first 2000 chars)\n")
    else:
        print("✅ No changes needed\n")
