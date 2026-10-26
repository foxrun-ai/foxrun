# Cedar Shop test schema

## Collections
| Collection | Object type | Supertype | Lens | Database type | Who writes it |
|---|---|---|---|---|---|
| `persons` | person | database | records | table | Authorized local writer |
| `organizations` | organization | database | records | table | Authorized local writer |
| `organization_memberships` | organization-membership | database | records | table | Authorized local writer |
| `handles` | handle | database | records | table | Authorized local writer |
| `threads` | thread | database | records | table | Authorized local writer |
| `participants` | participant | database | records | table | Authorized local writer |
| `pipelines` | pipeline | database | records | table | Authorized local writer |
| `pipeline_stages` | pipeline-stage | database | records | table | Authorized local writer |
| `opportunities` | opportunity | database | records | table | Authorized local writer |
| `interactions` | interaction | database | history | table | Authorized local writer |
| `messages` | message | database | history | mirror | small-talk feeder only |
| `meetings` | meeting | database | history | table | Authorized local writer |
| `agreements` | agreement | database | records | table | Authorized local writer |
