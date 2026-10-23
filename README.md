# White Gopher contrib

Converters that migrate data from other CalDAV/CardDAV servers to
[White Gopher](https://github.com/bitflipp/whitegopher). Each one reads the
source server and writes a directory tree in White Gopher's
[import format](https://github.com/bitflipp/whitegopher/blob/main/docs/import-format.md),
which `whitegopher import` then loads. Python 3.8+, standard library only
(except MySQL for Baikal).

| Converter | Source |
|---|---|
| [`radicale/`](radicale) | [Radicale](https://radicale.org) filesystem storage |
| [`baikal/`](baikal) | [Baikal](https://sabre.io/baikal/) (sabre/dav) SQLite or MySQL database |

## Layout

```
radicale/   Radicale converter and its README
baikal/     Baikal converter and its README
common/     wgimport.py: import-tree writer and text clean-up shared by both
tests/      unit tests
```

Clone the repository and run a script in place; the converters find `common/`
relative to themselves.

## Usage

```sh
./radicale/radicale2whitegopher.py /var/lib/radicale/collections ./tree
./baikal/baikal2whitegopher.py --sqlite /path/to/Specific/db/db.sqlite ./tree
./baikal/baikal2whitegopher.py --mysql 'mysql://user:pass@localhost/baikal' ./tree   # needs: pip install pymysql

whitegopher import -dry-run ./tree    # check counts and warnings
whitegopher import ./tree
```

The output directory must be empty or not exist. Sources are only read; stop
clients from writing to the old server first (or accept that later changes are
lost). Anything a converter had to change or skip is reported as a `warning:`
on stderr. See the White Gopher deployment guide (section 8) for the rest of
the migration.

## What is converted

| | Radicale | Baikal |
|---|---|---|
| Users | directory names | `users` table, with display name and email from `principals` |
| Passwords | not available: set them in the admin UI | kept as `digest_ha1`; set White Gopher's `realm` to Baikal's (default `BaikalDAV`) **before** importing |
| Calendars | name, description, colour, order, components, time zone | same, plus free-busy transparency |
| Address books | name, description | same |
| Objects | files as stored, URIs kept | rows as stored, URIs and ETags kept |

Not converted: sharing, subscriptions (Radicale `VSUBSCRIBED`), scheduling
inboxes, app passwords. Calendars shared *to* a Baikal user are not copied
into that user; only the owner's copy is.

Fixes applied on the way: data that is not UTF-8 is transcoded (Windows-1252),
vCards with quoted-printable or legacy `CHARSET=` lines are rewritten as UTF-8
(Baikal), and collection names White Gopher rejects (`inbox`, `outbox`,
`notification`, unsupported characters) are renamed. The source ETag is
dropped for any object that was rewritten.

## Tests

```sh
python3 -m unittest discover -v tests
```

The tests build a Radicale store and a Baikal SQLite database from scratch. The
Radicale layout (`.Radicale.props` keys) and the Baikal schema are written from
the documented formats; run `import -dry-run` on real data before trusting a
migration.

## Contributing

Converters for other servers are welcome: add a folder with the script and a
README, reuse `common/wgimport.py`, and add tests under `tests/`.

## Licence

[MIT](LICENSE), as White Gopher.
