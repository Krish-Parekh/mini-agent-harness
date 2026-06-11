"use client";

// Replaces the root layout when it (or a provider) throws, so it must render
// its own <html>/<body> and stay dependency-light — Providers/Toaster and
// global styles are unavailable here. Mirrors layout.tsx's dark class.
export default function GlobalError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <html className="dark">
      <body
        style={{
          display: "flex",
          minHeight: "100vh",
          alignItems: "center",
          justifyContent: "center",
          background: "#0a0a0a",
          color: "#fafafa",
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
        }}
      >
        <title>Something went wrong</title>
        <div style={{ textAlign: "center", maxWidth: 420, padding: 24 }}>
          <h1 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
            Something went wrong
          </h1>
          <p style={{ fontSize: 14, opacity: 0.7, marginBottom: 16 }}>
            {error.digest ? `Error digest: ${error.digest}` : "An unexpected error occurred."}
          </p>
          <button
            onClick={() => unstable_retry()}
            style={{
              padding: "8px 16px",
              borderRadius: 8,
              border: "1px solid #333",
              background: "#fafafa",
              color: "#0a0a0a",
              fontSize: 14,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
