# Cedar Shop test schema

## Collections
| Collection | Object type | Supertype | Lens | Database type or file kind | Who writes it |
|---|---|---|---|---|---|
| Amazon page | function page | document | knowledge | Markdown: `amazon.md` | Page renderer reads rows |
| Accounts | account | database | records | table: `accounts` | Authorized local operator |
| Listings | listing | database | records | mirror: `listings` | Amazon listing feeder |
| Advertising | ads | database | records | mirror: `ads_campaigns` | Amazon advertising feeder |
| Account health | account_health | database | history | trend: `account_health_history` | Health schedule appends observations |
| Compliance cases | compliance-case | database | records | table: `compliance_cases` | Authorized local operator |
| Suppressed listings | listing | database | records | view: `v_suppressed_listings` | SQLite reads the listing mirror |
| Open compliance cases | compliance-case | database | records | view: `v_open_compliance_cases` | SQLite reads local case rows |
