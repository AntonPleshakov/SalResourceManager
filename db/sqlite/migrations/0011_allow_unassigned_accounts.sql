CREATE TABLE game_accounts_v3 (
    account_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES telegram_users(user_id) ON DELETE CASCADE,
    clan_id INTEGER REFERENCES clans(group_id),
    tag TEXT NOT NULL,
    UNIQUE(user_id, tag)
);

INSERT INTO game_accounts_v3 (account_id, user_id, clan_id, tag)
SELECT account_id, user_id, clan_id, tag
FROM game_accounts;

CREATE TABLE user_data_v4 (
    account_id INTEGER PRIMARY KEY REFERENCES game_accounts_v3(account_id) ON DELETE CASCADE,
    mount_keys INTEGER NOT NULL,
    mount_keys_updated_on TEXT NOT NULL,
    skills INTEGER NOT NULL,
    skills_updated_on TEXT NOT NULL,
    shells INTEGER NOT NULL,
    shells_updated_on TEXT NOT NULL,
    hammers INTEGER NOT NULL,
    hammers_updated_on TEXT NOT NULL,
    pets INTEGER NOT NULL,
    pets_updated_on TEXT NOT NULL,
    unmerged_mounts INTEGER NOT NULL,
    unmerged_mounts_updated_on TEXT NOT NULL,
    forge_level INTEGER NOT NULL,
    forge_level_updated_on TEXT NOT NULL,
    skill_summon_cost INTEGER NOT NULL,
    skill_summon_cost_updated_on TEXT NOT NULL,
    extra_egg_chance INTEGER NOT NULL,
    extra_egg_chance_updated_on TEXT NOT NULL,
    mount_summon_cost INTEGER NOT NULL,
    mount_summon_cost_updated_on TEXT NOT NULL,
    extra_mount_chance INTEGER NOT NULL,
    extra_mount_chance_updated_on TEXT NOT NULL,
    eggs_per_hatch_batch INTEGER NOT NULL,
    max_egg_level INTEGER NOT NULL,
    hatch_batches_common INTEGER NOT NULL,
    hatch_batches_rare INTEGER NOT NULL,
    hatch_batches_epic INTEGER NOT NULL,
    hatch_batches_legendary INTEGER NOT NULL,
    hatch_batches_ultimate INTEGER NOT NULL,
    hatch_batches_mythic INTEGER NOT NULL
);

INSERT INTO user_data_v4
SELECT * FROM user_data;

DROP TABLE user_data;
DROP TABLE game_accounts;
ALTER TABLE game_accounts_v3 RENAME TO game_accounts;
ALTER TABLE user_data_v4 RENAME TO user_data;
CREATE INDEX game_accounts_user_id_idx ON game_accounts(user_id);
CREATE INDEX game_accounts_clan_id_idx ON game_accounts(clan_id);
