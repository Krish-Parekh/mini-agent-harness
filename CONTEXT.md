# MiniAgent

A coding agent users run against their GitHub repositories. Users authenticate, pick or import a codebase, start multi-turn agent sessions, and review the edits those sessions produced.

## Language

**User**:
A person authenticated by Supabase Auth via the GitHub provider, identified by `auth.users.id`, who owns their Conversations and holds at most one GitHub connection. GitHub OAuth is the only way in — signing in for the first time is signing up.
_Avoid_: Account, member

**Repository**:
A GitHub codebase the user can run agent sessions against — either one they already own or one they imported (forked) into their account.
_Avoid_: Project, codebase (use Repository unless distinguishing imported vs owned)

**Conversation**:
A multi-turn agent session scoped to exactly one Repository. It has a title, status, event history, and the file edits produced during the session.
_Avoid_: Chat, session, thread

**Event**:
One append-only entry in a Conversation's timeline — a user message, agent action, status change, or error.
_Avoid_: Message (too narrow — actions and errors are events too)

**Session changes**:
The set of file modifications the agent made during a Conversation, viewable as a per-file diff against the branch baseline.
_Avoid_: Diff (that's the presentation), patch

**Conversation review**:
Opening a past Conversation read-only — replaying its Events and Session changes without resuming the agent or mutating the workspace.
_Avoid_: Resume (resuming reactivates the agent; review does not)

**Change snapshot**:
A persisted copy of Session changes written to storage — captured continuously during an active Conversation and finalized when the Conversation is closed.
_Avoid_: Diff record, patch log
