ALTER TABLE user_data
ADD COLUMN free_equipment_chance INTEGER NOT NULL DEFAULT 0;

ALTER TABLE user_data
ADD COLUMN free_equipment_chance_updated_on TEXT NOT NULL DEFAULT '';
