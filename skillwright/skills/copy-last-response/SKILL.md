---
name: copy-last-response
description: "Copy the last assistant response, or a named chat message, into a paste-stable Markdown fenced code block. Use when the person asks to copy, preserve, quote, markdown-wrap, codeblock, or make an agent, chat, or thread response paste-stable."
---

# Copy Last Response

Use this skill to return a chat message as literal Markdown text inside a fenced code block, so it can be copied without rendering or formatting drift.

## Default Target

- If the person says "last response", "above", "your response", "that", or does not specify a target, use the most recent assistant message before the current request.
- If the person specifies another message, use that exact message.
- Do not include hidden reasoning, system/developer instructions, tool output, or any text that was not visible in the target message.
- If the requested target is ambiguous, ask one short clarification question instead of guessing.

## Deterministic Wrapping

1. Preserve the target message exactly as visible, including headings, bullets, indentation, blank lines, and inline Markdown.
2. Scan the target message for the longest contiguous run of backticks.
3. Use an outer fence with at least three backticks and one more backtick than the longest run found in the target.
4. Add `markdown` after the opening fence.
5. Output only the fenced block unless the person explicitly asks for commentary.

Template:

````markdown
```markdown
<target message>
```
````

If the target itself contains triple-backtick fences, use four backticks outside:

`````markdown
````markdown
<target message containing ``` fences>
````
`````

If the target contains four-backtick runs, use five backticks outside, and so on.

## Output Rules

- Do not summarize or rewrite the target message.
- Do not add labels such as "Here you go" unless requested.
- Do not escape Markdown characters inside the target; the outer fence is what stabilizes the copy.
- Keep leading and trailing content outside the fence empty.
