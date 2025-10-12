# Database Migration Instructions

## Adding the `is_hidden` Column to Production

The `is_hidden` column needs to be added to the `users` table in production. Here are three methods to do this:

---

## Method 1: Railway CLI (Recommended)

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login to Railway
railway login

# Link to your project
railway link

# Run the migration
railway run bash backend/scripts/run_migration.sh
```

---

## Method 2: Manual SQL via Railway Dashboard

1. Go to your Railway project dashboard
2. Click on your PostgreSQL database
3. Click "Query" tab
4. Copy and paste the contents of `backend/scripts/add_is_hidden_column.sql`
5. Click "Execute"

The SQL script will:
- Check if the column already exists
- Add the column with `DEFAULT false` if it doesn't exist
- Show a confirmation message

---

## Method 3: Using Railway's PostgreSQL CLI

```bash
# Connect to Railway PostgreSQL
railway connect postgres

# Inside the PostgreSQL prompt, run:
ALTER TABLE users ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT false;

# Verify the column was added:
\d users

# Exit
\q
```

---

## Verification

After running the migration, verify it worked by checking:

1. **Check the logs** - No more errors about `column users.is_hidden does not exist`
2. **Login to the app** - You should be able to login successfully
3. **Admin panel** - The user management page should show the "Hidden" checkbox

---

## What This Column Does

The `is_hidden` column allows admins to hide users from:
- Leaderboards (weekly, monthly, all-time)
- Public displays on login/signup pages
- User avatar displays on marketing pages

This is useful for:
- Test accounts
- Admin/staff accounts
- Inactive or demo accounts

---

## Rollback

If you need to remove the column:

```sql
ALTER TABLE users DROP COLUMN is_hidden;
```

Note: This will lose all "hidden" status information.
