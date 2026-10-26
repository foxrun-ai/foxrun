-- T79: portable data dictionary. Install in a workspace database when approved.
-- This blueprint stores definitions, not WORK records or contract files.
-- Deferred references let INSERT OR REPLACE retain existing child fields.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS object_types (
    name TEXT PRIMARY KEY NOT NULL,
    supertype TEXT,
    subtype TEXT,
    lens TEXT CHECK (lens IN ('knowledge','playbooks','records','history')),
    container TEXT NOT NULL,
    module TEXT NOT NULL,
    database_type TEXT CHECK (database_type IN ('table','mirror','trend','view')),
    storage_name TEXT NOT NULL,
    description TEXT NOT NULL,
    why TEXT,
    example TEXT,
    definition TEXT,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fields (
    object_type TEXT NOT NULL REFERENCES object_types(name)
        DEFERRABLE INITIALLY DEFERRED,
    field TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    required INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0, 1)),
    field_type TEXT NOT NULL CHECK (
        field_type IN ('key','text','number','date','time','yes/no','pick','link','list','file')
    ),
    pick_values TEXT CHECK (
        CASE WHEN pick_values IS NULL THEN 1
             WHEN json_valid(pick_values) THEN json_type(pick_values) = 'array'
             ELSE 0 END
    ),
    pick_source TEXT,
    description TEXT NOT NULL,
    storage_type TEXT,
    sql_definition TEXT,
    source TEXT NOT NULL,
    PRIMARY KEY (object_type, field),
    UNIQUE (object_type, ordinal),
    CHECK (field_type <> 'pick' OR (pick_values IS NOT NULL AND pick_source IS NOT NULL))
);
CREATE VIEW IF NOT EXISTS v_dictionary AS
SELECT o.name AS object_type, o.supertype, o.subtype, o.lens,
       o.container, o.module, o.database_type, o.storage_name,
       o.description AS object_description, o.why, o.example, o.definition,
       o.source AS object_source, f.ordinal, f.field, f.required, f.field_type,
       f.pick_values, f.pick_source, f.description,
       f.storage_type, f.sql_definition, f.source AS field_source
FROM object_types AS o
LEFT JOIN fields AS f ON f.object_type = o.name;
