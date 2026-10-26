---
type: index
workspace: {{workspace}}
timestamp: {{timestamp}}
---
# Index: {{workspace}}

The map of {{scope}}. A script makes it from the folders on disk. Start here to find a {{find}}.

```
PAGES AT THE TOP  {{pages_at_top}}
FOLDERS           {{folder_count}}
FILES             {{file_count}}
MADE              {{made}}
```

## Pages

| Page | What it says |
|---|---|
{{page_rows}}

## Folders

| Folder | What it holds | Files | Its page |
|---|---|---:|---|
{{folder_rows}}

## Tree

The tree shows each folder and its next level.

```
{{tree}}
```
{{#extra}}

## Extra at the top

These files are outside the six main pages. Their names come from the files on disk.
{{extra_blocks}}
{{/extra}}
