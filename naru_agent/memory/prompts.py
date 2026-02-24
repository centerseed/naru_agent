FACT_EXTRACTION_PROMPT = """\
You are a memory extraction assistant. Extract key facts from the conversation below.

Rules:
- Extract only factual, specific information about the user
- Each fact should be a single, self-contained statement
- Ignore greetings, filler words, and generic statements
- Focus on preferences, history, constraints, and personal details

Conversation:
{conversation}

Return a JSON object with a "facts" array:
{{"facts": ["fact 1", "fact 2", ...]}}

If no meaningful facts can be extracted, return: {{"facts": []}}
"""

MEMORY_RECONCILIATION_PROMPT = """\
You are a memory manager. Compare new facts against existing memories and decide what to do.

Existing memories:
{existing_memories}

New facts:
{new_facts}

For each new fact, decide one action:
- ADD: This is genuinely new information not covered by existing memories
- UPDATE: This updates/corrects an existing memory (specify which one by id)
- DELETE: This contradicts an existing memory and the old one should be removed (specify which one by id)
- NONE: This fact is already captured in existing memories, skip it

Return a JSON object:
{{
  "actions": [
    {{"fact": "...", "action": "ADD"}},
    {{"fact": "...", "action": "UPDATE", "target_id": "0", "updated_text": "..."}},
    {{"fact": "...", "action": "DELETE", "target_id": "1"}},
    {{"fact": "...", "action": "NONE"}}
  ]
}}
"""
