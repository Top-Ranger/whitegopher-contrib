#!/usr/bin/env python3
"""Convert a Baikal (sabre/dav) database to a White Gopher import tree.

    baikal2whitegopher.py --sqlite Specific/db/db.sqlite OUT_DIR
    baikal2whitegopher.py --mysql 'mysql://user:pass@host:3306/baikal' OUT_DIR

The database is opened read-only and never modified. Users keep their
passwords through Baikal's digest hash (`digest_ha1`); set the White Gopher
`realm` to Baikal's (default "BaikalDAV") before importing. MySQL needs the
PyMySQL package (`pip install pymysql`); SQLite needs nothing.
"""

import argparse
import os
import sys
from urllib.parse import unquote, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
import wgimport as wg  # noqa: E402


class DB:
    """Minimal wrapper hiding the SQLite/MySQL differences."""

    def __init__(self, args):
        if args.sqlite:
            import sqlite3
            from pathlib import Path
            self.con = sqlite3.connect("%s?mode=ro" % Path(args.sqlite).resolve().as_uri(), uri=True)
            self.ph = "?"
        else:
            try:
                import pymysql
            except ImportError:
                sys.exit("error: MySQL support needs PyMySQL: pip install pymysql")
            u = urlparse(args.mysql)
            if u.scheme != "mysql" or not u.path.strip("/"):
                sys.exit("error: --mysql expects mysql://user:pass@host[:port]/database")
            self.con = pymysql.connect(
                host=u.hostname or "localhost", port=u.port or 3306, user=unquote(u.username or ""),
                password=unquote(u.password or ""), database=u.path.strip("/"), charset="utf8mb4",
                read_only=True)
            self.ph = "%s"

    def query(self, sql, *params):
        cur = self.con.cursor()
        cur.execute(sql.replace("?", self.ph), params)
        rows = cur.fetchall()
        cur.close()
        return rows

    def has_table(self, name):
        try:
            self.query("SELECT 1 FROM %s WHERE 1 = 0" % name)
            return True
        except Exception:
            return False


def text(v):
    if v is None:
        return ""
    return v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else str(v)


def blob(v):
    if v is None:
        return b""
    return bytes(v) if isinstance(v, (bytes, bytearray, memoryview)) else str(v).encode("utf-8")


def convert(db, out):
    tree = wg.Tree(out, "baikal2whitegopher")
    users = convert_users(db, tree)
    convert_calendars(db, tree, users)
    convert_addressbooks(db, tree, users)
    return tree


def convert_users(db, tree):
    """Returns the set of principal URIs ('principals/alice') of imported users."""
    info = {}
    if db.has_table("principals"):
        for uri, dn, em in db.query("SELECT uri, displayname, email FROM principals"):
            info[text(uri)] = (text(dn), text(em))
    principals = set()
    for name, ha1 in db.query("SELECT username, digesta1 FROM users ORDER BY username"):
        name = text(name)
        dn, em = info.get("principals/" + name, ("", ""))
        tree.user(name, dn, em.lower(), text(ha1).lower())
        principals.add("principals/" + name)
    return principals


def owner(principal):
    return principal.split("/", 1)[1] if "/" in principal else principal


def convert_calendars(db, tree, users):
    # Newer schemas split calendars (shared data) from calendarinstances
    # (per-principal properties); older ones keep everything in calendars.
    if db.has_table("calendarinstances"):
        q = ("SELECT ci.calendarid, ci.principaluri, ci.uri, ci.displayname, ci.description,"
             " ci.calendarorder, ci.calendarcolor, ci.timezone, c.components, ci.transparent"
             " FROM calendarinstances ci JOIN calendars c ON c.id = ci.calendarid"
             " WHERE ci.access = 1 ORDER BY ci.principaluri, ci.uri")
    else:
        q = ("SELECT id, principaluri, uri, displayname, description, calendarorder,"
             " calendarcolor, timezone, components, 0 FROM calendars ORDER BY principaluri, uri")
    for cid, principal, uri, name, desc, order, color, tz, comps, transp in db.query(q):
        principal, uri = text(principal), text(uri)
        if principal not in users:
            tree.warn("calendar %r: unknown owner %r, skipped" % (uri, principal))
            continue
        coll = tree.collection(
            owner(principal), wg.CALENDAR, uri, display_name=text(name), description=text(desc),
            color=text(color), sort_order=int(order or 0), components=text(comps),
            timezone=wg.vtimezone(text(tz)), transparent=bool(transp))
        if coll is not None:
            copy_objects(db, coll, wg.CALENDAR, "SELECT uri, calendardata, etag FROM calendarobjects"
                         " WHERE calendarid = ? ORDER BY uri", cid)


def convert_addressbooks(db, tree, users):
    q = "SELECT id, principaluri, uri, displayname, description FROM addressbooks ORDER BY principaluri, uri"
    for bid, principal, uri, name, desc in db.query(q):
        principal, uri = text(principal), text(uri)
        if principal not in users:
            tree.warn("address book %r: unknown owner %r, skipped" % (uri, principal))
            continue
        coll = tree.collection(owner(principal), wg.ADDRESSBOOK, uri,
                               display_name=text(name), description=text(desc))
        if coll is not None:
            copy_objects(db, coll, wg.ADDRESSBOOK, "SELECT uri, carddata, etag FROM cards"
                         " WHERE addressbookid = ? ORDER BY uri", bid)


def copy_objects(db, coll, kind, query, srcid):
    for uri, data, etag in db.query(query, srcid):
        uri = text(uri)
        data, changed = wg.fix_object(kind, blob(data))
        if changed:
            coll.tree.warn("%s/%s: converted to UTF-8" % (coll.label, uri))
        # The source ETag only describes the original bytes.
        coll.add(uri, data, "" if changed else text(etag))
    coll.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--sqlite", metavar="FILE", help="Baikal SQLite database (Specific/db/db.sqlite)")
    src.add_argument("--mysql", metavar="URL", help="mysql://user:pass@host[:port]/database")
    ap.add_argument("out", help="output directory, must be empty or not exist")
    args = ap.parse_args()
    tree = convert(DB(args), args.out)
    c = tree.counts
    print("%d users, %d calendars, %d address books, %d objects, %d warnings"
          % (c["users"], c["calendars"], c["addressbooks"], c["objects"], len(tree.warnings)))


if __name__ == "__main__":
    main()
