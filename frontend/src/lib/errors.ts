import { ApiError } from "@/lib/api";

const SANDBOX_MESSAGES: Record<string, string> = {
  sandbox_expired: "The sandbox for this conversation expired. The diff is no longer available.",
  sandbox_unavailable: "The sandbox is unreachable right now. Please try again.",
};

/** A user-facing message for a failed request: the API's detail when it has
 * one, generic copy otherwise (5xx details are server internals, not UX). */
export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (SANDBOX_MESSAGES[error.detail]) return SANDBOX_MESSAGES[error.detail];
    if (error.status < 500 && error.detail) return error.detail;
    return "The server hit an error. Please try again.";
  }
  if (error instanceof TypeError) {
    return "Couldn't reach the server. Check your connection and try again.";
  }
  return "Something went wrong. Please try again.";
}
