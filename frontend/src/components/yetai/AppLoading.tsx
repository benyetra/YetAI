'use client';

export default function AppLoading() {
  return (
    <div className="min-h-[40vh] flex items-center justify-center">
      <div
        className="animate-spin rounded-full h-12 w-12 border-2 border-transparent"
        style={{ borderBottomColor: 'var(--accent)' }}
      />
    </div>
  );
}
