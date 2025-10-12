"""
Stripe subscription service for handling Pro plan upgrades
"""

import stripe
import os
import logging
from typing import Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.database_models import User

logger = logging.getLogger(__name__)

# Initialize Stripe API key once at module level
_stripe_initialized = False


def _ensure_stripe_initialized():
    """Ensure Stripe is initialized with API key"""
    global _stripe_initialized
    if not _stripe_initialized:
        stripe_key = os.getenv("STRIPE_SECRET_KEY")
        if not stripe_key:
            raise ValueError(
                "STRIPE_SECRET_KEY environment variable not set. Please configure it in Railway."
            )

        # Trim whitespace and validate format
        stripe_key = stripe_key.strip()

        if not (stripe_key.startswith("sk_test_") or stripe_key.startswith("sk_live_")):
            raise ValueError(
                f"Invalid STRIPE_SECRET_KEY format. Key should start with 'sk_test_' or 'sk_live_', but starts with '{stripe_key[:10]}...'"
            )

        stripe.api_key = stripe_key
        _stripe_initialized = True
        logger.info(
            f"Stripe initialized with key length: {len(stripe_key)}, starts with: {stripe_key[:8]}..."
        )


class SubscriptionService:
    def __init__(self, db: Session):
        self.db = db
        # Ensure Stripe is initialized
        _ensure_stripe_initialized()

    def create_checkout_session(
        self, user: User, tier: str, return_url: str
    ) -> Dict[str, str]:
        """Create a Stripe Checkout session for subscription upgrade"""
        try:
            # Get price ID from environment
            if tier == "pro":
                price_id = os.getenv("STRIPE_PRO_PRICE_ID", "")
            else:
                raise ValueError(f"Invalid subscription tier: {tier}")

            if not price_id:
                raise ValueError(
                    f"Stripe Price ID not configured for tier: {tier}. Please set STRIPE_PRO_PRICE_ID environment variable."
                )

            # Create or retrieve Stripe customer
            if not user.stripe_customer_id:
                logger.info("Creating new Stripe customer")
                try:
                    # Use raw API call to bypass SDK object parsing issues
                    import requests

                    api_key = stripe.api_key
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    }

                    data = {
                        "email": user.email,
                        "name": f"{user.first_name} {user.last_name}",
                        "metadata[user_id]": str(user.id),
                        "metadata[username]": user.username,
                    }

                    response = requests.post(
                        "https://api.stripe.com/v1/customers",
                        headers=headers,
                        data=data,
                    )

                    logger.info(f"Raw API response status: {response.status_code}")

                    if response.status_code == 200:
                        customer_data = response.json()
                        customer_id = customer_data.get("id")
                        logger.info(
                            f"Successfully got customer ID from raw API: {customer_id}"
                        )

                        user.stripe_customer_id = customer_id
                        self.db.commit()

                        # Create a simple object to use later
                        class CustomerObj:
                            def __init__(self, cid):
                                self.id = cid

                        customer = CustomerObj(customer_id)
                    else:
                        logger.error(f"API error: {response.text}")
                        raise Exception(f"Failed to create customer: {response.text}")

                except Exception as e:
                    logger.error(f"Exception during customer creation: {e}")
                    logger.error(f"Exception type: {type(e)}")
                    raise
            else:
                logger.info(f"Retrieving existing customer: {user.stripe_customer_id}")
                # Use raw API to retrieve
                import requests

                api_key = stripe.api_key
                headers = {"Authorization": f"Bearer {api_key}"}

                response = requests.get(
                    f"https://api.stripe.com/v1/customers/{user.stripe_customer_id}",
                    headers=headers,
                )

                if response.status_code == 200:
                    customer_data = response.json()
                    customer_id = customer_data.get("id")
                    logger.info(f"Successfully retrieved customer: {customer_id}")

                    class CustomerObj:
                        def __init__(self, cid):
                            self.id = cid

                    customer = CustomerObj(customer_id)
                else:
                    logger.error(f"Failed to retrieve customer: {response.text}")
                    logger.info("Creating new customer instead")
                    # Use raw API to create
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                    data = {
                        "email": user.email,
                        "name": f"{user.first_name} {user.last_name}",
                        "metadata[user_id]": str(user.id),
                        "metadata[username]": user.username,
                    }
                    response = requests.post(
                        "https://api.stripe.com/v1/customers",
                        headers=headers,
                        data=data,
                    )
                    if response.status_code == 200:
                        customer_data = response.json()
                        customer_id = customer_data.get("id")
                        logger.info(f"Created new customer: {customer_id}")
                        user.stripe_customer_id = customer_id
                        self.db.commit()
                        customer = CustomerObj(customer_id)
                    else:
                        raise Exception(f"Failed to create customer: {response.text}")

            # Validate customer object before proceeding
            if not customer or not hasattr(customer, "id"):
                logger.error(f"Invalid customer object: {customer}")
                raise Exception("Failed to get valid customer object from Stripe")

            # Create checkout session using raw API
            logger.info(f"About to create checkout session:")
            logger.info(f"  customer_id: {customer.id}")
            logger.info(f"  price_id: '{price_id}'")
            logger.info(f"  price_id type: {type(price_id)}")
            logger.info(f"  return_url: {return_url}")

            if not price_id:
                raise ValueError("Price ID is empty or None")

            import requests

            api_key = stripe.api_key
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            }

            data = {
                "customer": customer.id,  # Email is already on the customer object
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
                "mode": "subscription",
                "ui_mode": "embedded",
                "return_url": f"{return_url}?session_id={{CHECKOUT_SESSION_ID}}&upgrade=success",
                "payment_method_types[0]": "card",
                "automatic_tax[enabled]": "false",
                "metadata[user_id]": str(user.id),
                "metadata[tier]": tier,
                "subscription_data[metadata][user_id]": str(user.id),
                "subscription_data[metadata][tier]": tier,
            }

            response = requests.post(
                "https://api.stripe.com/v1/checkout/sessions",
                headers=headers,
                data=data,
            )

            logger.info(f"Checkout session API response status: {response.status_code}")

            if response.status_code == 200:
                session_data = response.json()
                session_id = session_data.get("id")
                client_secret = session_data.get("client_secret")
                logger.info(
                    f"Created checkout session for user {user.id}: {session_id}"
                )

                return {
                    "client_secret": client_secret,
                    "session_id": session_id,
                }
            else:
                logger.error(f"Checkout session API error: {response.text}")
                raise Exception(f"Failed to create checkout session: {response.text}")

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating checkout session: {e}")
            raise Exception(f"Payment processing error: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating checkout session: {e}")
            raise

    def get_session_status(self, session_id: str, user: User) -> Dict:
        """Get checkout session status and update user if completed"""
        try:
            import requests

            api_key = stripe.api_key
            headers = {"Authorization": f"Bearer {api_key}"}

            # Retrieve session from Stripe
            response = requests.get(
                f"https://api.stripe.com/v1/checkout/sessions/{session_id}",
                headers=headers,
                params={"expand[]": "subscription"},
            )

            if response.status_code != 200:
                logger.error(f"Failed to retrieve session: {response.text}")
                return {"status": "error", "message": "Failed to retrieve session"}

            session = response.json()
            payment_status = session.get("payment_status")

            logger.info(f"Session {session_id} payment status: {payment_status}")

            # If payment is complete, update the user
            if payment_status == "paid":
                tier = session.get("metadata", {}).get("tier", "pro")
                subscription_id = session.get("subscription")

                # Update user subscription
                user.subscription_tier = tier
                user.stripe_subscription_id = (
                    subscription_id
                    if isinstance(subscription_id, str)
                    else subscription_id.get("id") if subscription_id else None
                )

                # Get subscription details
                if subscription_id:
                    sub_id = (
                        subscription_id
                        if isinstance(subscription_id, str)
                        else subscription_id.get("id")
                    )
                    logger.info(f"Fetching subscription details for: {sub_id}")
                    sub_response = requests.get(
                        f"https://api.stripe.com/v1/subscriptions/{sub_id}",
                        headers=headers,
                    )
                    logger.info(
                        f"Subscription fetch status: {sub_response.status_code}"
                    )

                    if sub_response.status_code == 200:
                        subscription_data = sub_response.json()
                        logger.info(f"Subscription data: {subscription_data}")

                        user.subscription_status = subscription_data.get("status")

                        # Safely handle period_end timestamp
                        period_end = subscription_data.get("current_period_end")
                        if period_end:
                            user.subscription_current_period_end = (
                                datetime.fromtimestamp(period_end)
                            )
                            logger.info(
                                f"Set period_end: {user.subscription_current_period_end}"
                            )
                        else:
                            logger.warning("No current_period_end in subscription data")
                    else:
                        logger.error(
                            f"Failed to fetch subscription: {sub_response.text}"
                        )

                self.db.commit()
                logger.info(f"Updated user {user.id} subscription to {tier}")

                return {
                    "status": "complete",
                    "payment_status": payment_status,
                    "tier": tier,
                }
            else:
                return {
                    "status": "incomplete",
                    "payment_status": payment_status,
                }

        except Exception as e:
            logger.error(f"Error getting session status: {e}")
            return {"status": "error", "message": str(e)}

    def handle_checkout_completed(self, session: Dict) -> None:
        """Handle successful checkout completion webhook"""
        try:
            user_id = session["metadata"]["user_id"]
            tier = session["metadata"]["tier"]
            subscription_id = session.get("subscription")

            user = self.db.query(User).filter(User.id == user_id).first()
            if not user:
                logger.error(f"User not found for checkout completion: {user_id}")
                return

            # Update user subscription
            user.subscription_tier = tier
            user.stripe_subscription_id = subscription_id

            # Get subscription details from Stripe
            if subscription_id:
                subscription = stripe.Subscription.retrieve(subscription_id)
                user.subscription_status = subscription.status
                user.subscription_current_period_end = datetime.fromtimestamp(
                    subscription.current_period_end
                )

            self.db.commit()
            logger.info(f"Updated user {user_id} subscription to {tier}")

        except Exception as e:
            logger.error(f"Error handling checkout completion: {e}")
            self.db.rollback()
            raise

    def handle_subscription_updated(self, subscription: Dict) -> None:
        """Handle subscription update webhook (renewal, cancellation, etc.)"""
        try:
            subscription_id = subscription["id"]
            user = (
                self.db.query(User)
                .filter(User.stripe_subscription_id == subscription_id)
                .first()
            )

            if not user:
                logger.error(
                    f"User not found for subscription update: {subscription_id}"
                )
                return

            # Update subscription status
            user.subscription_status = subscription["status"]
            user.subscription_current_period_end = datetime.fromtimestamp(
                subscription["current_period_end"]
            )

            # Handle cancellation
            if subscription["status"] == "canceled":
                user.subscription_tier = "free"
                user.stripe_subscription_id = None
                logger.info(f"Downgraded user {user.id} to free tier")

            self.db.commit()
            logger.info(f"Updated subscription for user {user.id}")

        except Exception as e:
            logger.error(f"Error handling subscription update: {e}")
            self.db.rollback()
            raise

    def cancel_subscription(self, user: User) -> Dict:
        """Cancel a user's subscription"""
        try:
            if not user.stripe_subscription_id:
                return {"success": False, "error": "No active subscription found"}

            # Cancel at period end (don't immediately revoke access)
            subscription = stripe.Subscription.modify(
                user.stripe_subscription_id, cancel_at_period_end=True
            )

            user.subscription_status = "canceling"
            self.db.commit()

            logger.info(f"Cancelled subscription for user {user.id}")

            return {
                "success": True,
                "message": "Subscription will be cancelled at the end of the billing period",
                "period_end": datetime.fromtimestamp(
                    subscription.current_period_end
                ).isoformat(),
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error cancelling subscription: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Error cancelling subscription: {e}")
            return {"success": False, "error": "Failed to cancel subscription"}

    def get_subscription_info(self, user: User) -> Optional[Dict]:
        """Get current subscription information for a user"""
        try:
            if not user.stripe_subscription_id:
                return None

            subscription = stripe.Subscription.retrieve(user.stripe_subscription_id)

            return {
                "tier": user.subscription_tier,
                "status": subscription.status,
                "current_period_end": datetime.fromtimestamp(
                    subscription.current_period_end
                ).isoformat(),
                "cancel_at_period_end": subscription.cancel_at_period_end,
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error getting subscription info: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting subscription info: {e}")
            return None
