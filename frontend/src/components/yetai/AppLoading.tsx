'use client';

type AppLoadingProps = {
  label?: string;
};

export default function AppLoading({ label }: AppLoadingProps) {
  return (
    <div className="min-h-[40vh] flex flex-col items-center justify-center gap-3">
      <div
        className="animate-spin rounded-full h-12 w-12 border-2 border-transparent"
        style={{ borderBottomColor: 'var(--accent)' }}
      />
      {label ? <p className="text-sm muted">{label}</p> : null}
    </div>
  );
}
