ALTER TABLE telegram_users
ADD COLUMN reminders_enabled INTEGER NOT NULL DEFAULT 1
CHECK (reminders_enabled IN (0, 1));
