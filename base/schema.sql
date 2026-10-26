PRAGMA foreign_keys=ON;

CREATE TABLE "amazon_account_markets" (
  "account" INTEGER NOT NULL,
  "currency" TEXT,
  "epr_status" TEXT,
  "evidence" TEXT,
  "id" INTEGER PRIMARY KEY,
  "legal_entity" TEXT,
  "marketplace" TEXT NOT NULL,
  "marketplace_id" TEXT,
  "multiplier_as_of" TEXT CHECK ("multiplier_as_of" IS NULL OR (julianday("multiplier_as_of") IS NOT NULL AND date("multiplier_as_of")="multiplier_as_of")),
  "number" TEXT NOT NULL,
  "price_multiplier" REAL,
  "vat_status" TEXT,
  "verified_at" TEXT CHECK ("verified_at" IS NULL OR julianday("verified_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  UNIQUE ("account","marketplace"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "amazon_account_markets_link_0" ON "amazon_account_markets"("account");

CREATE TABLE "amazon_accounts" (
  "aliases" TEXT CHECK ("aliases" IS NULL OR json_valid("aliases")) CHECK ("aliases" IS NULL OR json_type("aliases")='array'),
  "id" INTEGER PRIMARY KEY
) STRICT;

CREATE TABLE "amazon_compliance_cases" (
  "account" INTEGER NOT NULL,
  "case_type" TEXT CHECK ("case_type" IN ('document','brand-conflict','origin','warning')),
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "doc_status" TEXT CHECK ("doc_status" IN ('not-required','need-to-submit','submitted','approved','rejected','lab-gap','data-fix')),
  "due_on" TEXT CHECK ("due_on" IS NULL OR (julianday("due_on") IS NOT NULL AND date("due_on")="due_on")),
  "error_code" TEXT,
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "listing" INTEGER,
  "number" TEXT NOT NULL,
  "owner" TEXT,
  "report_number" TEXT,
  "requirement" TEXT NOT NULL,
  "source_case_id" TEXT,
  "source_status" TEXT,
  "source_url" TEXT,
  "status" TEXT NOT NULL CHECK ("status" IN ('awaiting-external','closed','in-progress','open','resolved')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("listing") REFERENCES "amazon_listings"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "amazon_compliance_cases_link_0" ON "amazon_compliance_cases"("account");

CREATE INDEX "amazon_compliance_cases_link_1" ON "amazon_compliance_cases"("function");

CREATE INDEX "amazon_compliance_cases_link_2" ON "amazon_compliance_cases"("listing");

CREATE TABLE "amazon_listing_changes" (
  "account" INTEGER NOT NULL,
  "approval" INTEGER,
  "change_type" TEXT CHECK ("change_type" IN ('listing','offer','battery','package','fba-switch')),
  "content" TEXT NOT NULL CHECK ("content" IS NULL OR json_valid("content")),
  "content_hash" TEXT NOT NULL,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "marketplace" TEXT,
  "notes" TEXT,
  "number" TEXT NOT NULL,
  "sku" TEXT NOT NULL,
  "sku_ref" INTEGER,
  "status" TEXT NOT NULL CHECK ("status" IN ('blocked','copy-approved','draft','live','previewed','retired','submitted')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "version" INTEGER NOT NULL,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("approval") REFERENCES "base_approvals"("seq") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("sku_ref") REFERENCES "commerce_skus"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "amazon_listing_changes_link_0" ON "amazon_listing_changes"("account");

CREATE INDEX "amazon_listing_changes_link_1" ON "amazon_listing_changes"("approval");

CREATE INDEX "amazon_listing_changes_link_2" ON "amazon_listing_changes"("sku_ref");

CREATE TABLE "amazon_listing_submissions" (
  "checked_at" TEXT CHECK ("checked_at" IS NULL OR julianday("checked_at") IS NOT NULL),
  "content_hash" TEXT NOT NULL,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "idempotency_key" TEXT,
  "listing_change" INTEGER NOT NULL,
  "number" TEXT NOT NULL,
  "result" TEXT,
  "result_message" TEXT,
  "submission_id" TEXT,
  "submitted_at" TEXT CHECK ("submitted_at" IS NULL OR julianday("submitted_at") IS NOT NULL),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("listing_change") REFERENCES "amazon_listing_changes"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "amazon_listing_submissions_link_0" ON "amazon_listing_submissions"("listing_change");

CREATE TABLE "amazon_listings" (
  "account" INTEGER NOT NULL,
  "asin" TEXT,
  "currency" TEXT,
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "fulfillment" TEXT NOT NULL,
  "has_buy_box" INTEGER CHECK ("has_buy_box" IN (0,1)),
  "id" INTEGER PRIMARY KEY,
  "is_buyable" INTEGER CHECK ("is_buyable" IN (0,1)),
  "is_own_offer" INTEGER CHECK ("is_own_offer" IN (0,1)),
  "is_suppressed" INTEGER CHECK ("is_suppressed" IN (0,1)),
  "marketplace" TEXT NOT NULL,
  "observed_at" TEXT CHECK ("observed_at" IS NULL OR julianday("observed_at") IS NOT NULL),
  "parent_asin" TEXT,
  "quantity" INTEGER,
  "refresh_run" INTEGER,
  "seller_sku" TEXT NOT NULL,
  "sku_ref" INTEGER,
  "source_status" TEXT,
  "source_system" TEXT NOT NULL,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "source_url" TEXT,
  "status_reason" TEXT,
  "title" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("account","marketplace","seller_sku","fulfillment"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("sku_ref") REFERENCES "commerce_skus"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "amazon_listings_link_0" ON "amazon_listings"("account");

CREATE INDEX "amazon_listings_link_1" ON "amazon_listings"("refresh_run");

CREATE INDEX "amazon_listings_link_2" ON "amazon_listings"("sku_ref");

CREATE TABLE "base_approvals" (
  "action" TEXT NOT NULL CHECK ("action" IN ('approved','rejected','edited','discussed')),
  "actor" TEXT NOT NULL,
  "approved_sha256" TEXT,
  "authorization_valid" INTEGER NOT NULL DEFAULT 0 CHECK ("authorization_valid" IN (0,1)),
  "envelope_ref" TEXT,
  "go_word" INTEGER CHECK ("go_word" IN (0,1)),
  "person_words" TEXT,
  "occurred_at" TEXT CHECK ("occurred_at" IS NULL OR julianday("occurred_at") IS NOT NULL),
  "recorded_at" TEXT CHECK ("recorded_at" IS NULL OR julianday("recorded_at") IS NOT NULL),
  "refs" TEXT CHECK ("refs" IS NULL OR json_valid("refs")) CHECK ("refs" IS NULL OR json_type("refs")='array'),
  "seq" INTEGER PRIMARY KEY,
  "session" TEXT,
  "source" TEXT,
  "subject_id" INTEGER,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('proposal','draft','content','agreement','listing-change','file-request','restock','task','project','decision','contract','spec','opportunity','deliverable','scheduled-transaction','cancellation','database','meeting')),
  "summary" TEXT,
  "version" INTEGER,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  CHECK (length(trim(actor)) > 0 AND ((session IS NOT NULL AND length(trim(session)) > 0) OR (source IS NOT NULL AND length(trim(source)) > 0))),
  CHECK (recorded_at IS NOT NULL),
  CHECK (authorization_valid=0 OR (action='approved' AND version IS NOT NULL AND subject_id IS NOT NULL AND approved_sha256 IS NOT NULL AND length(approved_sha256)=64 AND approved_sha256 NOT GLOB '*[^0-9a-f]*' AND envelope_ref IS NOT NULL AND go_word=1))
) STRICT;

CREATE TABLE "base_decisions" (
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "decided_on" TEXT CHECK ("decided_on" IS NULL OR (julianday("decided_on") IS NOT NULL AND date("decided_on")="decided_on")),
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "person_words" TEXT,
  "name" TEXT NOT NULL,
  "number" TEXT NOT NULL,
  "path" TEXT,
  "project" INTEGER,
  "replaces" TEXT CHECK ("replaces" IS NULL OR json_valid("replaces")) CHECK ("replaces" IS NULL OR json_type("replaces")='array'),
  "scope" TEXT,
  "source" TEXT,
  "statement" TEXT,
  "status" TEXT NOT NULL CHECK ("status" IN ('deferred','open','ruled','soft','replaced','withdrawn')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  UNIQUE ("number"),
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("project") REFERENCES "work_projects"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "base_decisions_link_0" ON "base_decisions"("function");

CREATE INDEX "base_decisions_link_1" ON "base_decisions"("project");

CREATE TABLE "base_fields" (
  "description" TEXT NOT NULL,
  "field" TEXT NOT NULL,
  "field_type" TEXT NOT NULL CHECK ("field_type" IN ('date','file','key','link','list','number','pick','text','time','yes/no','map')),
  "id" INTEGER PRIMARY KEY,
  "indexed" INTEGER CHECK ("indexed" IN (0,1)),
  "link_target" TEXT,
  "object_type" INTEGER NOT NULL,
  "pick_source" TEXT,
  "pick_values" TEXT CHECK ("pick_values" IS NULL OR json_valid("pick_values")) CHECK ("pick_values" IS NULL OR json_type("pick_values")='array'),
  "required" INTEGER NOT NULL CHECK ("required" IN (0,1)),
  "sort_order" INTEGER NOT NULL,
  "source" TEXT NOT NULL,
  "storage_type" TEXT,
  "sql_definition" TEXT,
  UNIQUE ("object_type","field"),
  FOREIGN KEY ("object_type") REFERENCES "base_object_types"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "base_fields_link_0" ON "base_fields"("object_type");

CREATE TABLE "base_inbox_items" (
  "body" TEXT NOT NULL,
  "captured_by" TEXT NOT NULL,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "kind" TEXT NOT NULL,
  "link" TEXT,
  "number" TEXT NOT NULL,
  "path" TEXT,
  "routed_to" TEXT,
  "source" TEXT NOT NULL,
  "status" TEXT NOT NULL CHECK ("status" IN ('new','routed','dropped')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  UNIQUE ("number")
) STRICT;

CREATE TABLE "base_installs" (
  "actor" TEXT NOT NULL,
  "blueprint_hash" TEXT NOT NULL,
  "id" INTEGER PRIMARY KEY,
  "installed_at" TEXT CHECK ("installed_at" IS NULL OR julianday("installed_at") IS NOT NULL),
  "module" INTEGER NOT NULL,
  "reason" TEXT,
  "status" TEXT NOT NULL CHECK ("status" IN ('complete','partial')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "version" TEXT NOT NULL,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("module","workspace"),
  FOREIGN KEY ("module") REFERENCES "base_modules"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "base_installs_link_0" ON "base_installs"("module");

CREATE TABLE "base_modules" (
  "about" TEXT,
  "built_by" TEXT,
  "connects_to" TEXT CHECK ("connects_to" IS NULL OR json_valid("connects_to")) CHECK ("connects_to" IS NULL OR json_type("connects_to")='array'),
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "install_command" TEXT,
  "job" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "source_path" TEXT,
  "tier" TEXT NOT NULL CHECK ("tier" IN ('base','workspace-type','add-on')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "version" TEXT NOT NULL,
  UNIQUE ("name")
) STRICT;

CREATE TABLE "base_object_types" (
  "collection" TEXT NOT NULL,
  "database_type" TEXT CHECK ("database_type" IN ('mirror','table','trend','view')),
  "definition" TEXT,
  "description" TEXT NOT NULL,
  "example" TEXT,
  "id" INTEGER PRIMARY KEY,
  "lens" TEXT NOT NULL CHECK ("lens" IN ('knowledge','playbooks','records','history','mixed')),
  "location" TEXT,
  "module" INTEGER NOT NULL,
  "name" TEXT NOT NULL,
  "source" TEXT NOT NULL,
  "supertype" TEXT NOT NULL CHECK ("supertype" IN ('record','event','source','view','contract','document','capability')),
  "why" TEXT,
  UNIQUE ("module","name"),
  FOREIGN KEY ("module") REFERENCES "base_modules"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "base_object_types_link_0" ON "base_object_types"("module");

CREATE TABLE "base_pages" (
  "context" TEXT NOT NULL,
  "id" INTEGER PRIMARY KEY,
  "kind" TEXT NOT NULL CHECK ("kind" IN ('mini-app','page-store')),
  "name" TEXT NOT NULL,
  "number" TEXT NOT NULL,
  "owner" TEXT NOT NULL,
  "purpose" TEXT NOT NULL,
  "replaces" INTEGER,
  "source_path" TEXT,
  "status" TEXT NOT NULL CHECK ("status" IN ('in use','not ready','retired','replaced')),
  "url" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  UNIQUE ("name","workspace"),
  FOREIGN KEY ("replaces") REFERENCES "base_pages"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "base_pages_link_0" ON "base_pages"("replaces");

CREATE TABLE "base_proposals" (
  "applied_at" TEXT CHECK ("applied_at" IS NULL OR julianday("applied_at") IS NOT NULL),
  "approval" INTEGER,
  "base_row" TEXT CHECK ("base_row" IS NULL OR json_valid("base_row")),
  "changes" TEXT NOT NULL CHECK ("changes" IS NULL OR json_valid("changes")),
  "content_hash" TEXT NOT NULL,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "idempotency_key" TEXT,
  "number" TEXT NOT NULL,
  "proposed_by" TEXT NOT NULL,
  "status" TEXT CHECK ("status" IN ('open','approved','rejected','withdrawn')),
  "subject_id" INTEGER NOT NULL,
  "table_name" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "why" TEXT NOT NULL,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("approval") REFERENCES "base_approvals"("seq") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "base_proposals_link_0" ON "base_proposals"("approval");

CREATE TABLE "base_receipts" (
  "action" TEXT NOT NULL CHECK ("action" IN ('handed-off','compacted','forked','closed')),
  "actor" TEXT NOT NULL,
  "handoff_path" TEXT,
  "last_seq" INTEGER,
  "occurred_at" TEXT CHECK ("occurred_at" IS NULL OR julianday("occurred_at") IS NOT NULL),
  "parent_session" TEXT,
  "recorded_at" TEXT CHECK ("recorded_at" IS NULL OR julianday("recorded_at") IS NOT NULL),
  "refs" TEXT CHECK ("refs" IS NULL OR json_valid("refs")) CHECK ("refs" IS NULL OR json_type("refs")='array'),
  "runtime" TEXT,
  "seq" INTEGER PRIMARY KEY,
  "session" TEXT,
  "source" TEXT,
  "subject_id" INTEGER NOT NULL,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('session')),
  "summary" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  CHECK (length(trim(actor)) > 0 AND ((session IS NOT NULL AND length(trim(session)) > 0) OR (source IS NOT NULL AND length(trim(source)) > 0))),
  CHECK (action NOT IN ('handed-off','compacted','closed') OR last_seq IS NOT NULL),
  CHECK (recorded_at IS NOT NULL)
) STRICT;

CREATE TABLE "base_values" (
  "active" INTEGER NOT NULL CHECK ("active" IN (0,1)),
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "description" TEXT,
  "id" INTEGER PRIMARY KEY,
  "label" TEXT,
  "set" TEXT NOT NULL,
  "sort_order" INTEGER,
  "source" TEXT NOT NULL,
  "value" TEXT NOT NULL,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("set","value")
) STRICT;

CREATE TABLE "commerce_accounts" (
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "label" TEXT NOT NULL,
  "owner" TEXT,
  "source_account_id" TEXT NOT NULL,
  "source_system" TEXT NOT NULL CHECK ("source_system" IN ('shopify','shipbob','amazon')),
  "status" TEXT NOT NULL CHECK ("status" IN ('active','closed','paused')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("source_system","source_account_id")
) STRICT;

CREATE TABLE "commerce_customer_reviews" (
  "account" INTEGER NOT NULL,
  "body" TEXT,
  "body_ref" TEXT,
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "product" INTEGER,
  "rating" REAL,
  "refresh_run" INTEGER,
  "reviewed_at" TEXT CHECK ("reviewed_at" IS NULL OR julianday("reviewed_at") IS NOT NULL),
  "source_id" TEXT NOT NULL,
  "source_status" TEXT,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "source_url" TEXT,
  "title" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("account","source_id"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("product") REFERENCES "commerce_products"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "commerce_customer_reviews_link_0" ON "commerce_customer_reviews"("account");

CREATE INDEX "commerce_customer_reviews_link_1" ON "commerce_customer_reviews"("refresh_run");

CREATE INDEX "commerce_customer_reviews_link_2" ON "commerce_customer_reviews"("product");

CREATE TABLE "commerce_inventory_levels" (
  "account" INTEGER NOT NULL,
  "available" INTEGER,
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "inbound" INTEGER,
  "location_id" TEXT NOT NULL,
  "observed_at" TEXT CHECK ("observed_at" IS NULL OR julianday("observed_at") IS NOT NULL),
  "on_hand" INTEGER,
  "refresh_run" INTEGER,
  "reserved" INTEGER,
  "sku" TEXT,
  "sku_ref" INTEGER,
  "source_id" TEXT NOT NULL,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "source_url" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("account","source_id","location_id"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("sku_ref") REFERENCES "commerce_skus"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "commerce_inventory_levels_link_0" ON "commerce_inventory_levels"("account");

CREATE INDEX "commerce_inventory_levels_link_1" ON "commerce_inventory_levels"("refresh_run");

CREATE INDEX "commerce_inventory_levels_link_2" ON "commerce_inventory_levels"("sku_ref");

CREATE TABLE "commerce_line_items" (
  "account" INTEGER NOT NULL,
  "currency" TEXT,
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "line_total_minor" INTEGER,
  "order" INTEGER NOT NULL,
  "quantity" INTEGER,
  "refresh_run" INTEGER,
  "sku" TEXT,
  "sku_ref" INTEGER,
  "source_id" TEXT NOT NULL,
  "source_status" TEXT,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "unit_price_minor" INTEGER,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("account","order","source_id"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("order") REFERENCES "commerce_orders"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("sku_ref") REFERENCES "commerce_skus"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (("line_total_minor" IS NULL AND "unit_price_minor" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

CREATE INDEX "commerce_line_items_link_0" ON "commerce_line_items"("account");

CREATE INDEX "commerce_line_items_link_1" ON "commerce_line_items"("order");

CREATE INDEX "commerce_line_items_link_2" ON "commerce_line_items"("refresh_run");

CREATE INDEX "commerce_line_items_link_3" ON "commerce_line_items"("sku_ref");

CREATE TABLE "commerce_orders" (
  "account" INTEGER NOT NULL,
  "currency" TEXT,
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "ordered_at" TEXT CHECK ("ordered_at" IS NULL OR julianday("ordered_at") IS NOT NULL),
  "originating_order_ref" TEXT,
  "reference_id" TEXT,
  "refresh_run" INTEGER,
  "source_channel_id" TEXT,
  "source_id" TEXT NOT NULL,
  "source_status" TEXT,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "source_url" TEXT,
  "total_minor" INTEGER,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("account","source_id"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (("total_minor" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

CREATE INDEX "commerce_orders_link_0" ON "commerce_orders"("account");

CREATE INDEX "commerce_orders_link_1" ON "commerce_orders"("refresh_run");

CREATE TABLE "commerce_prices" (
  "account" INTEGER NOT NULL,
  "channel" TEXT NOT NULL,
  "currency" TEXT,
  "discount" REAL,
  "effective_from" TEXT CHECK ("effective_from" IS NULL OR (julianday("effective_from") IS NOT NULL AND date("effective_from")="effective_from")),
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "list_price_minor" INTEGER,
  "marketplace" TEXT NOT NULL,
  "refresh_run" INTEGER,
  "sale_price_minor" INTEGER,
  "sku" TEXT NOT NULL,
  "sku_ref" INTEGER,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("account","channel","marketplace","sku"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("sku_ref") REFERENCES "commerce_skus"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (("list_price_minor" IS NULL AND "sale_price_minor" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

CREATE INDEX "commerce_prices_link_0" ON "commerce_prices"("account");

CREATE INDEX "commerce_prices_link_1" ON "commerce_prices"("refresh_run");

CREATE INDEX "commerce_prices_link_2" ON "commerce_prices"("sku_ref");

CREATE TABLE "commerce_products" (
  "account" INTEGER NOT NULL,
  "description_html" TEXT,
  "features" TEXT CHECK ("features" IS NULL OR json_valid("features")) CHECK ("features" IS NULL OR json_type("features")='array'),
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "handle" TEXT,
  "id" INTEGER PRIMARY KEY,
  "image_urls" TEXT CHECK ("image_urls" IS NULL OR json_valid("image_urls")) CHECK ("image_urls" IS NULL OR json_type("image_urls")='array'),
  "metafields" TEXT CHECK ("metafields" IS NULL OR json_valid("metafields")),
  "product_type" TEXT,
  "refresh_run" INTEGER,
  "source_id" TEXT NOT NULL,
  "source_status" TEXT,
  "source_tags" TEXT CHECK ("source_tags" IS NULL OR json_valid("source_tags")) CHECK ("source_tags" IS NULL OR json_type("source_tags")='array'),
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "source_url" TEXT,
  "title" TEXT,
  "vendor" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("account","source_id"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "commerce_products_link_0" ON "commerce_products"("account");

CREATE INDEX "commerce_products_link_1" ON "commerce_products"("refresh_run");

CREATE TABLE "commerce_receivings" (
  "counted_at" TEXT CHECK ("counted_at" IS NULL OR julianday("counted_at") IS NOT NULL),
  "counted_by" TEXT NOT NULL,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "notes" TEXT,
  "number" TEXT NOT NULL,
  "quantity" INTEGER NOT NULL,
  "replaces" INTEGER,
  "restock" INTEGER NOT NULL,
  "status" TEXT NOT NULL CHECK ("status" IN ('confirmed','disputed','draft','replaced')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("replaces") REFERENCES "commerce_receivings"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("restock") REFERENCES "commerce_restocks"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "commerce_receivings_link_0" ON "commerce_receivings"("restock");

CREATE TABLE "commerce_restock_recommendations" (
  "as_of" TEXT NOT NULL CHECK ("as_of" IS NULL OR (julianday("as_of") IS NOT NULL AND date("as_of")="as_of")),
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "recommended_quantity" INTEGER NOT NULL,
  "restock" INTEGER NOT NULL,
  "source" TEXT NOT NULL CHECK ("source" IN ('amazon','helium-10','internal')),
  "window_end" TEXT CHECK ("window_end" IS NULL OR (julianday("window_end") IS NOT NULL AND date("window_end")="window_end")),
  "window_start" TEXT CHECK ("window_start" IS NULL OR (julianday("window_start") IS NOT NULL AND date("window_start")="window_start")),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  UNIQUE ("restock","source","as_of","window_start","window_end"),
  FOREIGN KEY ("restock") REFERENCES "commerce_restocks"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "commerce_restock_recommendations_link_0" ON "commerce_restock_recommendations"("restock");

CREATE TABLE "commerce_restocks" (
  "account" INTEGER,
  "approval" INTEGER,
  "approved_quantity" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "destination_location_id" TEXT NOT NULL,
  "due_on" TEXT CHECK ("due_on" IS NULL OR (julianday("due_on") IS NOT NULL AND date("due_on")="due_on")),
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "inventory_level" INTEGER,
  "notes" TEXT,
  "number" TEXT NOT NULL,
  "origin_location_id" TEXT,
  "owner" TEXT,
  "requested_quantity" INTEGER NOT NULL,
  "shipment" INTEGER,
  "sku" TEXT,
  "sku_ref" INTEGER,
  "status" TEXT NOT NULL CHECK ("status" IN ('approved','canceled','draft','in-transit','ordered','planned','received')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("approval") REFERENCES "base_approvals"("seq") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("inventory_level") REFERENCES "commerce_inventory_levels"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("shipment") REFERENCES "commerce_shipments"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("sku_ref") REFERENCES "commerce_skus"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "commerce_restocks_link_0" ON "commerce_restocks"("account");

CREATE INDEX "commerce_restocks_link_1" ON "commerce_restocks"("approval");

CREATE INDEX "commerce_restocks_link_2" ON "commerce_restocks"("function");

CREATE INDEX "commerce_restocks_link_3" ON "commerce_restocks"("inventory_level");

CREATE INDEX "commerce_restocks_link_4" ON "commerce_restocks"("sku_ref");

CREATE INDEX "commerce_restocks_link_5" ON "commerce_restocks"("shipment");

CREATE TABLE "commerce_sales" (
  "account" INTEGER NOT NULL,
  "channel" TEXT NOT NULL,
  "currency" TEXT,
  "date" TEXT NOT NULL CHECK ("date" IS NULL OR (julianday("date") IS NOT NULL AND date("date")="date")),
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "refresh_run" INTEGER,
  "revenue_minor" INTEGER,
  "sku" TEXT NOT NULL,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "units" INTEGER NOT NULL,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("account","channel","sku","date"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (("revenue_minor" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

CREATE INDEX "commerce_sales_link_0" ON "commerce_sales"("account");

CREATE INDEX "commerce_sales_link_1" ON "commerce_sales"("refresh_run");

CREATE TABLE "commerce_sales_reports" (
  "account" INTEGER NOT NULL,
  "barcode" TEXT,
  "channel" TEXT NOT NULL,
  "currency" TEXT,
  "fees_minor" INTEGER,
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "net_sales_minor" INTEGER,
  "refresh_run" INTEGER,
  "revenue_rank" INTEGER,
  "sku" TEXT NOT NULL,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "title" TEXT,
  "units" INTEGER,
  "variant_title" TEXT,
  "window_end" TEXT NOT NULL CHECK ("window_end" IS NULL OR (julianday("window_end") IS NOT NULL AND date("window_end")="window_end")),
  "window_start" TEXT NOT NULL CHECK ("window_start" IS NULL OR (julianday("window_start") IS NOT NULL AND date("window_start")="window_start")),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("account","channel","sku","window_start","window_end"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (("fees_minor" IS NULL AND "net_sales_minor" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

CREATE INDEX "commerce_sales_reports_link_0" ON "commerce_sales_reports"("account");

CREATE INDEX "commerce_sales_reports_link_1" ON "commerce_sales_reports"("refresh_run");

CREATE TABLE "commerce_shipments" (
  "account" INTEGER NOT NULL,
  "carrier" TEXT,
  "delivered_at" TEXT CHECK ("delivered_at" IS NULL OR julianday("delivered_at") IS NOT NULL),
  "delivery_evidence" TEXT,
  "destination" TEXT,
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "order" INTEGER,
  "origin_location_id" TEXT,
  "refresh_run" INTEGER,
  "shipped_at" TEXT CHECK ("shipped_at" IS NULL OR julianday("shipped_at") IS NOT NULL),
  "source_id" TEXT NOT NULL,
  "source_status" TEXT,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "source_url" TEXT,
  "tracking_number" TEXT,
  "tracking_url" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("account","source_id"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("order") REFERENCES "commerce_orders"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "commerce_shipments_link_0" ON "commerce_shipments"("account");

CREATE INDEX "commerce_shipments_link_1" ON "commerce_shipments"("order");

CREATE INDEX "commerce_shipments_link_2" ON "commerce_shipments"("refresh_run");

CREATE TABLE "commerce_skus" (
  "account" INTEGER NOT NULL,
  "barcode" TEXT,
  "collection" TEXT,
  "cost_minor" INTEGER,
  "currency" TEXT,
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "movement" TEXT CHECK ("movement" IN ('automatic','quartz','unknown')),
  "on_tiktok" INTEGER CHECK ("on_tiktok" IN (0,1)),
  "product" INTEGER,
  "refresh_run" INTEGER,
  "shipbob_inventory_id" TEXT,
  "sku" TEXT NOT NULL,
  "source_id" TEXT NOT NULL,
  "source_status" TEXT,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "source_url" TEXT,
  "title" TEXT,
  "variant_title" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("account","source_id"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("product") REFERENCES "commerce_products"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (("cost_minor" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

CREATE INDEX "commerce_skus_link_0" ON "commerce_skus"("account");

CREATE INDEX "commerce_skus_link_1" ON "commerce_skus"("product");

CREATE INDEX "commerce_skus_link_2" ON "commerce_skus"("refresh_run");

CREATE TABLE "commerce_support_cases" (
  "account" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "next_action" TEXT,
  "next_action_due_on" TEXT CHECK ("next_action_due_on" IS NULL OR (julianday("next_action_due_on") IS NOT NULL AND date("next_action_due_on")="next_action_due_on")),
  "number" TEXT NOT NULL,
  "opened_at" TEXT CHECK ("opened_at" IS NULL OR julianday("opened_at") IS NOT NULL),
  "owner" TEXT,
  "platform" TEXT NOT NULL CHECK ("platform" IN ('amazon','other','shipbob','shopify','tiktok-shop')),
  "source_case_id" TEXT,
  "source_status" TEXT,
  "source_url" TEXT,
  "status" TEXT NOT NULL CHECK ("status" IN ('closed','escalated','open','resolved','waiting')),
  "subject" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("account") REFERENCES "commerce_accounts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "commerce_support_cases_link_0" ON "commerce_support_cases"("account");

CREATE INDEX "commerce_support_cases_link_1" ON "commerce_support_cases"("function");

CREATE TABLE "design_briefs" (
  "approval" INTEGER,
  "body" TEXT NOT NULL,
  "channel" TEXT,
  "content_hash" TEXT NOT NULL,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "format" TEXT CHECK ("format" IN ('static','video','deck','copy','page')),
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "status" TEXT NOT NULL CHECK ("status" IN ('draft','approved','in-production','done','canceled')),
  "task" INTEGER,
  "title" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("approval") REFERENCES "base_approvals"("seq") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("task") REFERENCES "work_tasks"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "design_briefs_link_0" ON "design_briefs"("approval");

CREATE INDEX "design_briefs_link_1" ON "design_briefs"("function");

CREATE INDEX "design_briefs_link_2" ON "design_briefs"("task");

CREATE TABLE "design_content" (
  "approval" INTEGER,
  "brief" INTEGER,
  "brief_hash" TEXT,
  "channel" TEXT NOT NULL,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "family_id" TEXT NOT NULL,
  "file_hash" TEXT NOT NULL,
  "file_path" TEXT NOT NULL,
  "format" TEXT NOT NULL CHECK ("format" IN ('static','video','deck','copy','page')),
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "owner" TEXT NOT NULL,
  "parent_content" INTEGER,
  "platform" TEXT,
  "post_id" TEXT,
  "published_at" TEXT CHECK ("published_at" IS NULL OR julianday("published_at") IS NOT NULL),
  "source_url" TEXT,
  "status" TEXT NOT NULL CHECK ("status" IN ('draft','approved','published','retired')),
  "title" TEXT,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "version" INTEGER NOT NULL,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("approval") REFERENCES "base_approvals"("seq") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("brief") REFERENCES "design_briefs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("parent_content") REFERENCES "design_content"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "design_content_link_0" ON "design_content"("approval");

CREATE INDEX "design_content_link_1" ON "design_content"("brief");

CREATE INDEX "design_content_link_2" ON "design_content"("function");

CREATE INDEX "design_content_link_3" ON "design_content"("parent_content");

CREATE TABLE "people_agreements" (
  "approval" INTEGER,
  "counterparty_contact" INTEGER,
  "counterparty_organization" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "currency" TEXT,
  "ends_on" TEXT CHECK ("ends_on" IS NULL OR (julianday("ends_on") IS NOT NULL AND date("ends_on")="ends_on")),
  "family_id" TEXT NOT NULL,
  "file_hash" TEXT,
  "file_path" TEXT,
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "opportunity" INTEGER,
  "replaces" INTEGER,
  "rights_summary" TEXT,
  "signed_at" TEXT CHECK ("signed_at" IS NULL OR julianday("signed_at") IS NOT NULL),
  "signed_file" TEXT,
  "starts_on" TEXT CHECK ("starts_on" IS NULL OR (julianday("starts_on") IS NOT NULL AND date("starts_on")="starts_on")),
  "status" TEXT NOT NULL CHECK ("status" IN ('draft','approved','sent','signed','expired','canceled')),
  "type" TEXT NOT NULL CHECK ("type" IN ('ambassador','client','creator','vendor')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "value_minor" INTEGER,
  "version" INTEGER NOT NULL,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("approval") REFERENCES "base_approvals"("seq") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("counterparty_contact") REFERENCES "people_contacts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("counterparty_organization") REFERENCES "people_organizations"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("opportunity") REFERENCES "people_opportunities"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("replaces") REFERENCES "people_agreements"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (("value_minor" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

CREATE INDEX "people_agreements_link_0" ON "people_agreements"("approval");

CREATE INDEX "people_agreements_link_1" ON "people_agreements"("counterparty_contact");

CREATE INDEX "people_agreements_link_2" ON "people_agreements"("counterparty_organization");

CREATE INDEX "people_agreements_link_3" ON "people_agreements"("function");

CREATE INDEX "people_agreements_link_4" ON "people_agreements"("opportunity");

CREATE TABLE "people_contacts" (
  "aliases" TEXT CHECK ("aliases" IS NULL OR json_valid("aliases")) CHECK ("aliases" IS NULL OR json_type("aliases")='array'),
  "contexts" TEXT CHECK ("contexts" IS NULL OR json_valid("contexts")) CHECK ("contexts" IS NULL OR json_type("contexts")='array'),
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "greeting" TEXT,
  "id" INTEGER PRIMARY KEY,
  "name" TEXT NOT NULL,
  "name_used" TEXT,
  "note_path" TEXT,
  "number" TEXT NOT NULL,
  "primary_channel" TEXT,
  "register" TEXT DEFAULT 'professional' CHECK ("register" IN ('professional','warm','casual')),
  "register_from" TEXT DEFAULT 'default' CHECK ("register_from" IN ('default','@person@')),
  "speaks_as" TEXT DEFAULT '@person@' CHECK ("speaks_as" IN ('@person@','brand')),
  "tier" INTEGER CHECK ("tier" IN (1,2,3,4)),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "voice_notes" TEXT,
  "location" TEXT,
  "body" TEXT,
  UNIQUE ("number")
) STRICT;

CREATE TABLE "people_conversations" (
  "account" TEXT NOT NULL,
  "channel" TEXT NOT NULL,
  "coverage" TEXT CHECK ("coverage" IN ('complete','partial-rcs')),
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "function" INTEGER,
  "group_chat" INTEGER NOT NULL CHECK ("group_chat" IN (0,1)),
  "id" INTEGER PRIMARY KEY,
  "snoozed_until" TEXT CHECK ("snoozed_until" IS NULL OR julianday("snoozed_until") IS NOT NULL),
  "source_system" TEXT NOT NULL,
  "source_thread_id" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'open' CHECK ("status" IN ('open','snoozed','closed')),
  "title" TEXT,
  "topic_id" TEXT,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace_tags" TEXT NOT NULL DEFAULT '[]' CHECK ("workspace_tags" IS NULL OR json_valid("workspace_tags")) CHECK ("workspace_tags" IS NULL OR json_type("workspace_tags")='array'),
  UNIQUE ("channel","account","source_thread_id"),
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (status IS NOT 'snoozed' OR coalesce(length(trim(snoozed_until)),0)>0)
) STRICT;

CREATE INDEX "people_conversations_link_0" ON "people_conversations"("function");

CREATE TABLE "people_draft_facts" (
  "checked_at" TEXT CHECK ("checked_at" IS NULL OR julianday("checked_at") IS NOT NULL),
  "draft" INTEGER NOT NULL,
  "id" INTEGER PRIMARY KEY,
  "reviewed_by" TEXT,
  "source_id" INTEGER,
  "source_ref" TEXT,
  "source_type" TEXT CHECK ("source_type" IN ('task','project','program','goal','measure','function','theme','run','bug','incident','lesson','decision','proposal','inbox-item','installed-module','contact','organization','organization-membership','handle','conversation','message','participant','draft','interaction','meeting','opportunity','pipeline','pipeline-stage','agreement','content','creative-brief','product','sku','price','inventory-level','order','line-item','shipment','customer-review','sale','sales-report','restock','receiving','support-case','account','listing','listing-change','listing-submission','compliance-case','deliverable','permission','file-request','media-file','scheduled-transaction','recurring-series','cancellation','transaction','transfer-leg','budget-snapshot','page')),
  "text" TEXT NOT NULL,
  FOREIGN KEY ("draft") REFERENCES "people_drafts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK ((source_type IS NULL)=(source_id IS NULL)),
  CHECK (reviewed_by IS NULL OR (length(trim(reviewed_by))>0 AND reviewed_by=trim(reviewed_by)))
) STRICT;

CREATE INDEX "people_draft_facts_link_0" ON "people_draft_facts"("draft");

CREATE TABLE "people_drafts" (
  "approval" INTEGER,
  "author" TEXT NOT NULL CHECK ("author" IN ('agent','@person@')),
  "contact" INTEGER,
  "content_hash" TEXT,
  "conversation" INTEGER NOT NULL,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "family_id" TEXT NOT NULL,
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "model" TEXT,
  "request" TEXT,
  "requested_by" TEXT,
  "send_result" TEXT CHECK ("send_result" IN ('not-delivered','failed','could-not-check')),
  "sent_message" INTEGER,
  "status" TEXT NOT NULL CHECK ("status" IN ('draft','approved','sent','skipped','replaced')),
  "text" TEXT,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "version" INTEGER NOT NULL,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("family_id","version"),
  FOREIGN KEY ("approval") REFERENCES "base_approvals"("seq") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("contact") REFERENCES "people_contacts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("conversation") REFERENCES "people_conversations"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("sent_message") REFERENCES "people_messages"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (status NOT IN ('approved','sent') OR (coalesce(length(trim(text)),0)>0 AND coalesce(length(trim(content_hash)),0)>0)),
  CHECK (send_result IS NULL OR status NOT IN ('draft','sent'))
) STRICT;

CREATE INDEX "people_drafts_link_0" ON "people_drafts"("approval");

CREATE INDEX "people_drafts_link_1" ON "people_drafts"("contact");

CREATE INDEX "people_drafts_link_2" ON "people_drafts"("function");

CREATE INDEX "people_drafts_link_3" ON "people_drafts"("sent_message");

CREATE INDEX "people_drafts_link_4" ON "people_drafts"("conversation");

CREATE TABLE "people_handle_snapshots" (
  "as_of" TEXT NOT NULL CHECK ("as_of" IS NULL OR (julianday("as_of") IS NOT NULL AND date("as_of")="as_of")),
  "avg_views" REAL,
  "fit" TEXT,
  "fit_reason" TEXT,
  "flags" TEXT CHECK ("flags" IS NULL OR json_valid("flags")),
  "followers" INTEGER,
  "handle" INTEGER NOT NULL,
  "id" INTEGER PRIMARY KEY,
  "last_post_at" TEXT CHECK ("last_post_at" IS NULL OR julianday("last_post_at") IS NOT NULL),
  "number" TEXT NOT NULL,
  "persona" TEXT,
  "sample_count" INTEGER,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  UNIQUE ("handle","as_of"),
  FOREIGN KEY ("handle") REFERENCES "people_handles"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "people_handle_snapshots_link_0" ON "people_handle_snapshots"("handle");

CREATE TABLE "people_handles" (
  "address" TEXT NOT NULL,
  "channel" TEXT NOT NULL,
  "contact" INTEGER NOT NULL,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "label" TEXT,
  "number" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "verified_at" TEXT CHECK ("verified_at" IS NULL OR julianday("verified_at") IS NOT NULL),
  UNIQUE ("number"),
  UNIQUE ("channel","address"),
  FOREIGN KEY ("contact") REFERENCES "people_contacts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "people_handles_link_0" ON "people_handles"("contact");

CREATE TABLE "people_interactions" (
  "contact" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "function" INTEGER,
  "handle" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "occurred_at" TEXT CHECK ("occurred_at" IS NULL OR julianday("occurred_at") IS NOT NULL),
  "opportunity" INTEGER,
  "source_message" INTEGER,
  "summary" TEXT NOT NULL,
  "summary_author" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "url" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("contact") REFERENCES "people_contacts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("handle") REFERENCES "people_handles"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("opportunity") REFERENCES "people_opportunities"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("source_message") REFERENCES "people_messages"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "people_interactions_link_0" ON "people_interactions"("contact");

CREATE INDEX "people_interactions_link_1" ON "people_interactions"("function");

CREATE INDEX "people_interactions_link_2" ON "people_interactions"("handle");

CREATE INDEX "people_interactions_link_3" ON "people_interactions"("opportunity");

CREATE INDEX "people_interactions_link_4" ON "people_interactions"("source_message");

CREATE TABLE "people_meetings" (
  "contact" INTEGER,
  "conversation" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "ended_at" TEXT CHECK ("ended_at" IS NULL OR julianday("ended_at") IS NOT NULL),
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "opportunity" INTEGER,
  "organization" INTEGER,
  "source_id" TEXT,
  "source_system" TEXT,
  "source_url" TEXT,
  "started_at" TEXT CHECK ("started_at" IS NULL OR julianday("started_at") IS NOT NULL),
  "summary" TEXT,
  "title" TEXT NOT NULL,
  "transcript_path" TEXT,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("contact") REFERENCES "people_contacts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("conversation") REFERENCES "people_conversations"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("opportunity") REFERENCES "people_opportunities"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("organization") REFERENCES "people_organizations"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "people_meetings_link_0" ON "people_meetings"("contact");

CREATE INDEX "people_meetings_link_1" ON "people_meetings"("conversation");

CREATE INDEX "people_meetings_link_2" ON "people_meetings"("function");

CREATE INDEX "people_meetings_link_3" ON "people_meetings"("opportunity");

CREATE INDEX "people_meetings_link_4" ON "people_meetings"("organization");

CREATE TABLE "people_messages" (
  "account" TEXT NOT NULL,
  "body_ref" TEXT,
  "channel" TEXT NOT NULL,
  "content_hash" TEXT,
  "conversation" INTEGER NOT NULL,
  "direction" TEXT CHECK ("direction" IN ('inbound','outbound','other','unknown')),
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "raw_ref" TEXT,
  "refresh_run" INTEGER,
  "replaces" INTEGER,
  "reply_to_source_id" TEXT,
  "sender_address" TEXT NOT NULL,
  "sender_handle" INTEGER,
  "sender_name" TEXT,
  "sent_at" TEXT CHECK ("sent_at" IS NULL OR julianday("sent_at") IS NOT NULL),
  "source_message_id" TEXT NOT NULL,
  "source_status" TEXT,
  "source_system" TEXT NOT NULL,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "source_url" TEXT,
  "text" TEXT,
  "workspace_tags" TEXT CHECK ("workspace_tags" IS NULL OR json_valid("workspace_tags")) CHECK ("workspace_tags" IS NULL OR json_type("workspace_tags")='array'),
  UNIQUE ("channel","account","source_message_id"),
  FOREIGN KEY ("conversation") REFERENCES "people_conversations"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("replaces") REFERENCES "people_messages"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("sender_handle") REFERENCES "people_handles"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "people_messages_link_0" ON "people_messages"("refresh_run");

CREATE INDEX "people_messages_link_1" ON "people_messages"("sender_handle");

CREATE INDEX "people_messages_link_3" ON "people_messages"("conversation");

CREATE TABLE "people_opportunities" (
  "agreed_amount_minor" INTEGER,
  "closed_at" TEXT CHECK ("closed_at" IS NULL OR julianday("closed_at") IS NOT NULL),
  "contact" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "currency" TEXT,
  "function" INTEGER,
  "heat" INTEGER CHECK ("heat" IN (0,1,2,3,4)),
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "offer_summary" TEXT,
  "organization" INTEGER,
  "outcome" TEXT CHECK ("outcome" IN ('open','won','lost','abandoned')),
  "owner" TEXT,
  "period_end" TEXT CHECK ("period_end" IS NULL OR (julianday("period_end") IS NOT NULL AND date("period_end")="period_end")),
  "period_start" TEXT CHECK ("period_start" IS NULL OR (julianday("period_start") IS NOT NULL AND date("period_start")="period_start")),
  "pipeline" INTEGER NOT NULL,
  "previous_opportunity" INTEGER,
  "primary_handle" INTEGER,
  "round_key" TEXT,
  "round_name" TEXT,
  "round_type" TEXT CHECK ("round_type" IN ('one-off','recurring')),
  "source_checked_at" TEXT CHECK ("source_checked_at" IS NULL OR julianday("source_checked_at") IS NOT NULL),
  "source_id" TEXT,
  "source_system" TEXT,
  "stage" INTEGER,
  "title" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "value_minor" INTEGER,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("contact") REFERENCES "people_contacts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("organization") REFERENCES "people_organizations"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("pipeline") REFERENCES "people_pipelines"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("previous_opportunity") REFERENCES "people_opportunities"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("primary_handle") REFERENCES "people_handles"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("stage") REFERENCES "people_pipeline_stages"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (("agreed_amount_minor" IS NULL AND "value_minor" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

CREATE INDEX "people_opportunities_link_0" ON "people_opportunities"("contact");

CREATE INDEX "people_opportunities_link_1" ON "people_opportunities"("function");

CREATE INDEX "people_opportunities_link_2" ON "people_opportunities"("organization");

CREATE INDEX "people_opportunities_link_3" ON "people_opportunities"("pipeline");

CREATE INDEX "people_opportunities_link_4" ON "people_opportunities"("previous_opportunity");

CREATE INDEX "people_opportunities_link_5" ON "people_opportunities"("primary_handle");

CREATE INDEX "people_opportunities_link_6" ON "people_opportunities"("stage");

CREATE TABLE "people_organization_memberships" (
  "contact" INTEGER NOT NULL,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "ends_on" TEXT CHECK ("ends_on" IS NULL OR (julianday("ends_on") IS NOT NULL AND date("ends_on")="ends_on")),
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "organization" INTEGER NOT NULL,
  "role" TEXT,
  "starts_on" TEXT CHECK ("starts_on" IS NULL OR (julianday("starts_on") IS NOT NULL AND date("starts_on")="starts_on")),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("contact") REFERENCES "people_contacts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("organization") REFERENCES "people_organizations"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "people_organization_memberships_link_0" ON "people_organization_memberships"("contact");

CREATE INDEX "people_organization_memberships_link_1" ON "people_organization_memberships"("organization");

CREATE TABLE "people_organizations" (
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "domain" TEXT,
  "id" INTEGER PRIMARY KEY,
  "name" TEXT NOT NULL,
  "note_path" TEXT,
  "number" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  UNIQUE ("number")
) STRICT;

CREATE TABLE "people_participants" (
  "contact" INTEGER,
  "conversation" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "handle" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "meeting" INTEGER,
  "number" TEXT NOT NULL,
  "raw_identity" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("contact") REFERENCES "people_contacts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("conversation") REFERENCES "people_conversations"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("handle") REFERENCES "people_handles"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("meeting") REFERENCES "people_meetings"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "people_participants_link_0" ON "people_participants"("contact");

CREATE INDEX "people_participants_link_1" ON "people_participants"("conversation");

CREATE INDEX "people_participants_link_2" ON "people_participants"("handle");

CREATE INDEX "people_participants_link_3" ON "people_participants"("meeting");

CREATE TABLE "people_pipeline_stages" (
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "pipeline" INTEGER NOT NULL,
  "sort_order" INTEGER NOT NULL,
  "stage" TEXT NOT NULL CHECK ("stage" IN ('identified','conversation','qualified','offered','won','lost','outreach','selection','shipment','production','payment','renewal','closed','idea','exploring','committed','building','launched','parked')),
  "target_days" INTEGER,
  UNIQUE ("pipeline","stage"),
  FOREIGN KEY ("pipeline") REFERENCES "people_pipelines"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "people_pipeline_stages_link_0" ON "people_pipeline_stages"("pipeline");

CREATE TABLE "people_pipelines" (
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "name" TEXT NOT NULL CHECK ("name" IN ('clients','ventures','creators')),
  "number" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  UNIQUE ("number"),
  UNIQUE ("name"),
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "people_pipelines_link_0" ON "people_pipelines"("function");

CREATE TABLE "treasury_budget_snapshots" (
  "as_of" TEXT CHECK ("as_of" IS NULL OR julianday("as_of") IS NOT NULL),
  "budget_id" TEXT NOT NULL,
  "content_hash" TEXT NOT NULL,
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "payload_path" TEXT NOT NULL,
  "refresh_run" INTEGER,
  "server_knowledge" INTEGER,
  "source" TEXT NOT NULL CHECK ("source" IN ('ynab')),
  "source_identity" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  UNIQUE ("content_hash"),
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "treasury_budget_snapshots_link_0" ON "treasury_budget_snapshots"("refresh_run");

CREATE TABLE "treasury_cancellations" (
  "confirmation_reference" TEXT,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "details" TEXT CHECK ("details" IS NULL OR json_valid("details")),
  "dimensions" TEXT CHECK ("dimensions" IS NULL OR json_valid("dimensions")),
  "effective_on" TEXT CHECK ("effective_on" IS NULL OR (julianday("effective_on") IS NOT NULL AND date("effective_on")="effective_on")),
  "id" INTEGER PRIMARY KEY,
  "nonrenewal_status" TEXT CHECK ("nonrenewal_status" IN ('confirmed','failed','requested','unknown')),
  "number" TEXT NOT NULL,
  "series" INTEGER,
  "service_label" TEXT NOT NULL,
  "status" TEXT CHECK ("status" IN ('undecided','keep','requested','confirmed','failed')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "vendor" TEXT NOT NULL,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("series") REFERENCES "treasury_recurring_series"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "treasury_cancellations_link_0" ON "treasury_cancellations"("series");

CREATE TABLE "treasury_recurring_series" (
  "account_id" TEXT,
  "category_id" TEXT,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "currency" TEXT,
  "expected_amount_minor" INTEGER,
  "first_seen_at" TEXT CHECK ("first_seen_at" IS NULL OR julianday("first_seen_at") IS NOT NULL),
  "frequency" TEXT NOT NULL,
  "id" INTEGER PRIMARY KEY,
  "last_seen_at" TEXT CHECK ("last_seen_at" IS NULL OR julianday("last_seen_at") IS NOT NULL),
  "name" TEXT NOT NULL,
  "number" TEXT NOT NULL,
  "source_identity" TEXT NOT NULL,
  "source_system" TEXT,
  "status" TEXT NOT NULL CHECK ("status" IN ('active','canceled','inactive','needs-review')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  CHECK (("expected_amount_minor" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

CREATE TABLE "treasury_scheduled_transactions" (
  "amount_minor" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "currency" TEXT,
  "cycle_key" TEXT,
  "direction" TEXT NOT NULL CHECK ("direction" IN ('in','out')),
  "due_on" TEXT NOT NULL CHECK ("due_on" IS NULL OR (julianday("due_on") IS NOT NULL AND date("due_on")="due_on")),
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "opportunity" INTEGER,
  "payee" TEXT,
  "series" INTEGER,
  "settled_at" TEXT CHECK ("settled_at" IS NULL OR julianday("settled_at") IS NOT NULL),
  "source_identity" TEXT,
  "source_system" TEXT,
  "status" TEXT CHECK ("status" IN ('expected','due','settled','skipped','written-off','canceled')),
  "transaction" INTEGER,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("series") REFERENCES "treasury_recurring_series"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("transaction") REFERENCES "treasury_transactions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (("amount_minor" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

CREATE INDEX "treasury_scheduled_transactions_link_0" ON "treasury_scheduled_transactions"("opportunity");

CREATE INDEX "treasury_scheduled_transactions_link_1" ON "treasury_scheduled_transactions"("series");

CREATE INDEX "treasury_scheduled_transactions_link_2" ON "treasury_scheduled_transactions"("transaction");

CREATE TABLE "treasury_transactions" (
  "account_id" TEXT NOT NULL,
  "amount_milliunits" INTEGER,
  "approved" INTEGER CHECK ("approved" IN (0,1)),
  "budget_id" TEXT NOT NULL,
  "category_id" TEXT,
  "cleared" TEXT CHECK ("cleared" IN ('cleared','uncleared','reconciled')),
  "currency" TEXT,
  "date" TEXT NOT NULL CHECK ("date" IS NULL OR (julianday("date") IS NOT NULL AND date("date")="date")),
  "deleted" INTEGER CHECK ("deleted" IN (0,1)),
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "memo" TEXT,
  "payee_id" TEXT,
  "payee_name" TEXT,
  "refresh_run" INTEGER,
  "source_id" TEXT NOT NULL,
  "source_system" TEXT NOT NULL,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "transfer_account_id" TEXT,
  "transfer_transaction_id" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("budget_id","source_id"),
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "treasury_transactions_link_0" ON "treasury_transactions"("refresh_run");

CREATE TABLE "treasury_transfer_legs" (
  "account_id" TEXT NOT NULL,
  "amount_milliunits" INTEGER,
  "currency" TEXT,
  "destination_account_id" TEXT NOT NULL,
  "direction" TEXT NOT NULL CHECK ("direction" IN ('in','out')),
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "paired_source_identity" TEXT NOT NULL,
  "refresh_run" INTEGER,
  "source_identity" TEXT NOT NULL,
  "source_system" TEXT NOT NULL,
  "transaction" INTEGER,
  "transfer_on" TEXT NOT NULL CHECK ("transfer_on" IS NULL OR (julianday("transfer_on") IS NOT NULL AND date("transfer_on")="transfer_on")),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("transaction") REFERENCES "treasury_transactions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "treasury_transfer_legs_link_0" ON "treasury_transfer_legs"("refresh_run");

CREATE INDEX "treasury_transfer_legs_link_1" ON "treasury_transfer_legs"("transaction");

CREATE TABLE "ugc_deliverable_content" (
  "content" INTEGER NOT NULL,
  "deliverable" INTEGER NOT NULL,
  "id" INTEGER PRIMARY KEY,
  UNIQUE ("deliverable","content"),
  FOREIGN KEY ("content") REFERENCES "design_content"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("deliverable") REFERENCES "ugc_deliverables"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "ugc_deliverable_content_link_0" ON "ugc_deliverable_content"("deliverable");

CREATE INDEX "ugc_deliverable_content_link_1" ON "ugc_deliverable_content"("content");

CREATE TABLE "ugc_deliverables" (
  "acceptance_criteria" TEXT,
  "agreement" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "due_on" TEXT CHECK ("due_on" IS NULL OR (julianday("due_on") IS NOT NULL AND date("due_on")="due_on")),
  "format" TEXT NOT NULL CHECK ("format" IN ('collab-reel','post','post-carousel','raw-files','reel','short-video-cut','story')),
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "opportunity" INTEGER NOT NULL,
  "platform" TEXT,
  "promise_key" TEXT NOT NULL,
  "published_required" INTEGER CHECK ("published_required" IN (0,1)),
  "quantity" INTEGER,
  "quantity_unknown_reason" TEXT,
  "required_shots" TEXT CHECK ("required_shots" IS NULL OR json_valid("required_shots")) CHECK ("required_shots" IS NULL OR json_type("required_shots")='array'),
  "status" TEXT NOT NULL CHECK ("status" IN ('proposed','agreed','waived')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "waiver_approval" INTEGER,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("agreement") REFERENCES "people_agreements"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("opportunity") REFERENCES "people_opportunities"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("waiver_approval") REFERENCES "base_approvals"("seq") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "ugc_deliverables_link_0" ON "ugc_deliverables"("agreement");

CREATE INDEX "ugc_deliverables_link_1" ON "ugc_deliverables"("function");

CREATE INDEX "ugc_deliverables_link_2" ON "ugc_deliverables"("opportunity");

CREATE INDEX "ugc_deliverables_link_3" ON "ugc_deliverables"("waiver_approval");

CREATE TABLE "ugc_file_requests" (
  "approval" INTEGER,
  "checked_at" TEXT CHECK ("checked_at" IS NULL OR julianday("checked_at") IS NOT NULL),
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "expires_at" TEXT CHECK ("expires_at" IS NULL OR julianday("expires_at") IS NOT NULL),
  "folder_path" TEXT,
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "link_state" TEXT NOT NULL CHECK ("link_state" IN ('available','expired','unavailable','unchecked')),
  "number" TEXT NOT NULL,
  "opportunity" INTEGER NOT NULL,
  "provider" TEXT NOT NULL,
  "receipt_ref" TEXT,
  "received_at" TEXT CHECK ("received_at" IS NULL OR julianday("received_at") IS NOT NULL),
  "sent_interaction" INTEGER,
  "source_id" TEXT,
  "status" TEXT NOT NULL CHECK ("status" IN ('closed','created','prepared','received','sent')),
  "title" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "url" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("approval") REFERENCES "base_approvals"("seq") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("opportunity") REFERENCES "people_opportunities"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("sent_interaction") REFERENCES "people_interactions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "ugc_file_requests_link_0" ON "ugc_file_requests"("approval");

CREATE INDEX "ugc_file_requests_link_1" ON "ugc_file_requests"("function");

CREATE INDEX "ugc_file_requests_link_2" ON "ugc_file_requests"("opportunity");

CREATE INDEX "ugc_file_requests_link_3" ON "ugc_file_requests"("sent_interaction");

CREATE TABLE "ugc_media_files" (
  "availability" TEXT NOT NULL CHECK ("availability" IN ('available','expired','missing','unknown')),
  "bytes" INTEGER,
  "checked_at" TEXT CHECK ("checked_at" IS NULL OR julianday("checked_at") IS NOT NULL),
  "deliverable" INTEGER,
  "expires_at" TEXT CHECK ("expires_at" IS NULL OR julianday("expires_at") IS NOT NULL),
  "fetched_at" TEXT CHECK ("fetched_at" IS NULL OR julianday("fetched_at") IS NOT NULL),
  "file_hash" TEXT,
  "id" INTEGER PRIMARY KEY,
  "identity_status" TEXT CHECK ("identity_status" IN ('ambiguous','unknown','verified')),
  "mime_type" TEXT,
  "parent_folder_id" TEXT,
  "path" TEXT,
  "refresh_run" INTEGER,
  "source_account_id" TEXT NOT NULL,
  "source_id" TEXT NOT NULL,
  "source_instance_id" TEXT NOT NULL,
  "source_system" TEXT NOT NULL,
  "source_updated_at" TEXT CHECK ("source_updated_at" IS NULL OR julianday("source_updated_at") IS NOT NULL),
  "source_url" TEXT,
  "version_id" TEXT NOT NULL,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("source_system","source_account_id","source_instance_id","source_id","version_id"),
  FOREIGN KEY ("deliverable") REFERENCES "ugc_deliverables"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("refresh_run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "ugc_media_files_link_0" ON "ugc_media_files"("deliverable");

CREATE INDEX "ugc_media_files_link_1" ON "ugc_media_files"("refresh_run");

CREATE TABLE "ugc_usage_rights" (
  "agreement" INTEGER,
  "content" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "creator" INTEGER,
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "permission_key" TEXT NOT NULL,
  "platform" TEXT,
  "source_interaction" INTEGER,
  "status" TEXT NOT NULL CHECK ("status" IN ('granted','proposed','revoked','unknown')),
  "territory" TEXT,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "usage" TEXT NOT NULL CHECK ("usage" IN ('creator-handle','editing','organic','paid')),
  "valid_from" TEXT CHECK ("valid_from" IS NULL OR (julianday("valid_from") IS NOT NULL AND date("valid_from")="valid_from")),
  "valid_until" TEXT CHECK ("valid_until" IS NULL OR (julianday("valid_until") IS NOT NULL AND date("valid_until")="valid_until")),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("agreement") REFERENCES "people_agreements"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("content") REFERENCES "design_content"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("creator") REFERENCES "people_contacts"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("source_interaction") REFERENCES "people_interactions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "ugc_usage_rights_link_0" ON "ugc_usage_rights"("agreement");

CREATE INDEX "ugc_usage_rights_link_1" ON "ugc_usage_rights"("content");

CREATE INDEX "ugc_usage_rights_link_2" ON "ugc_usage_rights"("creator");

CREATE INDEX "ugc_usage_rights_link_3" ON "ugc_usage_rights"("function");

CREATE INDEX "ugc_usage_rights_link_4" ON "ugc_usage_rights"("source_interaction");

CREATE TABLE "work_attachments" (
  "action" TEXT NOT NULL CHECK ("action" IN ('attached','published')),
  "actor" TEXT NOT NULL,
  "bytes" INTEGER,
  "hash" TEXT,
  "kind" TEXT,
  "mime_type" TEXT,
  "occurred_at" TEXT CHECK ("occurred_at" IS NULL OR julianday("occurred_at") IS NOT NULL),
  "path" TEXT,
  "payload" TEXT,
  "recorded_at" TEXT CHECK ("recorded_at" IS NULL OR julianday("recorded_at") IS NOT NULL),
  "refs" TEXT CHECK ("refs" IS NULL OR json_valid("refs")) CHECK ("refs" IS NULL OR json_type("refs")='array'),
  "role" TEXT NOT NULL CHECK ("role" IN ('produced','evidence')),
  "seq" INTEGER PRIMARY KEY,
  "session" TEXT,
  "source" TEXT,
  "subject_id" INTEGER NOT NULL,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('task','project','program','goal','measure','function','theme','run','bug','incident','lesson','decision','proposal','inbox-item','installed-module','contact','organization','organization-membership','handle','conversation','message','participant','draft','interaction','meeting','opportunity','pipeline','pipeline-stage','agreement','content','creative-brief','product','sku','price','inventory-level','order','line-item','shipment','customer-review','sale','sales-report','restock','receiving','support-case','account','listing','listing-change','listing-submission','compliance-case','deliverable','permission','file-request','media-file','scheduled-transaction','recurring-series','cancellation','transaction','transfer-leg','budget-snapshot','session','file','page')),
  "summary" TEXT,
  "url" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  CHECK (length(trim(actor)) > 0 AND ((session IS NOT NULL AND length(trim(session)) > 0) OR (source IS NOT NULL AND length(trim(source)) > 0))),
  CHECK (coalesce(length(trim(path)),0)>0 OR coalesce(length(trim(url)),0)>0 OR coalesce(length(payload),0)>0),
  CHECK (recorded_at IS NOT NULL)
) STRICT;

CREATE TABLE "work_bugs" (
  "capability" TEXT,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "description" TEXT,
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "opened_at" TEXT CHECK ("opened_at" IS NULL OR julianday("opened_at") IS NOT NULL),
  "reports" INTEGER NOT NULL,
  "resolved_at" TEXT CHECK ("resolved_at" IS NULL OR julianday("resolved_at") IS NOT NULL),
  "severity" TEXT CHECK ("severity" IN ('critical','error','info','warning')),
  "status" TEXT CHECK ("status" IN ('open','fixed','wont-fix')),
  "title" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "work_bugs_link_0" ON "work_bugs"("function");

CREATE TABLE "work_changes" (
  "action" TEXT NOT NULL CHECK ("action" IN ('created','updated','moved','archived','deleted','captured','imported','claimed','started','finished','failed','verified','accepted','decided','replaced','corrected','merged','released','published','sent','fixed','restored','closed','rolled-back')),
  "actor" TEXT NOT NULL,
  "detail_id" INTEGER,
  "detail_type" TEXT CHECK ("detail_type" IN ('comment','attachment','run','approval','receipt','proposal')),
  "field" TEXT,
  "new_value" TEXT,
  "occurred_at" TEXT CHECK ("occurred_at" IS NULL OR julianday("occurred_at") IS NOT NULL),
  "old_value" TEXT,
  "recorded_at" TEXT CHECK ("recorded_at" IS NULL OR julianday("recorded_at") IS NOT NULL),
  "refs" TEXT CHECK ("refs" IS NULL OR json_valid("refs")) CHECK ("refs" IS NULL OR json_type("refs")='array'),
  "seq" INTEGER PRIMARY KEY,
  "session" TEXT,
  "source" TEXT,
  "subject_id" INTEGER NOT NULL,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('task','project','program','goal','measure','function','theme','run','bug','incident','lesson','decision','proposal','inbox-item','installed-module','contact','organization','organization-membership','handle','conversation','message','participant','draft','interaction','meeting','opportunity','pipeline','pipeline-stage','agreement','content','creative-brief','product','sku','price','inventory-level','order','line-item','shipment','customer-review','sale','sales-report','restock','receiving','support-case','account','listing','listing-change','listing-submission','compliance-case','deliverable','permission','file-request','media-file','scheduled-transaction','recurring-series','cancellation','transaction','transfer-leg','budget-snapshot','session','file','snapshot','account-market','approval','attachment','change','comment','deliverable-content','draft-fact','field','handle-snapshot','link','measure-observation','module','object-type','page','receipt','restock-recommendation','value','capability')),
  "subject_version" TEXT,
  "summary" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace",1)),
  CHECK (length(trim(actor)) > 0 AND ((session IS NOT NULL AND length(trim(session)) > 0) OR (source IS NOT NULL AND length(trim(source)) > 0))),
  CHECK (workspace <> 'foxrun' OR subject_type='function'),
  CHECK (recorded_at IS NOT NULL)
) STRICT;

CREATE TABLE "work_comments" (
  "action" TEXT NOT NULL CHECK ("action" IN ('commented')),
  "actor" TEXT NOT NULL,
  "body" TEXT NOT NULL,
  "field" TEXT,
  "flag" INTEGER CHECK ("flag" IN (0,1)),
  "occurred_at" TEXT CHECK ("occurred_at" IS NULL OR julianday("occurred_at") IS NOT NULL),
  "recorded_at" TEXT CHECK ("recorded_at" IS NULL OR julianday("recorded_at") IS NOT NULL),
  "refs" TEXT CHECK ("refs" IS NULL OR json_valid("refs")) CHECK ("refs" IS NULL OR json_type("refs")='array'),
  "reply_to" INTEGER,
  "seq" INTEGER PRIMARY KEY,
  "session" TEXT,
  "source" TEXT,
  "subject_id" INTEGER NOT NULL,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('task','project','program','goal','measure','function','theme','run','bug','incident','lesson','decision','proposal','inbox-item','installed-module','contact','organization','organization-membership','handle','conversation','message','participant','draft','interaction','meeting','opportunity','pipeline','pipeline-stage','agreement','content','creative-brief','product','sku','price','inventory-level','order','line-item','shipment','customer-review','sale','sales-report','restock','receiving','support-case','account','listing','listing-change','listing-submission','compliance-case','deliverable','permission','file-request','media-file','scheduled-transaction','recurring-series','cancellation','transaction','transfer-leg','budget-snapshot','session','file')),
  "summary" TEXT,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  FOREIGN KEY ("reply_to") REFERENCES "work_comments"("seq") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (length(trim(actor)) > 0 AND ((session IS NOT NULL AND length(trim(session)) > 0) OR (source IS NOT NULL AND length(trim(source)) > 0))),
  CHECK (recorded_at IS NOT NULL)
) STRICT;

CREATE INDEX "work_comments_link_0" ON "work_comments"("reply_to");

CREATE TABLE "work_functions" (
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "job" TEXT,
  "name" TEXT NOT NULL,
  "number" TEXT NOT NULL,
  "owner" TEXT,
  "page" TEXT,
  "parent" INTEGER,
  "sort_order" INTEGER,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace",1)),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("parent") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "work_functions_link_0" ON "work_functions"("parent");

CREATE TABLE "work_goals" (
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "function" INTEGER,
  "horizon" TEXT NOT NULL CHECK ("horizon" IN ('1-year','3-year','north-star','quarter')),
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "owner" TEXT,
  "period" TEXT,
  "replaces" INTEGER,
  "status" TEXT NOT NULL CHECK ("status" IN ('on-track','at-risk','off-track','done','missed','canceled','replaced')),
  "title" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("replaces") REFERENCES "work_goals"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "work_goals_link_0" ON "work_goals"("function");

CREATE TABLE "work_incidents" (
  "body" TEXT,
  "bug" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "ended_at" TEXT CHECK ("ended_at" IS NULL OR julianday("ended_at") IS NOT NULL),
  "function" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "impact" TEXT,
  "number" TEXT NOT NULL,
  "restored_by" TEXT,
  "root_cause" TEXT,
  "source" TEXT,
  "started_at" TEXT CHECK ("started_at" IS NULL OR julianday("started_at") IS NOT NULL),
  "status" TEXT NOT NULL CHECK ("status" IN ('closed','open','restored')),
  "title" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("bug") REFERENCES "work_bugs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "work_incidents_link_0" ON "work_incidents"("bug");

CREATE INDEX "work_incidents_link_1" ON "work_incidents"("function");

CREATE TABLE "work_lessons" (
  "codified_in" TEXT,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "number" TEXT NOT NULL,
  "replay_case" TEXT,
  "skill" TEXT,
  "source" TEXT NOT NULL CHECK ("source" IN ('feedback','lesson','failure')),
  "source_ref" TEXT NOT NULL,
  "status" TEXT NOT NULL CHECK ("status" IN ('open','codified','replaced','canceled')),
  "subject" TEXT NOT NULL,
  "text" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number")
) STRICT;

CREATE TABLE "work_links" (
  "actor" TEXT,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "path" TEXT,
  "relation" TEXT NOT NULL CHECK ("relation" IN ('about','blocks','caused-by','fix','found-in','produced','serves','shown-as','source','spec','specified-by','tagged','updated')),
  "subject_id" INTEGER NOT NULL,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('task','project','program','goal','measure','function','theme','run','bug','incident','lesson','decision','proposal','inbox-item','installed-module','contact','organization','organization-membership','handle','conversation','message','participant','draft','interaction','meeting','opportunity','pipeline','pipeline-stage','agreement','content','creative-brief','product','sku','price','inventory-level','order','line-item','shipment','customer-review','sale','sales-report','restock','receiving','support-case','account','listing','listing-change','listing-submission','compliance-case','deliverable','permission','file-request','media-file','scheduled-transaction','recurring-series','cancellation','transaction','transfer-leg','budget-snapshot','session','file','page')),
  "system" TEXT,
  "target_id" INTEGER,
  "target_type" TEXT CHECK ("target_type" IN ('task','project','program','goal','measure','function','theme','run','bug','incident','lesson','decision','proposal','inbox-item','installed-module','contact','organization','organization-membership','handle','conversation','message','participant','draft','interaction','meeting','opportunity','pipeline','pipeline-stage','agreement','content','creative-brief','product','sku','price','inventory-level','order','line-item','shipment','customer-review','sale','sales-report','restock','receiving','support-case','account','listing','listing-change','listing-submission','compliance-case','deliverable','permission','file-request','media-file','scheduled-transaction','recurring-series','cancellation','transaction','transfer-leg','budget-snapshot','session','file','source','page','value')),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  CHECK (target_id IS NULL OR target_type IS NOT NULL)
) STRICT;

CREATE TABLE "work_measure_history" (
  "as_of" TEXT NOT NULL CHECK ("as_of" IS NULL OR julianday("as_of") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "measure" INTEGER NOT NULL,
  "note" TEXT,
  "recorded_at" TEXT CHECK ("recorded_at" IS NULL OR julianday("recorded_at") IS NOT NULL),
  "run" INTEGER,
  "value" REAL,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","measure","as_of"),
  FOREIGN KEY ("measure") REFERENCES "work_measures"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("run") REFERENCES "work_runs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "work_measure_history_link_0" ON "work_measure_history"("measure");

CREATE INDEX "work_measure_history_link_1" ON "work_measure_history"("run");

CREATE TABLE "work_measures" (
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "function" INTEGER,
  "goal" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "name" TEXT NOT NULL,
  "number" TEXT NOT NULL,
  "owner" TEXT,
  "source" TEXT,
  "target" REAL,
  "unit" TEXT,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("goal") REFERENCES "work_goals"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "work_measures_link_0" ON "work_measures"("function");

CREATE INDEX "work_measures_link_1" ON "work_measures"("goal");

CREATE TABLE "work_programs" (
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "goal" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "name" TEXT NOT NULL,
  "number" TEXT NOT NULL,
  "objective" TEXT,
  "owner" TEXT,
  "status" TEXT NOT NULL CHECK ("status" IN ('backlog','todo','in-progress','blocked','in-review','done','canceled','replaced')),
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("goal") REFERENCES "work_goals"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "work_programs_link_0" ON "work_programs"("goal");

CREATE TABLE "work_projects" (
  "acceptance_criteria" TEXT,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "description" TEXT,
  "due_on" TEXT CHECK ("due_on" IS NULL OR (julianday("due_on") IS NOT NULL AND date("due_on")="due_on")),
  "function" INTEGER,
  "goal" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "job_story" TEXT CHECK ("job_story" IS NULL OR json_valid("job_story")),
  "number" TEXT NOT NULL,
  "owner" TEXT,
  "page" TEXT,
  "problem" TEXT,
  "program" INTEGER,
  "replaces" INTEGER,
  "result" TEXT,
  "sort_order" INTEGER,
  "status" TEXT NOT NULL CHECK ("status" IN ('backlog','todo','in-progress','blocked','in-review','done','canceled','replaced')),
  "theme" INTEGER,
  "title" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("goal") REFERENCES "work_goals"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("program") REFERENCES "work_programs"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("replaces") REFERENCES "work_projects"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("theme") REFERENCES "work_themes"("id") ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT;

CREATE INDEX "work_projects_link_0" ON "work_projects"("function");

CREATE INDEX "work_projects_link_1" ON "work_projects"("goal");

CREATE INDEX "work_projects_link_2" ON "work_projects"("program");

CREATE INDEX "work_projects_link_3" ON "work_projects"("replaces");

CREATE INDEX "work_projects_link_4" ON "work_projects"("theme");

CREATE TABLE "work_runs" (
  "actor" TEXT NOT NULL,
  "cost_micro" INTEGER,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "currency" TEXT,
  "ended_at" TEXT CHECK ("ended_at" IS NULL OR julianday("ended_at") IS NOT NULL),
  "fix_rounds" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "log_path" TEXT,
  "model" TEXT,
  "note" TEXT,
  "number" TEXT NOT NULL,
  "proof" TEXT,
  "result" TEXT,
  "runtime" TEXT,
  "session" TEXT,
  "started_at" TEXT CHECK ("started_at" IS NULL OR julianday("started_at") IS NOT NULL),
  "status" TEXT NOT NULL CHECK ("status" IN ('running','succeeded','failed','partial','canceled','unknown')),
  "subject_id" INTEGER,
  "subject_type" TEXT NOT NULL CHECK ("subject_type" IN ('task','project','program','workflow','feeder')),
  "tokens" INTEGER,
  "tool" TEXT,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  CHECK (("cost_micro" IS NULL) OR coalesce(length(trim(currency)),0)>0)
) STRICT;

CREATE TABLE "work_tasks" (
  "acceptance_criteria" TEXT,
  "body" TEXT,
  "reviewer" TEXT CHECK ("reviewer" IN ('lead','@person@')),
  "reviewed_by" TEXT,
  "claimed_at" TEXT CHECK ("claimed_at" IS NULL OR julianday("claimed_at") IS NOT NULL),
  "claimed_by" TEXT,
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "created_by" TEXT,
  "due_on" TEXT CHECK ("due_on" IS NULL OR (julianday("due_on") IS NOT NULL AND date("due_on")="due_on")),
  "flag" INTEGER NOT NULL CHECK ("flag" IN (0,1)),
  "function" INTEGER,
  "goal" INTEGER,
  "id" INTEGER PRIMARY KEY,
  "idempotency_key" TEXT,
  "important" INTEGER NOT NULL CHECK ("important" IN (0,1)),
  "number" TEXT NOT NULL,
  "owner" TEXT,
  "parent" INTEGER,
  "planned_on" TEXT CHECK ("planned_on" IS NULL OR (julianday("planned_on") IS NOT NULL AND date("planned_on")="planned_on")),
  "problem" TEXT,
  "project" INTEGER,
  "sort_order" INTEGER,
  "source" TEXT,
  "status" TEXT NOT NULL CHECK ("status" IN ('backlog','todo','in-progress','blocked','in-review','done','canceled','replaced')),
  "title" TEXT NOT NULL,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "urgent" INTEGER NOT NULL CHECK ("urgent" IN (0,1)),
  "version" INTEGER NOT NULL DEFAULT 1,
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number"),
  UNIQUE ("idempotency_key"),
  FOREIGN KEY ("function") REFERENCES "work_functions"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("goal") REFERENCES "work_goals"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("parent") REFERENCES "work_tasks"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  FOREIGN KEY ("project") REFERENCES "work_projects"("id") ON UPDATE RESTRICT ON DELETE RESTRICT,
  CHECK (reviewer IS NOT 'lead' OR reviewed_by IS NULL OR coalesce(length(trim(reviewed_by)),0)>0),
  CHECK (owner IS NULL OR lower(owner)='@person@' OR reviewer IS NOT NULL)
) STRICT;

CREATE INDEX "work_tasks_link_0" ON "work_tasks"("function");

CREATE INDEX "work_tasks_link_1" ON "work_tasks"("goal");

CREATE INDEX "work_tasks_link_2" ON "work_tasks"("parent");

CREATE INDEX "work_tasks_link_3" ON "work_tasks"("project");

CREATE TABLE "work_themes" (
  "created_at" TEXT CHECK ("created_at" IS NULL OR julianday("created_at") IS NOT NULL),
  "id" INTEGER PRIMARY KEY,
  "name" TEXT NOT NULL,
  "number" TEXT NOT NULL,
  "page" TEXT,
  "sort_order" INTEGER,
  "tagline" TEXT,
  "updated_at" TEXT CHECK ("updated_at" IS NULL OR julianday("updated_at") IS NOT NULL),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  UNIQUE ("workspace","number")
) STRICT;

CREATE TABLE "base_capabilities" (
  "id" INTEGER PRIMARY KEY,
  "name" TEXT NOT NULL,
  "kind" TEXT NOT NULL CHECK ("kind" IN ('agent','skill','mcp','cli','schedule','hook','plugin','report','workflow','service')),
  "set" TEXT CHECK ("set"='base' OR foxrun_workspace_allowed("set")),
  "workspace" TEXT NOT NULL CHECK (foxrun_workspace_allowed("workspace")),
  "status" TEXT NOT NULL CHECK ("status" IN ('live','parked','dead')),
  "runtimes" TEXT CHECK ("runtimes" IS NULL OR json_valid("runtimes")) CHECK ("runtimes" IS NULL OR json_type("runtimes")='array'),
  "card_path" TEXT NOT NULL,
  UNIQUE ("name"),
  UNIQUE ("card_path"),
  CHECK (status='dead' OR "set" IS NOT NULL),
  CHECK (status='dead' OR (runtimes IS NOT NULL AND json_array_length(runtimes)>0))
) STRICT;

CREATE TABLE "_foxrun_sequence" ("id" INTEGER PRIMARY KEY CHECK(id=1), "value" INTEGER NOT NULL CHECK(value>=0)) STRICT;
