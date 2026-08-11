CREATE TABLE telegram_users (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    active_game_account_id INTEGER
);

CREATE TABLE game_accounts (
    account_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES telegram_users(user_id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    UNIQUE(user_id, tag)
);

INSERT INTO telegram_users (user_id, username)
SELECT user_id, username
FROM user_data;

INSERT INTO game_accounts (user_id, tag)
SELECT
    user_id,
    CASE
        WHEN trim(tag) <> '' THEN trim(tag)
        WHEN trim(username) <> '' THEN trim(username)
        ELSE 'Аккаунт 1'
    END
FROM user_data;

CREATE TABLE user_data_v2 (
    account_id INTEGER PRIMARY KEY REFERENCES game_accounts(account_id) ON DELETE CASCADE,
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

INSERT INTO user_data_v2 (
    account_id,
    mount_keys, mount_keys_updated_on,
    skills, skills_updated_on,
    shells, shells_updated_on,
    hammers, hammers_updated_on,
    pets, pets_updated_on,
    unmerged_mounts, unmerged_mounts_updated_on,
    forge_level, forge_level_updated_on,
    skill_summon_cost, skill_summon_cost_updated_on,
    extra_egg_chance, extra_egg_chance_updated_on,
    mount_summon_cost, mount_summon_cost_updated_on,
    extra_mount_chance, extra_mount_chance_updated_on,
    eggs_per_hatch_batch, max_egg_level,
    hatch_batches_common, hatch_batches_rare, hatch_batches_epic,
    hatch_batches_legendary, hatch_batches_ultimate, hatch_batches_mythic
)
SELECT
    game_accounts.account_id,
    user_data.mount_keys, user_data.mount_keys_updated_on,
    user_data.skills, user_data.skills_updated_on,
    user_data.shells, user_data.shells_updated_on,
    user_data.hammers, user_data.hammers_updated_on,
    user_data.pets, user_data.pets_updated_on,
    user_data.unmerged_mounts, user_data.unmerged_mounts_updated_on,
    user_data.forge_level, user_data.forge_level_updated_on,
    user_data.skill_summon_cost, user_data.skill_summon_cost_updated_on,
    user_data.extra_egg_chance, user_data.extra_egg_chance_updated_on,
    user_data.mount_summon_cost, user_data.mount_summon_cost_updated_on,
    user_data.extra_mount_chance, user_data.extra_mount_chance_updated_on,
    user_data.eggs_per_hatch_batch, user_data.max_egg_level,
    user_data.hatch_batches_common, user_data.hatch_batches_rare,
    user_data.hatch_batches_epic, user_data.hatch_batches_legendary,
    user_data.hatch_batches_ultimate, user_data.hatch_batches_mythic
FROM user_data
JOIN game_accounts ON game_accounts.user_id = user_data.user_id;

UPDATE telegram_users
SET active_game_account_id = (
    SELECT account_id
    FROM game_accounts
    WHERE game_accounts.user_id = telegram_users.user_id
);

DROP TABLE user_data;
ALTER TABLE user_data_v2 RENAME TO user_data;

CREATE INDEX game_accounts_user_id_idx ON game_accounts(user_id);
