'use client';

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

type Props = {
  text: string;
  /** Accessible name for the trigger, e.g. "About All-play". */
  label?: string;
};

/**
 * Compact “?” control that explains vault jargon on click / keyboard.
 * Closes on Escape, outside click, or second press.
 */
export function VaultHelp({ text, label = 'More info' }: Props) {
  const tipId = useId();
  const rootRef = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  return (
    <span className={`vault-help${open ? ' is-open' : ''}`} ref={rootRef}>
      <button
        type="button"
        className="vault-help-trigger"
        aria-expanded={open}
        aria-controls={tipId}
        aria-label={label}
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">?</span>
      </button>
      {open ? (
        <span role="tooltip" id={tipId} className="vault-help-tip">
          {text}
        </span>
      ) : null}
    </span>
  );
}

type LabelProps = {
  children: ReactNode;
  help?: string;
  helpLabel?: string;
};

/** Inline label + optional help trigger for table headers and record names. */
export function VaultLabelWithHelp({ children, help, helpLabel }: LabelProps) {
  if (!help) return <>{children}</>;
  return (
    <span className="vault-label-with-help">
      <span>{children}</span>
      <VaultHelp text={help} label={helpLabel ?? `About ${String(children)}`} />
    </span>
  );
}
