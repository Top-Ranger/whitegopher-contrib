"""Writer for the White Gopher import format (version 1) and the text
clean-up the converters share.

Format: https://github.com/bitflipp/whitegopher/blob/main/docs/import-format.md
Python 3.8+, standard library only.
"""

import json
import os
import re
import sys
from urllib.parse import quote

FORMAT = "whitegopher-import"
VERSION = 1

CALENDAR = "calendar"
ADDRESSBOOK = "addressbook"
_DIRS = {CALENDAR: "calendars", ADDRESSBOOK: "addressbooks"}

_SLUG_OK = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$")
_SLUG_BAD = re.compile(r"[^A-Za-z0-9._-]")
_RESERVED = {"inbox", "outbox", "notification"}


class Tree:
    """An import tree under `root`, which must not exist or be empty."""

    def __init__(self, root, generator):
        if os.path.isdir(root) and os.listdir(root):
            raise SystemExit("error: output directory %r is not empty" % root)
        self.root = root
        self.warnings = []
        self.counts = {"users": 0, "calendars": 0, "addressbooks": 0, "objects": 0}
        self._slugs = set()
        self._users = set()
        os.makedirs(root, exist_ok=True)
        self._json("whitegopher-import.json",
                   {"format": FORMAT, "version": VERSION, "generator": generator})

    def warn(self, msg):
        self.warnings.append(msg)
        print("warning: " + msg, file=sys.stderr)

    def _json(self, rel, obj):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def _user_dir(self, user):
        return os.path.join(self.root, "users", pct(user))

    def user(self, name, display_name="", email="", digest_ha1=""):
        """Declare a user. Fields left empty are omitted from user.json."""
        if name in self._users:
            return
        if not valid_name(name):
            self.warn("user %r: name cannot be represented, skipped" % name)
            return
        self._users.add(name)
        self.counts["users"] += 1
        os.makedirs(self._user_dir(name), exist_ok=True)
        info = {"display_name": display_name, "email": email, "digest_ha1": digest_ha1}
        info = {k: v for k, v in info.items() if v}
        if info:
            self._json(os.path.join("users", pct(name), "user.json"), info)

    def collection(self, user, kind, slug, **meta):
        """Start a collection and return it, or None if it cannot be created.

        meta keys are those of collection.json; empty values are omitted. The
        slug is rewritten if the importer would reject it.
        """
        if user not in self._users:
            self.warn("%s %r: unknown user %r, skipped" % (kind, slug, user))
            return None
        fixed = slug
        if not _SLUG_OK.match(fixed) or fixed in _RESERVED:
            fixed = _SLUG_BAD.sub("_", fixed)[:128].lstrip(".") or "unnamed"
            if fixed in _RESERVED:
                fixed += "-" + kind
        base, n = fixed, 1
        while (user, kind, fixed) in self._slugs:
            n += 1
            fixed = "%s-%d" % (base[:120], n)
        if fixed != slug:
            self.warn("%s %r of user %r renamed to %r" % (kind, slug, user, fixed))
        self._slugs.add((user, kind, fixed))
        self.counts[_DIRS[kind]] += 1
        rel = os.path.join("users", pct(user), _DIRS[kind], pct(fixed))
        os.makedirs(os.path.join(self.root, rel, "objects"), exist_ok=True)
        meta = {k: v for k, v in meta.items() if v not in (None, "", False)}
        return Collection(self, rel, "%s/%s" % (user, slug), meta)


class Collection:
    def __init__(self, tree, rel, label, meta):
        self.tree, self.rel, self.label, self.meta = tree, rel, label, meta
        self.etags = {}

    def add(self, uri, data, etag=""):
        """Store one object. `etag` is the source server's, if still valid."""
        if not valid_name(uri):
            self.tree.warn("%s/%r: name cannot be represented, skipped" % (self.label, uri))
            return
        path = os.path.join(self.tree.root, self.rel, "objects", pct(uri))
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError as e:
            self.tree.warn("%s/%r: %s, skipped" % (self.label, uri, e))
            return
        self.tree.counts["objects"] += 1
        etag = (etag or "").strip().strip('"')
        if etag:
            self.etags[uri] = etag

    def close(self):
        meta = dict(self.meta)
        if self.etags:
            meta["etags"] = self.etags
        if meta:
            self.tree._json(os.path.join(self.rel, "collection.json"), meta)


def pct(name):
    """Percent-encode one path segment as the format requires."""
    return quote(name, safe="")


def valid_name(name):
    b = name.encode("utf-8", "surrogatepass") if name else b""
    return 0 < len(b) <= 255 and "/" not in name and "\0" not in name and name not in (".", "..")


# --- text clean-up -----------------------------------------------------------

_CP1252_HIGH = ("€\x81‚ƒ„…†‡ˆ‰Š‹Œ\x8dŽ\x8f"
                "\x90‘’“”•–—˜™š›œ\x9džŸ")


def from_cp1252(b):
    return "".join(chr(c) if c < 0x80 or c >= 0xA0 else _CP1252_HIGH[c - 0x80] for c in b)


def to_utf8(b):
    """Valid UTF-8 is kept as is (even if a legacy charset is declared);
    anything else is taken to be Windows-1252."""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return from_cp1252(b)


def fix_object(kind, data):
    """Return (bytes, changed) with `data` as the importer requires: UTF-8,
    and for vCards no quoted-printable or legacy-charset lines."""
    if kind == ADDRESSBOOK:
        return normalize_vcard(data)
    try:
        data.decode("utf-8")
        return data, False
    except UnicodeDecodeError:
        return from_cp1252(data).encode("utf-8"), True


def vtimezone(text):
    """The VTIMEZONE component in `text` (which may be a whole VCALENDAR), or ""."""
    m = re.search(r"BEGIN:VTIMEZONE.*?END:VTIMEZONE", text or "", re.S)
    return re.sub(r"\r?\n", "\r\n", m.group(0)) if m else ""


def _unhex(c):
    return "0123456789abcdef".find(chr(c).lower()) if chr(c).isalnum() else -1


def _decode_qp(s):
    """Decode quoted-printable. Encoded ; , \\ stay escaped so they do not
    become separators; malformed escapes are kept."""
    out = bytearray()
    i = 0
    while i < len(s):
        if s[i] == 0x3D and i + 2 < len(s) and _unhex(s[i + 1]) >= 0 and _unhex(s[i + 2]) >= 0:
            c = _unhex(s[i + 1]) << 4 | _unhex(s[i + 2])
            if c in b";,\\":
                out.append(0x5C)
            out.append(c)
            i += 3
            continue
        out.append(s[i])
        i += 1
    return bytes(out)


def _split_line(s):
    """Split b'NAME;PARAMS:value' at the first colon outside double quotes.
    Both parts stay bytes; the structure is ASCII whatever the charset."""
    in_q = False
    for i, ch in enumerate(s):
        if ch == 0x22:
            in_q = not in_q
        elif ch == 0x3A and not in_q:
            return s[:i].decode("latin-1"), s[i + 1:]
    return None


def _params(head):
    """(parts without the QP marker, qp?, charset)"""
    parts, qp, charset = [], False, ""
    for i, p in enumerate(head.split(";")):
        if i > 0:
            u = p.upper()
            if u in ("ENCODING=QUOTED-PRINTABLE", "QUOTED-PRINTABLE"):
                qp = True
                continue
            if u.startswith("CHARSET="):
                charset = p[8:]
        parts.append(p)
    return parts, qp, charset


def _is_qp_start(line):
    sp = _split_line(line)
    return sp is not None and _params(sp[0])[1]


def _unfold(group, qp):
    b = b""
    for i, l in enumerate(group):
        l = l.rstrip(b"\r\n")
        if i > 0:
            if qp and b.endswith(b"="):
                b = b[:-1]
            elif l[:1] in (b" ", b"\t"):
                l = l[1:]
        b += l
    return b


def _is_utf8(b):
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _fix_group(group, qp):
    """Convert one logical content line (with its folded continuation lines)
    if needed; None if it is already fine."""
    raw = b"".join(group)
    eol = "\r\n" if raw.endswith(b"\r\n") else "\n"
    flat = _unfold(group, qp)
    sp = _split_line(flat)
    if sp is None:
        return None if _is_utf8(flat) else from_cp1252(raw)
    head, value = sp
    parts, _, charset = _params(head)
    legacy = charset != "" and charset.lower() != "utf-8"
    if not qp and not legacy and _is_utf8(flat):
        return None
    if qp:
        value = _decode_qp(value)
        if b"\r" in value or b"\n" in value:
            return None  # cannot be represented on one line; keep as is
    parts = ["CHARSET=UTF-8" if i > 0 and p.upper().startswith("CHARSET=") else p
             for i, p in enumerate(parts)]
    return ";".join(parts) + ":" + to_utf8(value) + eol


def normalize_vcard(data):
    """Rewrite vCard content lines that are not clean UTF-8 text (non-UTF-8
    bytes, a legacy CHARSET, quoted-printable) as plain UTF-8; all other bytes
    stay untouched. Returns (data, changed)."""
    lines = re.findall(rb"[^\n]*\n|[^\n]+", data)
    out, fixed, i = [], 0, 0
    while i < len(lines):
        j = i + 1
        qp = _is_qp_start(lines[i])
        while j < len(lines):
            folded = lines[j][:1] in (b" ", b"\t")
            soft = qp and lines[j - 1].rstrip(b"\r\n").endswith(b"=")
            if not folded and not soft:
                break
            j += 1
        group = lines[i:j]
        i = j
        new = _fix_group(group, qp)
        if new is None:
            out.extend(group)
        else:
            out.append(new.encode("utf-8"))
            fixed += 1
    return (b"".join(out), True) if fixed else (data, False)
