'use client';

import { useEffect, useState } from 'react';
import { loadStripe } from '@stripe/stripe-js';

interface EmbeddedCheckoutProps {
  clientSecret: string;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

export default function EmbeddedCheckout({
  clientSecret,
  onComplete,
  onError
}: EmbeddedCheckoutProps) {
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const initializeCheckout = async () => {
      try {
        // Get the publishable key from env
        const publishableKey = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;

        if (!publishableKey) {
          const error = 'Stripe publishable key not configured';
          console.error(error);
          onError?.(error);
          return;
        }

        // Load Stripe
        const stripe = await loadStripe(publishableKey);

        if (!stripe) {
          const error = 'Failed to load Stripe';
          console.error(error);
          onError?.(error);
          return;
        }

        // Mount the embedded checkout
        const checkout = await stripe.initEmbeddedCheckout({
          clientSecret,
        });

        checkout.mount('#embedded-checkout');
        setIsLoading(false);

        // Handle completion
        checkout.on('complete', () => {
          onComplete?.();
        });

      } catch (error) {
        console.error('Error initializing checkout:', error);
        onError?.(error instanceof Error ? error.message : 'Failed to initialize checkout');
        setIsLoading(false);
      }
    };

    if (clientSecret) {
      initializeCheckout();
    }

    // Cleanup function
    return () => {
      const checkoutElement = document.getElementById('embedded-checkout');
      if (checkoutElement) {
        checkoutElement.innerHTML = '';
      }
    };
  }, [clientSecret, onComplete, onError]);

  return (
    <div className="w-full">
      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
      )}
      <div id="embedded-checkout" className="w-full"></div>
    </div>
  );
}
