#!/bin/bash

# YetAI Sports Betting - User Management Script
# Creates and manages test users for development and testing.

API_BASE_URL="http://localhost:8000"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🎮 YetAI Sports Betting - User Management Tool${NC}"
echo "=================================================="

# Function to create a user
create_user() {
    local email="$1"
    local password="$2"
    local first_name="$3"
    local last_name="$4"
    
    echo -e "${YELLOW}Creating user: $email${NC}"
    
    result=$(curl -s -X POST "$API_BASE_URL/api/auth/signup" \
        -H "Content-Type: application/json" \
        -d "{\"email\": \"$email\", \"password\": \"$password\", \"first_name\": \"$first_name\", \"last_name\": \"$last_name\"}")
    
    # Check if creation was successful
    if echo "$result" | grep -q '"status":"success"'; then
        echo -e "${GREEN}✅ User created successfully!${NC}"
        user_id=$(echo "$result" | grep -o '"id":[0-9]*' | cut -d':' -f2)
        tier=$(echo "$result" | grep -o '"subscription_tier":"[^"]*"' | cut -d'"' -f4)
        echo -e "   ID: $user_id | Email: $email | Tier: $tier"
    else
        error_msg=$(echo "$result" | grep -o '"message":"[^"]*"' | cut -d'"' -f4)
        echo -e "${RED}❌ Error: $error_msg${NC}"
    fi
}

# Function to login a user
login_user() {
    local email="$1"
    local password="$2"
    
    echo -e "${YELLOW}Testing login: $email${NC}"
    
    result=$(curl -s -X POST "$API_BASE_URL/api/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"email\": \"$email\", \"password\": \"$password\"}")
    
    if echo "$result" | grep -q '"status":"success"'; then
        echo -e "${GREEN}✅ Login successful!${NC}"
        user_id=$(echo "$result" | grep -o '"id":[0-9]*' | cut -d':' -f2)
        tier=$(echo "$result" | grep -o '"subscription_tier":"[^"]*"' | cut -d'"' -f4)
        echo -e "   ID: $user_id | Email: $email | Tier: $tier"
    else
        error_msg=$(echo "$result" | grep -o '"message":"[^"]*"' | cut -d'"' -f4)
        echo -e "${RED}❌ Login failed: $error_msg${NC}"
    fi
}

# Function to create demo users
create_demo_users() {
    echo -e "${YELLOW}Creating demo users...${NC}"
    
    result=$(curl -s -X POST "$API_BASE_URL/api/auth/demo-users")
    
    if echo "$result" | grep -q '"status":"success"'; then
        echo -e "${GREEN}✅ Demo users created!${NC}"
        echo -e "${BLUE}Available demo accounts:${NC}"
        echo -e "   📧 demo@example.com | 🔑 demo123 | 🏷️ free"
        echo -e "   📧 pro@example.com | 🔑 pro123 | 🏷️ pro"
    else
        error_msg=$(echo "$result" | grep -o '"message":"[^"]*"' | cut -d'"' -f4)
        echo -e "${RED}❌ Error creating demo users: $error_msg${NC}"
    fi
}

# Function to create batch test users
create_batch_users() {
    echo -e "${YELLOW}Creating batch test users...${NC}"
    
    # Array of test users (email, password, first_name, last_name)
    users=(
        "alice@test.com test123 Alice Johnson"
        "bob@test.com test123 Bob Smith"
        "charlie@test.com test123 Charlie Brown"
        "diana@test.com test123 Diana Wilson"
        "emma@test.com test123 Emma Davis"
        "frank@test.com test123 Frank Miller"
        "grace@test.com test123 Grace Taylor"
        "henry@test.com test123 Henry Wilson"
    )
    
    for user_info in "${users[@]}"; do
        read -r email password first_name last_name <<< "$user_info"
        echo ""
        create_user "$email" "$password" "$first_name" "$last_name"
        sleep 0.5  # Small delay to avoid overwhelming the server
    done
}

# Parse command line arguments
case "${1:-help}" in
    "demo")
        create_demo_users
        ;;
    "create")
        if [[ $# -lt 3 ]]; then
            echo "Usage: ./create_test_users.sh create <email> <password> [first_name] [last_name]"
            exit 1
        fi
        create_user "$2" "$3" "${4:-}" "${5:-}"
        ;;
    "login")
        if [[ $# -lt 3 ]]; then
            echo "Usage: ./create_test_users.sh login <email> <password>"
            exit 1
        fi
        login_user "$2" "$3"
        ;;
    "batch")
        create_batch_users
        ;;
    "test-all")
        echo -e "${BLUE}Running complete test suite...${NC}"
        create_demo_users
        echo ""
        create_batch_users
        echo ""
        echo -e "${YELLOW}Testing login with demo user...${NC}"
        login_user "demo@example.com" "demo123"
        ;;
    "help"|*)
        echo "Usage:"
        echo "  ./create_test_users.sh demo                    # Create demo users"
        echo "  ./create_test_users.sh create <email> <pass>   # Create new user"
        echo "  ./create_test_users.sh login <email> <pass>    # Test login"
        echo "  ./create_test_users.sh batch                   # Create batch test users"
        echo "  ./create_test_users.sh test-all               # Run all tests"
        echo "  ./create_test_users.sh help                   # Show this help"
        ;;
esac

echo ""
echo -e "${BLUE}✨ User management complete!${NC}"