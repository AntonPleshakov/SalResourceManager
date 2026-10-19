ALTER TABLE telegram_users ADD COLUMN game_language TEXT NOT NULL DEFAULT 'ru'
    CHECK (game_language IN ('ru', 'en', 'de'));
