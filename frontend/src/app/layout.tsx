import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "../components/Auth";
import { NotificationProvider } from "../components/NotificationProvider";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "YetAI - AI Sports Betting & Fantasy Insights",
  description: "AI-powered sports betting and fantasy insights platform with real-time odds, predictions, and smart betting tools",
  icons: {
    icon: [
      { url: '/favicon.ico' },
      { url: '/favicon-16x16.png', sizes: '16x16', type: 'image/png' },
      { url: '/favicon-32x32.png', sizes: '32x32', type: 'image/png' },
    ],
    apple: [
      { url: '/apple-touch-icon.png', sizes: '180x180', type: 'image/png' },
    ],
    other: [
      { url: '/android-chrome-192x192.png', sizes: '192x192', type: 'image/png' },
      { url: '/android-chrome-512x512.png', sizes: '512x512', type: 'image/png' },
    ],
  },
  manifest: '/site.webmanifest',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              // Force Safari form controls styling
              function forceFormStyling() {
                // Handle select dropdowns
                const selects = document.querySelectorAll('select');
                selects.forEach(select => {
                  select.style.setProperty('background-color', '#ffffff', 'important');
                  select.style.setProperty('color', '#1f2937', 'important');
                  select.style.setProperty('border', '1px solid #d1d5db', 'important');
                  select.style.setProperty('-webkit-appearance', 'none', 'important');
                  select.style.setProperty('appearance', 'none', 'important');
                  select.style.setProperty('background-image', 'url("data:image/svg+xml,%3csvg xmlns=\\'http://www.w3.org/2000/svg\\' fill=\\'none\\' viewBox=\\'0 0 20 20\\'%3e%3cpath stroke=\\'%236b7280\\' stroke-linecap=\\'round\\' stroke-linejoin=\\'round\\' stroke-width=\\'1.5\\' d=\\'m6 8 4 4 4-4\\'/%3e%3c/svg%3e")', 'important');
                  select.style.setProperty('background-position', 'right 12px center', 'important');
                  select.style.setProperty('background-repeat', 'no-repeat', 'important');
                  select.style.setProperty('background-size', '16px 12px', 'important');
                  select.style.setProperty('padding', '12px 40px 12px 16px', 'important');
                  select.style.setProperty('border-radius', '8px', 'important');
                  
                  // Style options too
                  const options = select.querySelectorAll('option');
                  options.forEach(option => {
                    option.style.setProperty('background-color', '#ffffff', 'important');
                    option.style.setProperty('color', '#1f2937', 'important');
                  });
                });

                // Handle input fields (text, email, password, search)
                const inputs = document.querySelectorAll('input[type="text"], input[type="email"], input[type="password"], input[type="search"], input[type="number"], input[type="tel"], input[type="url"], input:not([type])');
                inputs.forEach(input => {
                  input.style.setProperty('background-color', '#ffffff', 'important');
                  input.style.setProperty('color', '#1f2937', 'important');
                  input.style.setProperty('border', '1px solid #d1d5db', 'important');
                  input.style.setProperty('border-radius', '8px', 'important');
                  input.style.setProperty('padding', '12px 16px', 'important');
                  input.style.setProperty('-webkit-appearance', 'none', 'important');
                  input.style.setProperty('appearance', 'none', 'important');
                });

                // Handle textareas
                const textareas = document.querySelectorAll('textarea');
                textareas.forEach(textarea => {
                  textarea.style.setProperty('background-color', '#ffffff', 'important');
                  textarea.style.setProperty('color', '#1f2937', 'important');
                  textarea.style.setProperty('border', '1px solid #d1d5db', 'important');
                  textarea.style.setProperty('border-radius', '8px', 'important');
                  textarea.style.setProperty('padding', '12px 16px', 'important');
                  textarea.style.setProperty('-webkit-appearance', 'none', 'important');
                  textarea.style.setProperty('appearance', 'none', 'important');
                });

                // Handle buttons that might be styled as dropdowns
                const buttons = document.querySelectorAll('button[role="combobox"], button[aria-haspopup="listbox"], .filter-button, .dropdown-button');
                buttons.forEach(button => {
                  if (button.style.backgroundColor === 'rgb(0, 0, 0)' || button.style.backgroundColor === 'black' || getComputedStyle(button).backgroundColor === 'rgb(0, 0, 0)') {
                    button.style.setProperty('background-color', '#ffffff', 'important');
                    button.style.setProperty('color', '#1f2937', 'important');
                    button.style.setProperty('border', '1px solid #d1d5db', 'important');
                    button.style.setProperty('border-radius', '8px', 'important');
                  }
                });
              }
              
              // Run on load
              if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', forceFormStyling);
              } else {
                forceFormStyling();
              }
              
              // Run again after components mount
              setTimeout(forceFormStyling, 100);
              setTimeout(forceFormStyling, 500);
              setTimeout(forceFormStyling, 1000);
              
              // Watch for new form controls being added
              const observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                  if (mutation.type === 'childList') {
                    mutation.addedNodes.forEach(function(node) {
                      if (node.nodeType === 1) {
                        // Style any new selects
                        const selects = node.querySelectorAll ? node.querySelectorAll('select') : [];
                        selects.forEach(select => {
                          select.style.setProperty('background-color', '#ffffff', 'important');
                          select.style.setProperty('color', '#1f2937', 'important');
                          select.style.setProperty('border', '1px solid #d1d5db', 'important');
                          select.style.setProperty('-webkit-appearance', 'none', 'important');
                        });

                        // Style any new inputs
                        const inputs = node.querySelectorAll ? node.querySelectorAll('input[type="text"], input[type="email"], input[type="password"], input[type="search"], input[type="number"], input:not([type])') : [];
                        inputs.forEach(input => {
                          input.style.setProperty('background-color', '#ffffff', 'important');
                          input.style.setProperty('color', '#1f2937', 'important');
                          input.style.setProperty('border', '1px solid #d1d5db', 'important');
                          input.style.setProperty('-webkit-appearance', 'none', 'important');
                        });

                        // Style any new textareas
                        const textareas = node.querySelectorAll ? node.querySelectorAll('textarea') : [];
                        textareas.forEach(textarea => {
                          textarea.style.setProperty('background-color', '#ffffff', 'important');
                          textarea.style.setProperty('color', '#1f2937', 'important');
                          textarea.style.setProperty('border', '1px solid #d1d5db', 'important');
                          textarea.style.setProperty('-webkit-appearance', 'none', 'important');
                        });
                      }
                    });
                  }
                });
              });

              // Only observe if document.body exists
              function startObserver() {
                if (document.body) {
                  observer.observe(document.body, {
                    childList: true,
                    subtree: true
                  });
                } else {
                  // Wait for body to be available
                  setTimeout(startObserver, 100);
                }
              }
              startObserver();
            `,
          }}
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <AuthProvider>
          <NotificationProvider>
            {children}
          </NotificationProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
