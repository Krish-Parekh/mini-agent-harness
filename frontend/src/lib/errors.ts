import { ApiError } from "@/lib/api";

/** A user-facing message for a failed request: the API's detail when it has
 * one, generic copy otherwise (5xx details are server internals, not UX). */
export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status < 500 && error.detail) return error.detail;
    return "The server hit an error. Please try again.";
  }
  if (error instanceof TypeError) {
    return "Couldn't reach the server. Check your connection and try again.";
  }
  return "Something went wrong. Please try again.";
}
