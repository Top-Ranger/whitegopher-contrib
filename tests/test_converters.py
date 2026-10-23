"""Tests for the converters. Run from the repository root: python3 -m unittest discover -v tests

Set WHITEGOPHER_BIN (and the database environment the binary needs) to also
check every generated tree with `whitegopher import -dry-run`.
"""

import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for sub in ("common", "radicale", "baikal"):
    sys.path.insert(0, os.path.join(ROOT, sub))

import baikal2whitegopher as baikal  # noqa: E402
import radicale2whitegopher as radicale  # noqa: E402
import wgimport as wg  # noqa: E402

ICS = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\nBEGIN:VEVENT\r\nUID:e1\r\n"
       b"DTSTAMP:20240101T000000Z\r\nDTSTART:20240102T100000Z\r\nSUMMARY:Standup\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
VCF = b"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:c1\r\nFN:Bob\r\nN:;Bob;;;\r\nEND:VCARD\r\n"
TZ = "BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\nEND:VTIMEZONE"


def read_json(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return json.load(f)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.out = os.path.join(self.tmp, "out")

    def run_quiet(self, fn, *a):
        with contextlib.redirect_stderr(io.StringIO()):
            return fn(*a)

    def tree_ok(self):
        """Check the tree with the real importer, if one is configured."""
        binary = os.environ.get("WHITEGOPHER_BIN")
        if binary:
            r = subprocess.run([binary, "import", "-dry-run", self.out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read_json(self.out, "whitegopher-import.json")["format"], "whitegopher-import")


class RadicaleTest(Base):
    def put(self, rel, data, mode="wb"):
        p = os.path.join(self.tmp, "store", "collection-root", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, mode) as f:
            f.write(data)

    def test_convert(self):
        self.put("alice/work/.Radicale.props", json.dumps({
            "tag": "VCALENDAR", "D:displayname": "Work", "C:calendar-description": "d",
            "ICAL:calendar-color": "#ff0000ff", "ICAL:calendar-order": "3",
            "C:supported-calendar-component-set": "VEVENT",
            "{urn:ietf:params:xml:ns:caldav}calendar-timezone":
                "BEGIN:VCALENDAR\r\n" + TZ + "\r\nEND:VCALENDAR"}), "w")
        self.put("alice/work/a b.ics", ICS)
        self.put("alice/work/.Radicale.cache/x", b"junk")
        self.put("alice/book/.Radicale.props", json.dumps(
            {"tag": "VADDRESSBOOK", "CR:addressbook-description": "people"}), "w")
        self.put("alice/book/bob.vcf", VCF)
        self.put("alice/feed/.Radicale.props", json.dumps({"tag": "VSUBSCRIBED"}), "w")
        self.put("bob/inbox/.Radicale.props", json.dumps({"tag": "VCALENDAR"}), "w")

        tree = self.run_quiet(radicale.convert, os.path.join(self.tmp, "store"), self.out)

        self.assertEqual(tree.counts, {"users": 2, "calendars": 2, "addressbooks": 1, "objects": 2})
        cal = os.path.join(self.out, "users", "alice", "calendars", "work")
        meta = read_json(cal, "collection.json")
        self.assertEqual(meta["display_name"], "Work")
        self.assertEqual(meta["sort_order"], 3)
        self.assertEqual(meta["components"], "VEVENT")
        self.assertEqual(meta["timezone"], TZ)
        with open(os.path.join(cal, "objects", "a%20b.ics"), "rb") as f:
            self.assertEqual(f.read(), ICS)
        self.assertEqual(os.listdir(os.path.join(cal, "objects")), ["a%20b.ics"])
        book = os.path.join(self.out, "users", "alice", "addressbooks", "book")
        self.assertEqual(read_json(book, "collection.json"), {"description": "people"})
        self.assertTrue(os.path.isdir(os.path.join(self.out, "users", "bob", "calendars", "inbox-calendar")))
        self.assertTrue(any("VSUBSCRIBED" in w for w in tree.warnings))
        self.tree_ok()

    def test_nonempty_output_refused(self):
        os.makedirs(self.out)
        open(os.path.join(self.out, "x"), "w").close()
        with self.assertRaises(SystemExit):
            wg.Tree(self.out, "t")


SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, digesta1 TEXT);
CREATE TABLE principals (id INTEGER PRIMARY KEY, uri TEXT, email TEXT, displayname TEXT);
CREATE TABLE calendars (id INTEGER PRIMARY KEY, synctoken INTEGER, components TEXT);
CREATE TABLE calendarinstances (id INTEGER PRIMARY KEY, calendarid INTEGER, principaluri TEXT, access INTEGER,
  displayname TEXT, uri TEXT, description TEXT, calendarorder INTEGER, calendarcolor TEXT, timezone TEXT,
  transparent INTEGER);
CREATE TABLE calendarobjects (id INTEGER PRIMARY KEY, calendardata BLOB, uri TEXT, calendarid INTEGER, etag TEXT);
CREATE TABLE addressbooks (id INTEGER PRIMARY KEY, principaluri TEXT, displayname TEXT, uri TEXT, description TEXT);
CREATE TABLE cards (id INTEGER PRIMARY KEY, addressbookid INTEGER, carddata BLOB, uri TEXT, etag TEXT);
"""


class BaikalTest(Base):
    def make_db(self):
        path = os.path.join(self.tmp, "db.sqlite")
        con = sqlite3.connect(path)
        con.executescript(SCHEMA)
        con.executescript("""
INSERT INTO users VALUES (1, 'alice', 'ABCDEF0123');
INSERT INTO users VALUES (2, 'bob', 'ff');
INSERT INTO principals VALUES (1, 'principals/alice', 'Alice@Example.com', 'Alice A.');
INSERT INTO calendars VALUES (1, 1, 'VEVENT,VTODO');
INSERT INTO calendarinstances VALUES (1, 1, 'principals/alice', 1, 'Default', 'default', 'desc', 2, '#00ff00ff',
  'BEGIN:VCALENDAR\r\nBEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\nEND:VTIMEZONE\r\nEND:VCALENDAR', 1);
INSERT INTO calendarinstances VALUES (2, 1, 'principals/bob', 3, 'Shared', 'shared', '', 0, '', '', 0);
INSERT INTO addressbooks VALUES (1, 'principals/alice', 'Contacts', 'default', '');
""")
        con.execute("INSERT INTO calendarobjects VALUES (1, ?, 'e1.ics', 1, 'abc')", (ICS,))
        con.execute("INSERT INTO calendarobjects VALUES (2, ?, 'e2.ics', 1, 'def')",
                    (ICS.replace(b"Standup", b"Stand\xfcp"),))
        con.execute("INSERT INTO cards VALUES (1, 1, ?, 'bob.vcf', '\"c1\"')", (VCF,))
        con.execute("INSERT INTO cards VALUES (2, 1, ?, 'old.vcf', 'c2')",
                    (b"BEGIN:VCARD\r\nVERSION:2.1\r\nFN;CHARSET=ISO-8859-1:M\xfcller\r\nEND:VCARD\r\n",))
        con.commit()
        con.close()
        return path

    def test_convert(self):
        class Args:
            sqlite, mysql = self.make_db(), None
        tree = self.run_quiet(baikal.convert, baikal.DB(Args), self.out)

        self.assertEqual(tree.counts, {"users": 2, "calendars": 1, "addressbooks": 1, "objects": 4})
        self.assertEqual(read_json(self.out, "users", "alice", "user.json"),
                         {"display_name": "Alice A.", "email": "alice@example.com", "digest_ha1": "abcdef0123"})
        self.assertEqual(read_json(self.out, "users", "bob", "user.json"), {"digest_ha1": "ff"})
        cal = os.path.join(self.out, "users", "alice", "calendars", "default")
        meta = read_json(cal, "collection.json")
        self.assertEqual(meta["components"], "VEVENT,VTODO")
        self.assertTrue(meta["transparent"])
        self.assertEqual(meta["timezone"], TZ)
        self.assertEqual(meta["etags"], {"e1.ics": "abc"})  # e2.ics was rewritten
        with open(os.path.join(cal, "objects", "e2.ics"), "rb") as f:
            self.assertIn("Standüp".encode(), f.read())
        book = os.path.join(self.out, "users", "alice", "addressbooks", "default")
        self.assertEqual(read_json(book, "collection.json")["etags"], {"bob.vcf": "c1"})
        with open(os.path.join(book, "objects", "old.vcf"), "rb") as f:
            self.assertIn("FN;CHARSET=UTF-8:Müller".encode(), f.read())
        self.assertFalse(os.path.exists(os.path.join(self.out, "users", "bob", "calendars")))  # sharee, not owner
        self.tree_ok()


class TextTest(unittest.TestCase):
    def test_quoted_printable(self):
        data = (b"BEGIN:VCARD\r\nVERSION:2.1\r\nN;ENCODING=QUOTED-PRINTABLE:M=C3=BCller;=\r\nHans\r\n"
                b"NOTE:a=3Db\r\nEND:VCARD\r\n")
        out, changed = wg.normalize_vcard(data)
        self.assertTrue(changed)
        self.assertEqual(out, "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Müller;Hans\r\nNOTE:a=3Db\r\nEND:VCARD\r\n".encode())

    def test_clean_vcard_untouched(self):
        self.assertEqual(wg.normalize_vcard(VCF), (VCF, False))

    def test_slug_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            t = wg.Tree(os.path.join(d, "o"), "t")
            t.user("u")
            with contextlib.redirect_stderr(io.StringIO()):
                a = t.collection("u", wg.CALENDAR, "my cal!")
                b = t.collection("u", wg.CALENDAR, "my_cal_")
            self.assertTrue(a.rel.endswith("my_cal_"))
            self.assertTrue(b.rel.endswith("my_cal_-2"))


if __name__ == "__main__":
    unittest.main()
