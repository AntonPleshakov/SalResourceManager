# SQLite migrations

The SQLite database has one global, linear migration history. Migration files
live in `migrations/` and use the format `NNNN_description.sql`, starting at
`0001` without gaps.

Each migration is one immutable logical change and may affect one or several
tables. Once a migration has been deployed, do not edit or reorder it; add the
next numbered file instead.

Migration SQL must not:

- use `CREATE TABLE IF NOT EXISTS` to hide schema conflicts;
- execute `BEGIN`, `COMMIT`, or `ROLLBACK`;
- set `PRAGMA user_version`.

`migration_runner.py` applies every pending file in its own `BEGIN IMMEDIATE`
transaction and updates `user_version` in the same transaction. A new database
starts at version `0` and receives every migration in order. After migration,
`SQLiteMirror` validates the resulting columns, types, nullability, and primary
keys before importing Google data.
