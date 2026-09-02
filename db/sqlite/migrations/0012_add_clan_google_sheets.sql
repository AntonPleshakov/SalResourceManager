ALTER TABLE clans ADD COLUMN spreadsheet_id TEXT;

CREATE UNIQUE INDEX clans_spreadsheet_id_unique
ON clans(spreadsheet_id)
WHERE spreadsheet_id IS NOT NULL;

ALTER TABLE admin_clans ADD COLUMN google_email TEXT;
ALTER TABLE admin_clans ADD COLUMN google_access_requested_at INTEGER;

CREATE UNIQUE INDEX admin_clans_group_google_email_unique
ON admin_clans(group_id, google_email)
WHERE google_email IS NOT NULL;
