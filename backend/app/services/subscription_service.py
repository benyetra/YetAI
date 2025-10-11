import stripe
import os
from typing import Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.database_models import User
from app.core.logger import get_logger

logger = get_logger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Price IDs for subscription tiers (these will be created in Stripe Dashboard)
STRIPE_PRICE_IDS = {
    "pro": os.getenv("STRIPE_PRO_PRICE_ID", ""),  # Monthly Pro subscription
}


class SubscriptionService:
    def __init__(self, db: Session):
        self.db = db

    def create_checkout_session(
        self, user: User, tier: str, return_url: str
    ) -> Dict[str, str]:
        """Create a Stripe Checkout session for subscription upgrade"""
        try:
            if tier not in STRIPE_PRICE_IDS:
                raise ValueError(f"Invalid subscription tier: {tier}")

            price_id = STRIPE_PRICE_IDS[tier]
            if not price_id:
                raise ValueError(
                    f"Stripe Price ID not configured for tier: {tier}. Please set STRIPE_PRO_PRICE_ID environment variable."
                )

            # Create or retrieve Stripe customer
            if not user.stripe_customer_id:
                customer = stripe.Customer.create(
                    email=user.email,
                    name=f"{user.first_name} {user.last_name}",
                    metadata={"user_id": str(user.id), "username": user.username},
                )
                user.stripe_customer_id = customer.id
                self.db.commit()
            else:
                customer = stripe.Customer.retrieve(user.stripe_customer_id)

            # Create checkout session
            checkout_session = stripe.checkout.Session.create(
                customer=customer.id,
                payment_method_types=["card"],
                line_items=[
                    {
                        "price": price_id,
                        "quantity": 1,
                    }
                ],
                mode="subscription",
                success_url=f"{return_url}?session_id={{CHECKOUT_SESSION_ID}}&upgrade=success",
                cancel_url=f"{return_url}?upgrade=cancelled",
                metadata={
                    "user_id": str(user.id),
                    "tier": tier,
                },
                subscription_data={
                    "metadata": {
                        "user_id": str(user.id),
                        "tier": tier,
                    }
                },
            )

            logger.info(
                f"Created checkout session for user {user.id}: {checkout_session.id}"
            )

            return {
                "checkout_url": checkout_session.url,
                "session_id": checkout_session.id,
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating checkout session: {e}")
            raise Exception(f"Payment processing error: {str(e)}")
        except Exception as e:
            logger.error(f"Error creating checkout session: {e}")
            raise

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
