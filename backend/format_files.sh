#!/bin/bash
# Manual formatting to match Black style

for file in \
  "app/services/unified_bet_verification_service.py" \
  "app/services/simple_unified_bet_service.py" \
  "app/services/bet_scheduler_service.py" \
  "test_unified_bet_verification.py"
do
  echo "Formatting $file..."
  # Remove trailing whitespace
  sed -i '' 's/[[:space:]]*$//' "$file"
  
  # Ensure blank line at end
  echo >> "$file"
done

echo "✅ Manual formatting complete"
