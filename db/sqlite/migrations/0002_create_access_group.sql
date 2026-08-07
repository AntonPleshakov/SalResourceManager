CREATE TABLE access_group (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    group_id INTEGER NOT NULL
);
