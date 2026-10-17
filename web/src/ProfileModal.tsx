import { useEffect, useRef, useState } from "react";

export const PROFILE_PLACEHOLDER =
  "I'm Sam, 31. 40 shares of AAPL at $150, $8k in VOO, $12k cash. Goal: house deposit in 5 years, medium risk.";

// First thing on the page: the user's own details in one box, or the demo.
export default function ProfileModal({
  initialText,
  busy,
  error,
  onSubmit,
  onDemo,
  onCancel,
}: {
  initialText: string;
  busy: boolean;
  error: string;
  onSubmit: (text: string) => void;
  onDemo: () => void;
  onCancel?: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [text, setText] = useState(initialText);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="member-modal profile-modal"
      aria-label="Your details"
      // Without a context yet the page has nothing to show, so Escape only closes it when there is one to go back to.
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel?.();
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (text.trim() && !busy) onSubmit(text.trim());
        }}
      >
        <p className="eyebrow">Before the council convenes</p>
        <h2>Tell the council about you</h2>
        <p className="muted">
          Your name, positions (shares and cost, or dollar amounts), cash,
          goals, horizon and risk. Only what you write is used.
        </p>
        <textarea
          id="profile-details"
          aria-label="Your details"
          className="profile-text"
          value={text}
          rows={6}
          maxLength={4000}
          placeholder={PROFILE_PLACEHOLDER}
          disabled={busy}
          autoFocus
          onChange={(event) => setText(event.target.value)}
        />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="profile-actions">
          <button
            type="submit"
            className="profile-submit"
            disabled={busy || !text.trim()}
          >
            {busy ? "Reading your details…" : "Submit"}
          </button>
          <button
            type="button"
            className="profile-demo"
            disabled={busy}
            onClick={onDemo}
          >
            Use the demo
          </button>
          {onCancel && (
            <button
              type="button"
              className="profile-cancel"
              disabled={busy}
              onClick={onCancel}
            >
              Cancel
            </button>
          )}
        </div>
      </form>
    </dialog>
  );
}
