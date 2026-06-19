- [x] Adding planning options
- [x] Add option to raise PR once in final stage
- [ ] Harden the conversation condenser (it is already wired in — see `agent.py:_maybe_condense`): add keep-first + recency, a model-aware token target, and context-window-overflow recovery.
- [x] Proper database for chats/messages — done (Postgres event store: `ConversationRow`/`EventRow` with JSONB, not JSONL).
- [ ] Token persistance is required for github, later we need to allow mini agent to make commits.
- [ ] Implement Fanout architecture for sub-agents
- [ ] Failure mechanism is still struggling needs fixing for those as well.



I would like you to do a proper analysis in terms of how the agents are designed inside the 

This is the file from which you have to take the reference 
/Users/krishparekh/Projects/mini-agent/codebase/OpenHands
/Users/krishparekh/Projects/mini-agent/codebase/software-agent-sdk


This is the agent which I have created 
/Users/krishparekh/Projects/mini-agent/backend
/Users/krishparekh/Projects/mini-agent/miniagent


I would suggest you make use of multiple agents to understand this codebase and my code many loopholes compared to theirs so can you please draw parallels in terms of what can be improved. 

Make use of /Users/krishparekh/Projects/mini-agent/docs to keep a running docs of all the observations that 
you are making in one place. Make sure that you don't hallicunate and everything gets distilled inside one file 

Code Snippets, Methodologies, Flow. 

This would be a long one so run it accordingly and then the final goal is to tell me what is left and what can be improved.