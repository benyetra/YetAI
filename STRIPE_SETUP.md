# Stripe Subscription Setup

## Environment Variables Required

Add these to your Railway environment variables:

```bash
STRIPE_SECRET_KEY=sk_test_... # Get from Stripe Dashboard
STRIPE_PRO_PRICE_ID=price_... # Create a recurring price in Stripe for $19/month
STRIPE_WEBHOOK_SECRET=whsec_... # Optional: for webhook signature verification
```

## Steps to Set Up

### 1. Create Stripe Account
- Go to https://stripe.com
- Sign up for an account
- Switch to Test mode (toggle in top right)

### 2. Create Product and Price
1. Go to Products in Stripe Dashboard
2. Click "+ Add Product"
3. Name: "YetAI Pro"
4. Description: "Pro subscription for YetAI"
5. Pricing model: Recurring
6. Price: $19.00 USD
7. Billing period: Monthly
8. Copy the Price ID (starts with `price_...`)

### 3. Get API Keys
1. Go to Developers > API Keys
2. Copy the "Secret key" (starts with `sk_test_...`)
3. Add to Railway as `STRIPE_SECRET_KEY`
4. Add the Price ID as `STRIPE_PRO_PRICE_ID`

### 4. Set Up Webhooks (Optional but Recommended)
1. Go to Developers > Webhooks
2. Click "+ Add endpoint"
3. Endpoint URL: `https://api.yetai.app/api/subscription/webhook`
4. Events to listen for:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
5. Copy the Signing secret (starts with `whsec_...`)
6. Add to Railway as `STRIPE_WEBHOOK_SECRET`

## Database Migration

The User model has been updated with new fields:
- `subscription_status`
- `subscription_current_period_end`
- `stripe_subscription_id`

You need to add these columns to the database:

```sql
ALTER TABLE users ADD COLUMN subscription_status VARCHAR(50);
ALTER TABLE users ADD COLUMN subscription_current_period_end TIMESTAMP;
ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR(255);
```

## Testing the Flow

### Test Mode
1. Go to https://yetai.app/upgrade
2. Click "Upgrade to Pro"
3. Use Stripe test card: `4242 4242 4242 4242`
4. Any future expiry date
5. Any CVC
6. Complete checkout

### Verify
- Check user's subscription_tier is updated to 'pro'
- Check Stripe Dashboard > Payments for the test payment
- Check Stripe Dashboard > Customers for the customer creation

## Going Live

When ready for production:

1. Switch Stripe account to Live mode
2. Create a new Product/Price for production
3. Update Railway environment variables with live keys:
   - `STRIPE_SECRET_KEY=sk_live_...`
   - `STRIPE_PRO_PRICE_ID=price_...` (live price ID)
   - `STRIPE_WEBHOOK_SECRET=whsec_...` (live webhook secret)
4. Update webhook endpoint to production URL

## Troubleshooting

- If checkout URL is not generated, check Railway logs for Stripe errors
- If webhooks don't work, verify the webhook secret is correct
- Test webhooks using Stripe CLI: `stripe listen --forward-to localhost:8000/api/subscription/webhook`
