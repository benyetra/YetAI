#!/bin/bash

# Script to enable/disable Lighthouse audits in GitHub Actions workflow

WORKFLOW_FILE=".github/workflows/frontend-ci-cd.yml"

if [ "$1" = "enable" ]; then
    echo "Enabling Lighthouse audits..."
    sed -i '' "s/ENABLE_LIGHTHOUSE: 'false'/ENABLE_LIGHTHOUSE: 'true'/" "$WORKFLOW_FILE"
    echo "✅ Lighthouse audits enabled"
    echo "⚠️  Note: Requires LHCI_GITHUB_APP_TOKEN and LHCI_TOKEN secrets or will use temporary storage"
elif [ "$1" = "disable" ]; then
    echo "Disabling Lighthouse audits..."
    sed -i '' "s/ENABLE_LIGHTHOUSE: 'true'/ENABLE_LIGHTHOUSE: 'false'/" "$WORKFLOW_FILE"
    echo "✅ Lighthouse audits disabled"
else
    echo "Usage: $0 [enable|disable]"
    echo "Current status:"
    grep "ENABLE_LIGHTHOUSE" "$WORKFLOW_FILE" || echo "Not found"
fi