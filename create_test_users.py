#!/usr/bin/env python3
"""
User Management Script for YetAI Sports Betting MVP
Creates and manages test users for development and testing.
"""

import requests
import json
import sys
from typing import List, Dict

API_BASE_URL = "http://localhost:8000"

def create_user(email: str, password: str, first_name: str = "", last_name: str = "") -> Dict:
    """Create a new user account"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/auth/signup",
            json={
                "email": email,
                "password": password,
                "first_name": first_name,
                "last_name": last_name
            },
            headers={"Content-Type": "application/json"}
        )
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def login_user(email: str, password: str) -> Dict:
    """Login with user credentials"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/auth/login",
            json={
                "email": email,
                "password": password
            },
            headers={"Content-Type": "application/json"}
        )
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def create_demo_users() -> Dict:
    """Create demo users for testing"""
    try:
        response = requests.post(f"{API_BASE_URL}/api/auth/demo-users")
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def print_user_info(user_data: Dict):
    """Print user information in a nice format"""
    if user_data.get("status") == "success":
        user = user_data.get("user", {})
        print(f"✅ User created successfully!")
        print(f"   ID: {user.get('id')}")
        print(f"   Email: {user.get('email')}")
        print(f"   Name: {user.get('first_name', '')} {user.get('last_name', '')}")
        print(f"   Tier: {user.get('subscription_tier', 'free')}")
        if user_data.get("access_token"):
            print(f"   Token: {user_data['access_token'][:20]}...")
    else:
        print(f"❌ Error: {user_data.get('message', 'Unknown error')}")

def main():
    print("🎮 YetAI Sports Betting - User Management Tool")
    print("=" * 50)
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python create_test_users.py demo                    # Create demo users")
        print("  python create_test_users.py create <email> <pass>   # Create new user")
        print("  python create_test_users.py login <email> <pass>    # Test login")
        print("  python create_test_users.py batch                   # Create batch test users")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "demo":
        print("Creating demo users...")
        result = create_demo_users()
        if result.get("status") == "success":
            print("✅ Demo users created!")
            for account in result.get("demo_accounts", []):
                print(f"   📧 {account['email']} | 🔑 {account['password']} | 🏷️ {account['tier']}")
        else:
            print(f"❌ Error: {result.get('message', 'Unknown error')}")
    
    elif command == "create":
        if len(sys.argv) < 4:
            print("Usage: python create_test_users.py create <email> <password> [first_name] [last_name]")
            sys.exit(1)
        
        email = sys.argv[2]
        password = sys.argv[3]
        first_name = sys.argv[4] if len(sys.argv) > 4 else ""
        last_name = sys.argv[5] if len(sys.argv) > 5 else ""
        
        print(f"Creating user: {email}")
        result = create_user(email, password, first_name, last_name)
        print_user_info(result)
    
    elif command == "login":
        if len(sys.argv) < 4:
            print("Usage: python create_test_users.py login <email> <password>")
            sys.exit(1)
        
        email = sys.argv[2]
        password = sys.argv[3]
        
        print(f"Testing login: {email}")
        result = login_user(email, password)
        print_user_info(result)
    
    elif command == "batch":
        print("Creating batch test users...")
        test_users = [
            ("alice@test.com", "test123", "Alice", "Johnson"),
            ("bob@test.com", "test123", "Bob", "Smith"),
            ("charlie@test.com", "test123", "Charlie", "Brown"),
            ("diana@test.com", "test123", "Diana", "Wilson"),
            ("emma@test.com", "test123", "Emma", "Davis")
        ]
        
        for email, password, first_name, last_name in test_users:
            print(f"\nCreating: {email}")
            result = create_user(email, password, first_name, last_name)
            print_user_info(result)
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()