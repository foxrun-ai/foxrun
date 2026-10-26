# Cedar Shop test schema

## Collections
| Collection | Object type | Supertype | Lens | Database type or file kind | Who writes it |
| --- | --- | --- | --- | --- | --- |
| `creator_cycles` | table; subject creator-cycle | database | records | table | Accountable agent accepts creator operator proposals |
| `deliverables` | table; subject deliverable | database | records | table | Accountable agent accepts promised terms and evidence |
| `content_permissions` | table; subject content-permission | database | records | table | Accountable agent records checked permission evidence |
| `file_reqs` | table; subject file-req | database | records | table | Approved file-request adapter records action receipts |
| `payments_owed_daily` | trend; subject payments-owed-daily | database | history | trend | Daily reconciler appends actual observations |
| `media_files` | mirror; subject media-file | database | records | mirror | UGC media-index feeder imports source metadata |
| `ugc.md` | function page | document | knowledge | Generated Markdown | Function-page renderer |
