import logging
from utils.migration.constants import ModelKeys

logger = logging.getLogger(__name__)

DEFAULT_POLICIES = {
    "user": "skip",
    "message": "skip_duplicates",
    "group": "skip",
    "group_member": "import_all",
    "group_invite": "import_all",
    "group_join_request": "import_all",
    "system_broadcast": "skip_duplicates",
    "media": "skip_files",
}

ENTITY_DEPENDENCIES = {
    "group": ["user"],
    "group_member": ["user", "group"],
    "group_invite": ["user", "group"],
    "group_join_request": ["user", "group"],
    "message": ["user"],
    "system_broadcast": [],
}


class ConflictReport:
    def __init__(self):
        self.entities = {}

    def add_entity(self, name, total_in_source, conflicts, details=None):
        self.entities[name] = {
            "total_in_source": total_in_source,
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
            "details": details or {},
        }

    def to_dict(self):
        return {"entities": self.entities}

    def has_conflicts(self):
        return any(e["conflict_count"] > 0 for e in self.entities.values())


class PreviewReport:
    def __init__(self):
        self.entities = {}

    def add_entity(self, name, existing, incoming, will_import, will_skip, will_merge=0, will_rename=0, will_replace=0):
        self.entities[name] = {
            "existing": existing,
            "incoming": incoming,
            "will_import": will_import,
            "will_skip": will_skip,
            "will_merge": will_merge,
            "will_rename": will_rename,
            "will_replace": will_replace,
        }

    def to_dict(self):
        return {"entities": self.entities}


def detect_conflicts(source_conn, target_session, target_models, enabled_entities=None):
    report = ConflictReport()

    if enabled_entities is None:
        enabled_entities = {k: True for k in DEFAULT_POLICIES}

    if enabled_entities.get("user"):
        _detect_user_conflicts(source_conn, target_session, target_models, report)

    if enabled_entities.get("message"):
        _detect_message_conflicts(source_conn, target_session, target_models, report)

    if enabled_entities.get("group"):
        _detect_group_conflicts(source_conn, target_session, target_models, report)

    return report


def _detect_user_conflicts(source_conn, target_session, target_models, report):
    User = target_models[ModelKeys.USER]
    existing_usernames = {u.username.lower() for u in User.query.with_entities(User.username).all()}

    source_usernames = _get_source_usernames(source_conn)
    conflicts = [u for u in source_usernames if u.lower() in existing_usernames]

    report.add_entity("user", len(source_usernames), conflicts, {"existing_usernames": sorted(existing_usernames)})


def _detect_message_conflicts(source_conn, target_session, target_models, report):
    Message = target_models[ModelKeys.MESSAGE]
    existing_msg_ids = {m.msg_id for m in Message.query.with_entities(Message.msg_id).all()}

    source_msg_ids = _get_source_msg_ids(source_conn)
    conflicts = [m for m in source_msg_ids if m in existing_msg_ids]

    report.add_entity("message", len(source_msg_ids), conflicts)


def _detect_group_conflicts(source_conn, target_session, target_models, report):
    Group = target_models[ModelKeys.GROUP]
    existing_names = {g.name.lower() for g in Group.query.with_entities(Group.name).all()}

    source_names = _get_source_group_names(source_conn)
    conflicts = [n for n in source_names if n.lower() in existing_names]

    report.add_entity("group", len(source_names), conflicts, {"existing_names": sorted(existing_names)})


def _get_source_usernames(conn):
    try:
        table = "messages" if _table_exists(conn, "messages") else "message"
        cur = conn.execute(f"SELECT DISTINCT sender FROM `{table}` WHERE sender NOT NULL")
        senders = {row[0] for row in cur.fetchall() if row[0]}
        cur = conn.execute(f"SELECT DISTINCT recipient FROM `{table}` WHERE recipient NOT NULL")
        recipients = {row[0] for row in cur.fetchall() if row[0]}
        excluded = {"server", "all", "Server", "All"}
        return sorted((senders | recipients) - excluded)
    except Exception as e:
        logger.warning("Could not extract source usernames: %s", e)
        return []


def _get_source_msg_ids(conn):
    try:
        table = "messages" if _table_exists(conn, "messages") else "message"
        cur = conn.execute(f"SELECT msg_id FROM `{table}` WHERE msg_id NOT NULL")
        return [row[0] for row in cur.fetchall() if row[0]]
    except Exception as e:
        logger.warning("Could not extract source msg_ids: %s", e)
        return []


def _get_source_group_names(conn):
    try:
        cur = conn.execute("SELECT DISTINCT name FROM `group` WHERE name NOT NULL")
        return [row[0] for row in cur.fetchall() if row[0]]
    except Exception as e:
        return []


def _table_exists(conn, name):
    cur = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone()[0] > 0


def generate_preview(source_conn, target_session, target_models, config):
    report = PreviewReport()
    enabled = config.get("enabled", {k: True for k in DEFAULT_POLICIES})
    policies = config.get("policies", DEFAULT_POLICIES)

    User = target_models.get(ModelKeys.USER)
    Message = target_models.get(ModelKeys.MESSAGE)
    Group = target_models.get(ModelKeys.GROUP)

    existing_users = User.query.count() if User else 0
    incoming_users = len(_get_source_usernames(source_conn))
    existing_usernames = {u.username.lower() for u in User.query.with_entities(User.username).all()} if User else set()

    will_import = 0
    will_skip = 0
    will_rename = 0
    for u in _get_source_usernames(source_conn):
        if u.lower() in existing_usernames:
            if policies.get("user") == "skip":
                will_skip += 1
            elif policies.get("user") == "rename":
                will_rename += 1
            elif policies.get("user") == "replace":
                will_import += 1
        else:
            will_import += 1

    report.add_entity("user", existing_users, incoming_users, will_import, will_skip, will_rename=will_rename)

    if enabled.get("message") and Message:
        existing_msgs = Message.query.count()
        incoming_msgs = len(_get_source_msg_ids(source_conn))
        existing_ids = {m.msg_id for m in Message.query.with_entities(Message.msg_id).all()}
        will_skip_m = sum(1 for m in _get_source_msg_ids(source_conn) if m in existing_ids)
        will_import_m = incoming_msgs - will_skip_m
        report.add_entity("message", existing_msgs, incoming_msgs, will_import_m, will_skip_m)

    if enabled.get("group") and Group:
        existing_groups = Group.query.count()
        incoming_groups = len(_get_source_group_names(source_conn))
        existing_names = {g.name.lower() for g in Group.query.with_entities(Group.name).all()}
        will_skip_g = sum(1 for n in _get_source_group_names(source_conn) if n.lower() in existing_names)
        will_import_g = incoming_groups - will_skip_g
        report.add_entity("group", existing_groups, incoming_groups, will_import_g, will_skip_g)

    return report


def apply_resolutions(records, entity_type, policy, resolutions=None):
    if resolutions is None:
        resolutions = {}

    transformed = []

    for record in records:
        if entity_type == "user":
            result = _resolve_user(record, policy, resolutions)
        elif entity_type == "message":
            result = _resolve_message(record, policy, resolutions)
        elif entity_type == "group":
            result = _resolve_group(record, policy, resolutions)
        else:
            result = ("import", record)

        if result is not None:
            transformed.append(result)

    return transformed


def _resolve_user(record, policy, resolutions):
    username = record.get("username", "")
    existing = resolutions.get("existing_usernames", set())
    has_conflict = username.lower() in {n.lower() for n in existing}

    if not has_conflict:
        return ("import", record)

    override = resolutions.get("overrides", {}).get(username)
    action = override or policy

    if action == "skip":
        return ("skip", record)
    elif action == "replace":
        return ("replace", record)
    elif action == "rename":
        new_name = _generate_rename(username, existing)
        record["username"] = new_name
        return ("import", record)
    else:
        return ("import", record)


def _resolve_message(record, policy, resolutions):
    msg_id = record.get("msg_id", "")
    existing = resolutions.get("existing_msg_ids", set())
    has_conflict = msg_id in existing

    if not has_conflict:
        return ("import", record)

    if policy == "skip_duplicates":
        return ("skip", record)
    elif policy == "replace":
        return ("replace", record)
    else:
        return ("import", record)


def _resolve_group(record, policy, resolutions):
    name = record.get("name", "")
    existing = resolutions.get("existing_names", set())
    has_conflict = name.lower() in {n.lower() for n in existing}

    if not has_conflict:
        return ("import", record)

    if policy == "skip":
        return ("skip", record)
    elif policy == "rename":
        record["name"] = f"{name} (imported)"
        return ("import", record)
    elif policy == "merge":
        return ("skip", record)
    else:
        return ("import", record)


def _generate_rename(username, existing_set):
    candidate = f"{username}_imported"
    if candidate.lower() not in {n.lower() for n in existing_set}:
        return candidate
    counter = 2
    while f"{username}_{counter}" in existing_set:
        counter += 1
    return f"{username}_{counter}"
