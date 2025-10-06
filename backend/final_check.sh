#!/bin/bash
echo "🔍 Final Pre-Commit Verification"
echo "=================================="

errors=0

# Check syntax
echo "1. Checking Python syntax..."
python3 -m py_compile \
  app/services/unified_bet_verification_service.py \
  app/services/simple_unified_bet_service.py \
  app/services/bet_scheduler_service.py \
  test_unified_bet_verification.py 2>&1

if [ $? -eq 0 ]; then
  echo "   ✅ All files compile"
else
  echo "   ❌ Syntax errors found"
  ((errors++))
fi

# Check file endings (should be exactly 1 newline)
echo "2. Checking file endings..."
for file in \
  app/services/unified_bet_verification_service.py \
  app/services/simple_unified_bet_service.py \
  app/services/bet_scheduler_service.py \
  test_unified_bet_verification.py
do
  # Count trailing newlines
  trailing=$(tail -c 2 "$file" | od -An -tx1 | tr -d ' ')
  if [ "$trailing" = "0a" ]; then
    echo "   ✅ $file - single newline"
  else
    echo "   ❌ $file - incorrect ending: $trailing"
    ((errors++))
  fi
done

# Check for trailing whitespace
echo "3. Checking for trailing whitespace..."
if grep -n '[[:space:]]$' \
  app/services/unified_bet_verification_service.py \
  app/services/simple_unified_bet_service.py \
  app/services/bet_scheduler_service.py \
  test_unified_bet_verification.py 2>/dev/null; then
  echo "   ❌ Trailing whitespace found"
  ((errors++))
else
  echo "   ✅ No trailing whitespace"
fi

# Check line lengths
echo "4. Checking line lengths (max 88)..."
long_lines=$(grep -n '.\{89\}' \
  app/services/unified_bet_verification_service.py \
  app/services/simple_unified_bet_service.py \
  app/services/bet_scheduler_service.py \
  test_unified_bet_verification.py 2>/dev/null | wc -l)

if [ "$long_lines" -gt 0 ]; then
  echo "   ❌ Found $long_lines lines > 88 characters"
  ((errors++))
else
  echo "   ✅ All lines ≤ 88 characters"
fi

echo ""
echo "=================================="
if [ $errors -eq 0 ]; then
  echo "✅ ALL CHECKS PASSED"
  echo "🚀 Ready to commit and push!"
  exit 0
else
  echo "❌ $errors CHECK(S) FAILED"
  echo "Please fix the issues above"
  exit 1
fi
