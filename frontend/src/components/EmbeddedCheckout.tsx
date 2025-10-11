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
    let checkoutInstance: any = null;

    const initializeCheckout = async () => {
      try {
        // Get the publishable key from env
        const publishableKey = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;

        console.log('Initializing checkout with publishable key:', publishableKey ? 'present' : 'missing');
        console.log('Client secret:', clientSecret ? 'present' : 'missing');

        if (!publishableKey) {
          const error = 'Stripe publishable key not configured. Please add NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY to Vercel environment variables.';
          console.error(error);
          onError?.(error);
          setIsLoading(false);
          return;
        }

        if (!clientSecret) {
          const error = 'Client secret is missing';
          console.error(error);
          onError?.(error);
          setIsLoading(false);
          return;
        }

        // Load Stripe
        console.log('Loading Stripe...');
        const stripe = await loadStripe(publishableKey);

        if (!stripe) {
          const error = 'Failed to load Stripe';
          console.error(error);
          onError?.(error);
          setIsLoading(false);
          return;
        }

        console.log('Stripe loaded successfully');
        console.log('Initializing embedded checkout...');

        // Mount the embedded checkout
        const checkout = await stripe.initEmbeddedCheckout({
          clientSecret,
        });

        console.log('Checkout object:', checkout);
        console.log('Checkout type:', typeof checkout);
        console.log('Has mount method:', typeof checkout?.mount === 'function');
        console.log('Has on method:', typeof checkout?.on === 'function');

        if (!checkout || typeof checkout.mount !== 'function') {
          const error = 'Invalid checkout object returned from Stripe';
          console.error(error, checkout);
          onError?.(error);
          setIsLoading(false);
          return;
        }

        checkout.mount('#embedded-checkout');
        setIsLoading(false);
        checkoutInstance = checkout;

        // Handle completion
        if (typeof checkout.on === 'function') {
          checkout.on('complete', () => {
            console.log('Checkout completed!');
            onComplete?.();
          });
        }

      } catch (error) {
        console.error('Error initializing checkout:', error);
        onError?.(error instanceof Error ? error.message : 'Failed to initialize checkout');
        setIsLoading(false);
      }
    };

    if (clientSecret) {
      initializeCheckout();
    }

    // Cleanup function - properly destroy the checkout instance
    return () => {
      console.log('Cleaning up checkout instance');
      if (checkoutInstance && typeof checkoutInstance.destroy === 'function') {
        try {
          checkoutInstance.destroy();
          console.log('Checkout instance destroyed');
        } catch (e) {
          console.error('Error destroying checkout:', e);
        }
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
