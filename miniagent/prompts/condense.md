The conversation above is about to be compacted. Write a summary that replaces the older part of it, so future steps keep the useful state without replaying every old message and tool result.

Do not call any tools. Reply with the summary only, using exactly these sections:

## Primary request
The user's goal, constraints, and any later changes to it.

## Files and code touched
Paths read or changed, with what matters about each.

## Errors and fixes
Failed tool calls, error messages, approaches that did not work, and how each was resolved or why it is still open.

## Decisions
Choices already made, and why.

## Pending work
What is still to do, including verification not yet run.

## Current state
Where the work stands right now, including verification already run and its outcome.

## Next step
The single next action.

If an earlier `[conversation summary]` is present, merge its content into these sections rather than copying it as a block. Do not invent facts; if something is uncertain, say so briefly.
