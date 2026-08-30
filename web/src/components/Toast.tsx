type ToastProps = {
  message: string | null;
};

export function Toast({ message }: ToastProps) {
  return (
    <div className={`toast ${message ? "show" : ""}`} role="status">
      {message ?? ""}
    </div>
  );
}
