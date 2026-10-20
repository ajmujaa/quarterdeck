"""Several accounts of one service (two Gmail accounts, a work Slack and a personal one).

An account is named by a label: lowercase letters, digits and dashes, at most 24, starting with a letter or digit. The label `default` is the
account every install already has; nothing about it changes, so an install written by an older version needs no migration.

  credential key   KEY for the default account, KEY@label for another (the name in the private file and the Keychain account name)
  snapshots        state/connectors/<service>/<label>/<snapshot>.json   (the default account also keeps state/connectors/<snapshot>.json)
  status records   <snapshot> for the default account, <snapshot>@<label> for another
  config           sources.<service> is the default account; sources.<service>.accounts.<label> = {"enabled": bool} are the others
  work items       "gmail" is the default account, "gmail@work" another (the loop, the runner, the log)

This module has no imports from the rest of the package so every part can use it.
"""
import re

DEFAULT = "default"
LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
BAD_LABEL = "an account label is lowercase letters, digits and dashes, at most 24"


def valid(label):
    return isinstance(label, str) and bool(LABEL.match(label))


def norm(label):
    """None or "" is the default account; anything else must be a valid label."""
    if label is None or label == "":
        return DEFAULT
    if not valid(label):
        raise ValueError(BAD_LABEL)
    return label


def cred_key(key, label=DEFAULT):
    return key if norm(label) == DEFAULT else f"{key}@{label}"


def split_key(stored):
    """("KEY", label) for a stored name: KEY -> ("KEY", "default"), KEY@work -> ("KEY", "work"). A name with a bad label gives (stored, None)."""
    base, sep, label = stored.partition("@")
    if not sep:
        return base, DEFAULT
    return (base, label) if valid(label) and label != DEFAULT else (stored, None)


def status_key(snapshot, label=DEFAULT):
    return snapshot if norm(label) == DEFAULT else f"{snapshot}@{label}"


def work_item(service, label=DEFAULT):
    return service if norm(label) == DEFAULT else f"{service}@{label}"


def split_item(item):
    """"gmail@work" -> ("gmail", "work"); "gmail" -> ("gmail", "default"). A bad label is a ValueError."""
    name, sep, label = str(item).partition("@")
    return name, (norm(label) if sep else DEFAULT)


def labels_of(cfg_source):
    """The extra labels in one sources.<service> entry, sorted. Bad ones are ignored."""
    acc = (cfg_source or {}).get("accounts")
    return sorted(l for l in acc if valid(l) and l != DEFAULT and isinstance(acc[l], dict)) if isinstance(acc, dict) else []


def snapshot_dir(state, service, label=DEFAULT):
    return state / "connectors" / service / norm(label)


def snapshot_file(state, service, snapshot, label=DEFAULT):
    return snapshot_dir(state, service, label) / f"{snapshot}.json"


def legacy_file(state, snapshot):
    return state / "connectors" / f"{snapshot}.json"
