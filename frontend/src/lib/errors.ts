import { ApiError } from "@/lib/api";
import type { ProviderFailure } from "@/lib/events";

const FAILURE_MESSAGES: Record<ProviderFailure["kind"], string> = {
  usage_limit: "The model provider's rate limit was reached.",
  permission_error: "The model provider rejected the API key. Check the provider key in your settings.",
  transport_error: "Couldn't reach the model provider.",
  validation_error: "The model provider rejected the request.",
  provider_error: "The model provider had an error.",
};

export function failureMessage(failure: ProviderFailure): string {
  const message = FAILURE_MESSAGES[failure.kind];
  if (failure.reset_at) {
    const at = new Date(failure.reset_at * 1000).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
    return `${message} Try again after ${at}.`;
  }
  return failure.retryable ? `${message} Send a message to try again.` : message;
}

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
