What are some fixes that we need to be making now.


Now we need to wire our events properly. 

First whatever changes we make we need to show the diff viewer: frontend/src/components/assistant-ui/diff-viewer.tsx whatever code changes we are about to going to make

Anything that requires users confirmation we need to show following UI
frontend/src/components/ai-elements/confirmation.tsx

We also have message component in similar directory.