"""Club ownership and selection evidence shared by the Rangers integration."""

def club_uid(value):
    value = str(value if value is not None else "").strip()
    # fmsave club UIDs are save-local nonnegative integers; zero is valid.
    return str(int(value)) if value.isascii() and value.isdecimal() else None


def is_rangers(name):
    return " ".join(str(name or "").casefold().split()) in {
        "rangers", "rangers fc", "rangers f.c.", "rangers football club"
    }


def rangers_names(*names):
    supplied = [name for name in names if str(name or "").strip()]
    return bool(supplied) and all(is_rangers(name) for name in supplied)


def rangers_ids(records):
    """Legacy evidence from current and contractual club names and UIDs."""
    result = set()
    for row in records:
        for name, uid in (("club_name", "club_uid"), ("loan_parent_club_name", "loan_parent_club_uid")):
            if is_rangers(row.get(name)) and club_uid(row.get(uid)):
                result.add(club_uid(row[uid]))
    return result


def loan_state(row, managed_uid):
    """Return a loan classification and club-level selection availability."""
    current = club_uid(row.get("club_uid"))
    parent = club_uid(row.get("loan_parent_club_uid"))
    flag = str(row.get("on_loan", "")).strip().lower()
    if not managed_uid or not current:
        return "unknown", "unknown"
    parent_value = row.get("loan_parent_club_uid")
    if flag == "false" and (parent_value is None or str(parent_value).strip() == "") and current == managed_uid:
        return "permanent", "available"
    if flag == "true" and parent and current != parent:
        if current == managed_uid:
            return "incoming", "available"
        if parent == managed_uid:
            return "outgoing", "unavailable"
    return "unknown", "unknown"
