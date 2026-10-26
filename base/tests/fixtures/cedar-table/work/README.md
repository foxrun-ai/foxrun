# Cedar Shop test schema

## Collections
| Collection | Object type | Supertype | Lens | Database type | Who writes it |
|---|---|---|---|---|---|
| `functions` | table | database | records | table | Person and authorized local writers |
| `goals` | table | database | records | table | Person and authorized local writers |
| `measures` | table | database | records | table | Person and authorized local writers |
| `measure_history` | trend | database | history | trend | Authorized measure writer |
| `programs` | table | database | records | table | Program-control seed |
| `themes` | table | database | records | table | Program-control seed |
| `projects` | table | database | records | table | Person and authorized local writers |
| `tasks` | table | database | records | table | Authorized task writers; `work` for these agent actions |
| `runs` | table | database | history | table | `work run-start` and `work run-end` |
| `task_links` | table | database | records | table | Authorized link writers; `work done` adds receipts |
| `activity` | table | database | history | table | Authorized change writers; `work` records selected actions |
| `comments` | table | database | history | table | Authorized writers; `work comment`, `block`, and `done` |
| `attachments` | table | database | records | table | Authorized attachment writers |
| `decisions` | table | database | records | table | Authorized writers recording decisions and their status |
| `approvals` | table | database | history | table | Authorized writer recording Person's response |
| `incidents` | table | database | history | table | Incident loader and `work incident-*` |
| `bugs` | table | database | records | table | Incident loader and `work bug-open` |
| `record_links` | table | database | records | table | Incident loader and `work link` |
| `open_decisions` | view | database | records | view | No row writer; blueprint defines selection |
| `open_tasks` | view | database | records | view | No row writer; blueprint defines selection |
| `needs_me` | view | database | records | view | No row writer; blueprint defines selection |
| `close_now` | view | database | records | view | No row writer; blueprint defines selection |
| `needs_business_input` | view | database | records | view | No row writer; blueprint defines selection |
| `this_week` | view | database | records | view | No row writer; blueprint defines selection |
| `next_step` | view | database | records | view | No row writer; blueprint defines selection |
| `eisenhower` | view | database | records | view | No row writer; blueprint defines selection |
| `program_plan` | view | database | records | view | No row writer; blueprint defines selection |
| `stream_brief` | view | database | records | view | No row writer; blueprint defines selection |
