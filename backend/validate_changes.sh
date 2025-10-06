#!/bin/bash
# Validation script for bet verification changes

echo "🔍 Validating Bet Verification Changes"
echo "========================================"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

errors=0

# 1. Check Python syntax
echo -e "\n📝 Checking Python syntax..."
python3 -m py_compile app/services/unified_bet_verification_service.py 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ unified_bet_verification_service.py - OK${NC}"
else
    echo -e "${RED}❌ unified_bet_verification_service.py - SYNTAX ERROR${NC}"
    ((errors++))
fi

python3 -m py_compile app/services/simple_unified_bet_service.py 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ simple_unified_bet_service.py - OK${NC}"
else
    echo -e "${RED}❌ simple_unified_bet_service.py - SYNTAX ERROR${NC}"
    ((errors++))
fi

python3 -m py_compile app/services/bet_scheduler_service.py 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ bet_scheduler_service.py - OK${NC}"
else
    echo -e "${RED}❌ bet_scheduler_service.py - SYNTAX ERROR${NC}"
    ((errors++))
fi

# 2. Check for old service imports
echo -e "\n🔍 Checking for deprecated service imports..."
if grep -r "from.*bet_verification_service import BetVerificationService" app/ 2>/dev/null | grep -v "__pycache__" | grep -v ".pyc"; then
    echo -e "${RED}❌ Found import of old BetVerificationService${NC}"
    ((errors++))
else
    echo -e "${GREEN}✅ No imports of old BetVerificationService${NC}"
fi

# 3. Check that unified service is used
echo -e "\n🔍 Checking unified service usage..."
if grep -q "unified_bet_verification_service" app/services/bet_scheduler_service.py; then
    echo -e "${GREEN}✅ Scheduler uses unified_bet_verification_service${NC}"
else
    echo -e "${RED}❌ Scheduler doesn't use unified_bet_verification_service${NC}"
    ((errors++))
fi

# 4. Check for proper enum usage (not string comparisons)
echo -e "\n🔍 Checking for enum usage (no string status comparisons)..."
if grep -E "\.status == ['\"]pending['\"]|\.status == ['\"]won['\"]" app/services/unified_bet_verification_service.py 2>/dev/null; then
    echo -e "${RED}❌ Found string status comparisons (should use BetStatus enum)${NC}"
    ((errors++))
else
    echo -e "${GREEN}✅ No string status comparisons found${NC}"
fi

# 5. Check for team name matching (not array index)
echo -e "\n🔍 Checking score matching logic..."
if grep -q "team_name == bet.home_team" app/services/unified_bet_verification_service.py; then
    echo -e "${GREEN}✅ Score matching uses team names${NC}"
else
    echo -e "${YELLOW}⚠️  Could not verify team name matching${NC}"
fi

# 6. Check for completed field check
echo -e "\n🔍 Checking game completion logic..."
if grep -q "game_data.get(\"completed\")" app/services/unified_bet_verification_service.py; then
    echo -e "${GREEN}✅ Uses 'completed' field from API${NC}"
else
    echo -e "${RED}❌ Doesn't check 'completed' field properly${NC}"
    ((errors++))
fi

# 7. Check documentation
echo -e "\n📚 Checking documentation..."
if grep -q "THE ONLY SERVICE FOR BET VERIFICATION" app/services/unified_bet_verification_service.py; then
    echo -e "${GREEN}✅ Verification service has proper documentation${NC}"
else
    echo -e "${YELLOW}⚠️  Verification service missing documentation${NC}"
fi

if grep -q "THE ONLY SERVICE FOR BET CREATION" app/services/simple_unified_bet_service.py; then
    echo -e "${GREEN}✅ Bet creation service has proper documentation${NC}"
else
    echo -e "${YELLOW}⚠️  Bet creation service missing documentation${NC}"
fi

# 8. Check for deprecated file marker
echo -e "\n🗑️  Checking deprecated file marker..."
if [ -f "DEPRECATED_bet_verification_service.py" ]; then
    echo -e "${GREEN}✅ Deprecated service file marker exists${NC}"
else
    echo -e "${YELLOW}⚠️  No deprecated service marker found${NC}"
fi

# Summary
echo -e "\n========================================"
if [ $errors -eq 0 ]; then
    echo -e "${GREEN}✅ ALL VALIDATION CHECKS PASSED${NC}"
    echo -e "${GREEN}🎉 Changes are ready for testing!${NC}"
    exit 0
else
    echo -e "${RED}❌ $errors VALIDATION ERROR(S) FOUND${NC}"
    echo -e "${YELLOW}Please fix the errors above before proceeding${NC}"
    exit 1
fi
