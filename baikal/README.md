# Baikal → White Gopher

```sh
./baikal2whitegopher.py --sqlite /path/to/Specific/db/db.sqlite ./tree
./baikal2whitegopher.py --mysql 'mysql://user:pass@localhost:3306/baikal' ./tree
whitegopher import -dry-run ./tree && whitegopher import ./tree
```

The database is opened read-only. Back up and stop writers first. MySQL needs
`pip install pymysql`; SQLite needs nothing. Percent-encode special characters
in the MySQL URL's user and password.

- Users keep their passwords: Baikal's digest hash becomes `digest_ha1`. Set
  White Gopher's `realm` to Baikal's (default `BaikalDAV`) **before** importing;
  each hash is replaced by argon2id at the user's first login.
- Display names and emails come from `principals`.
- Calendars: name, description, color, order, components, time zone and
  free-busy transparency. Both the current (`calendarinstances`) and the older
  schema are understood. Only the owner's copy of a shared calendar is
  converted.
- ETags are kept, except for objects that had to be rewritten.
- vCards with quoted-printable or legacy `CHARSET=` lines are rewritten as
  UTF-8.

See the [top-level README](../README.md) for common behavior and tests.
