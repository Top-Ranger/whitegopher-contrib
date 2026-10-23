#!/usr/bin/env python3
"""Convert a Radicale collection store to a White Gopher import tree.

    radicale2whitegopher.py /var/lib/radicale/collections OUT_DIR

Reads Radicale's "multifilesystem" storage (collection-root/<user>/<collection>)
as plain files and never writes to it. Radicale keeps no display names, email
addresses or password hashes per user (passwords live in the htpasswd file or
an external authenticator), so users are created without them: set passwords
and email addresses in the White Gopher admin UI afterwards.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
import wgimport as wg  # noqa: E402

_NS = {  # Radicale's short property prefixes
    "C": "urn:ietf:params:xml:ns:caldav",
    "CR": "urn:ietf:params:xml:ns:carddav",
    "D": "DAV:",
    "ICAL": "http://apple.com/ns/ical/",
}
_LONG = {"{%s}" % uri: pre + ":" for pre, uri in _NS.items()}


def read_props(path):
    """The collection's .Radicale.props with keys as 'PREFIX:name'."""
    try:
        with open(os.path.join(path, ".Radicale.props"), encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    props = {}
    for k, v in raw.items():
        for long, short in _LONG.items():
            if k.startswith(long):
                k = short + k[len(long):]
        props[k] = v
    return props


def collection_root(path):
    nested = os.path.join(path, "collection-root")
    return nested if os.path.isdir(nested) else path


def object_names(path):
    return sorted(n for n in os.listdir(path)
                  if not n.startswith(".Radicale.") and os.path.isfile(os.path.join(path, n)))


def guess_kind(names):
    exts = {os.path.splitext(n)[1].lower() for n in names}
    if exts & {".ics", ".ical"}:
        return wg.CALENDAR
    if ".vcf" in exts:
        return wg.ADDRESSBOOK
    return None


def convert(store, out):
    tree = wg.Tree(out, "radicale2whitegopher")
    root = collection_root(store)
    for user in sorted(os.listdir(root)):
        upath = os.path.join(root, user)
        if user.startswith(".") or not os.path.isdir(upath):
            continue
        tree.user(user)
        for slug in sorted(os.listdir(upath)):
            cpath = os.path.join(upath, slug)
            if slug.startswith(".") or not os.path.isdir(cpath):
                continue
            convert_collection(tree, user, slug, cpath)
    return tree


def convert_collection(tree, user, slug, path):
    label = "%s/%s" % (user, slug)
    props = read_props(path)
    names = object_names(path)
    tag = props.get("tag")
    kind = {"VCALENDAR": wg.CALENDAR, "VADDRESSBOOK": wg.ADDRESSBOOK}.get(tag)
    if kind is None:
        if tag:
            tree.warn("%s: collection type %s is not supported, skipped" % (label, tag))
            return
        kind = guess_kind(names)
        if kind is None:
            tree.warn("%s: not a calendar or address book, skipped" % label)
            return
        tree.warn("%s: no collection type recorded, treated as %s" % (label, kind))

    meta = {"display_name": props.get("D:displayname")}
    if kind == wg.CALENDAR:
        order = props.get("ICAL:calendar-order")
        meta.update(
            description=props.get("C:calendar-description"),
            color=props.get("ICAL:calendar-color"),
            sort_order=int(order) if str(order).lstrip("-").isdigit() else 0,
            components=props.get("C:supported-calendar-component-set"),
            timezone=wg.vtimezone(props.get("C:calendar-timezone")),
        )
    else:
        meta["description"] = props.get("CR:addressbook-description")
    coll = tree.collection(user, kind, slug, **meta)
    if coll is None:
        return
    for name in names:
        with open(os.path.join(path, name), "rb") as f:
            data, changed = wg.fix_object(kind, f.read())
        if changed:
            tree.warn("%s/%s: converted to UTF-8" % (label, name))
        coll.add(name, data)
    coll.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("storage", help="Radicale filesystem_folder (or its parent of collection-root)")
    ap.add_argument("out", help="output directory, must be empty or not exist")
    args = ap.parse_args()
    if not os.path.isdir(args.storage):
        sys.exit("error: %s is not a directory" % args.storage)
    tree = convert(args.storage, args.out)
    c = tree.counts
    print("%d users, %d calendars, %d address books, %d objects, %d warnings"
          % (c["users"], c["calendars"], c["addressbooks"], c["objects"], len(tree.warnings)))


if __name__ == "__main__":
    main()
