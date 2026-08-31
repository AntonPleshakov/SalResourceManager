# SQLite migrations

The database is initialized by `initializer.py`. Migrations live in
`sqlite/migrations/` and use consecutive names such as
`0011_description.sql`.

Never edit or reorder a deployed migration; add the next numbered file.
Migration SQL must not:

- use `CREATE TABLE IF NOT EXISTS` to hide schema conflicts;
- execute `BEGIN`, `COMMIT`, or `ROLLBACK`;
- set `PRAGMA user_version`.
