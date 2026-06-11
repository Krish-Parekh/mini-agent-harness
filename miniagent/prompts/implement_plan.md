# Approved plan
{plan}

The user approved this plan. Implement it in order unless the code proves a step is wrong.

For each step:
- Call `update_plan` to mark it `in_progress` before changing files.
- Make the smallest coherent change for that step.
- Run the narrowest meaningful verification for that step.
- Mark it `done` only after the change is implemented and verification passed, or after you have explicitly explained why verification cannot be completed.

Use the injected git status as current workspace state. Do not revert unrelated user edits. If the approved plan is wrong, explain the deviation, adjust the remaining work, and continue carefully. Call `finish` only when all steps are done or when an unresolved blocker has been reported truthfully.
