CREATE TABLE clans (
    group_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    title_needs_sync INTEGER NOT NULL DEFAULT 0
        CHECK (title_needs_sync IN (0, 1))
);

INSERT INTO clans (group_id, title, title_needs_sync)
SELECT group_id, printf('Клан %lld', group_id), 1
FROM access_group;

CREATE TABLE game_accounts_v2 (
    account_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES telegram_users(user_id) ON DELETE CASCADE,
    clan_id INTEGER NOT NULL REFERENCES clans(group_id),
    tag TEXT NOT NULL,
    UNIQUE(user_id, tag)
);

INSERT INTO game_accounts_v2 (account_id, user_id, clan_id, tag)
SELECT ga.account_id, ga.user_id, clans.group_id, ga.tag
FROM game_accounts ga
CROSS JOIN clans;

CREATE TABLE user_data_v3 (
    account_id INTEGER PRIMARY KEY REFERENCES game_accounts_v2(account_id) ON DELETE CASCADE,
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

INSERT INTO user_data_v3
SELECT * FROM user_data;

DROP TABLE user_data;
DROP TABLE game_accounts;
ALTER TABLE game_accounts_v2 RENAME TO game_accounts;
ALTER TABLE user_data_v3 RENAME TO user_data;
CREATE INDEX game_accounts_user_id_idx ON game_accounts(user_id);
CREATE INDEX game_accounts_clan_id_idx ON game_accounts(clan_id);

ALTER TABLE admins
ADD COLUMN active_group_id INTEGER REFERENCES clans(group_id);

CREATE TABLE admin_clans (
    user_id INTEGER NOT NULL REFERENCES admins(user_id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES clans(group_id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, group_id)
);

INSERT INTO admin_clans (user_id, group_id)
SELECT admins.user_id, clans.group_id
FROM admins
CROSS JOIN clans;

UPDATE admins
SET active_group_id = (SELECT group_id FROM clans LIMIT 1);

DROP TABLE access_group;
