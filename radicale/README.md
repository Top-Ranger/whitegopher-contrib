# Radicale → White Gopher

```sh
./radicale2whitegopher.py /var/lib/radicale/collections ./tree
whitegopher import -dry-run ./tree && whitegopher import ./tree
```

`STORAGE` is Radicale's `filesystem_folder` (or the directory containing
`collection-root`). It is only read. Back up and stop writers first.

- Users are the directory names. Radicale stores no display names, emails or
  password hashes (passwords live in htpasswd or an external authenticator), so
  set them in the White Gopher admin UI afterwards.
- Collections are read from `.Radicale.props`: display name, description,
  colour, order, supported components, time zone. A collection without a
  recorded type is guessed from its file extensions.
- Object files are copied as they are, with their names as URIs. Radicale does
  not store ETags, so White Gopher derives them.
- Skipped with a warning: subscriptions (`VSUBSCRIBED`) and anything that is
  not a calendar or address book.

See the [top-level README](../README.md) for common behaviour and tests.
