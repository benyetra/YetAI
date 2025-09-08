# Lighthouse CI Configuration

This document explains the Lighthouse CI setup for the frontend deployment pipeline.

## Current Status

Lighthouse audits are **DISABLED** by default to prevent deployment pipeline failures.

## Configuration Files

- `lighthouserc.js` - Lighthouse CI configuration
- `.github/workflows/frontend-ci-cd.yml` - GitHub Actions workflow with Lighthouse job

## Enabling/Disabling Lighthouse Audits

### Method 1: Using the Toggle Script
```bash
# Enable Lighthouse audits
./scripts/toggle-lighthouse.sh enable

# Disable Lighthouse audits  
./scripts/toggle-lighthouse.sh disable
```

### Method 2: Manual Configuration
Edit `.github/workflows/frontend-ci-cd.yml` and change:
```yaml
env:
  ENABLE_LIGHTHOUSE: 'true'  # or 'false' to disable
```

## Required Secrets (Optional)

For advanced Lighthouse CI features, you can add these GitHub secrets:

- `LHCI_GITHUB_APP_TOKEN` - Lighthouse CI GitHub App token
- `LHCI_TOKEN` - Lighthouse CI server token

If these secrets are not provided, Lighthouse will use temporary public storage for reports.

## Lighthouse Configuration

The current configuration in `lighthouserc.js`:

- **URLs Tested**: Home, Login, Dashboard, Chat pages
- **Thresholds**: Lenient scores to avoid blocking deployments
- **Storage**: Temporary public storage (no external setup required)
- **Runs**: Single run per URL for CI performance

## Troubleshooting

If Lighthouse audits are failing:

1. **Quick Fix**: Disable Lighthouse temporarily
   ```bash
   ./scripts/toggle-lighthouse.sh disable
   ```

2. **Check Site Accessibility**: Ensure the deployed site is accessible at https://yetai.app

3. **Review Reports**: Check the uploaded Lighthouse reports artifact in GitHub Actions

4. **Adjust Thresholds**: Lower the minimum scores in `lighthouserc.js` if needed

## Best Practices

- Keep Lighthouse audits disabled during active development
- Enable for release branches or periodic audits
- Review Lighthouse reports regularly for performance insights
- Adjust thresholds based on application requirements