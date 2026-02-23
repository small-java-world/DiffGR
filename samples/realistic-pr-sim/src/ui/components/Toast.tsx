import React from "react";

export type ToastVariant = "success" | "error" | "info";

export function Toast(props: { variant: ToastVariant; message: string; onClose: () => void }) {
  const { variant, message, onClose } = props;
  React.useEffect(() => {
    const id = window.setTimeout(() => onClose(), 3000);
    return () => window.clearTimeout(id);
  }, [onClose]);

  return (
    <div role="status" data-variant={variant}>
      <span>{message}</span>
      <button type="button" onClick={onClose}>
        Close
      </button>
    </div>
  );
}

