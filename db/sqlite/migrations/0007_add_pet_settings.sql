ALTER TABLE user_data
ADD COLUMN eggs_per_hatch_batch INTEGER NOT NULL DEFAULT 4;

ALTER TABLE user_data
ADD COLUMN max_egg_level INTEGER NOT NULL DEFAULT 6;

ALTER TABLE user_data
ADD COLUMN hatch_batches_common INTEGER NOT NULL DEFAULT 0;

ALTER TABLE user_data
ADD COLUMN hatch_batches_rare INTEGER NOT NULL DEFAULT 0;

ALTER TABLE user_data
ADD COLUMN hatch_batches_epic INTEGER NOT NULL DEFAULT 0;

ALTER TABLE user_data
ADD COLUMN hatch_batches_legendary INTEGER NOT NULL DEFAULT 0;

ALTER TABLE user_data
ADD COLUMN hatch_batches_ultimate INTEGER NOT NULL DEFAULT 1;

ALTER TABLE user_data
ADD COLUMN hatch_batches_mythic INTEGER NOT NULL DEFAULT 1;
