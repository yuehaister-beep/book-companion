#!/usr/bin/env python3
"""Local, explicit-book state transitions. No network and no third-party packages."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

STATE = ".book-companion.json"
SCHEMA = 1
PLAN_KEYS = {"motivation", "problem", "audience", "reader_change", "thesis",
             "contribution", "progression", "evidence_plan", "learning_gaps",
             "boundaries", "inspirations"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def fingerprint(state):
    return digest({k: v for k, v in state.items() if k != "candidates"})


def text(value, field):
    require(isinstance(value, str) and bool(value.strip()), field + " must be nonempty text")
    return value


def exact(obj, keys):
    require(isinstance(obj, dict) and set(obj) == set(keys), "invalid fields; expected " + str(sorted(keys)))


def chapter_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value),
            "chapter id must contain only lowercase letters, digits and hyphens")


def load(root):
    path = root / STATE
    require(not path.is_symlink(), "refusing symlink state file")
    state = json.loads(path.read_text(encoding="utf-8"))
    require(state.get("schema") == SCHEMA, "unsupported schema; no automatic migration")
    require(isinstance(state.get("book_id"), str) and isinstance(state.get("revision"), int), "invalid state")
    return state


def write(root, state):
    require(not (root / STATE).is_symlink(), "refusing symlink state file")
    fd, path = tempfile.mkstemp(prefix=".book-state-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(path, root / STATE)
    finally:
        if os.path.exists(path):
            os.unlink(path)


@contextmanager
def locked(root):
    lock = root / ".book-companion.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise ValueError("project locked; stop and inspect the other writer (never auto-remove a lock)")
    try:
        yield
    finally:
        lock.rmdir()


def initialize(root, title):
    text(title, "title")
    require(not root.exists(), "init requires a new directory; existing files are never replaced")
    root.mkdir(parents=True, mode=0o700)
    state = {"schema": SCHEMA, "book_id": str(uuid4()), "revision": 0,
             "title": title, "author": "", "assistant_name": "", "mode": "unspecified",
             "plan": {}, "outline": [], "chapters": {}, "memory": [],
             "candidates": {}, "events": [], "created_at": now(), "visibility": "private"}
    write(root, state)
    return state


def outline_signature(state):
    return digest({"plan": state["plan"], "outline": state["outline"]})


def current_hash(state, cid):
    chapter = state["chapters"].get(cid)
    return digest(chapter["versions"][-1]) if chapter else None


def validate_change(state, change):
    exact(change, {"action", "data"})
    action, data = change["action"], change["data"]
    if action == "settings":
        require(isinstance(data, dict) and data and set(data) <= {"title", "author", "assistant_name", "mode"},
                "invalid settings")
        for key, value in data.items():
            text(value, key)
        if "mode" in data:
            require(data["mode"] in {"direct", "learn", "unspecified"}, "invalid mode")
    elif action == "plan":
        require(isinstance(data, dict) and data and set(data) <= PLAN_KEYS, "invalid plan fields")
        for item in data.values():
            exact(item, {"value", "status", "evidence"})
            text(item["value"], "plan value")
            text(item["evidence"], "plan evidence")
            require(item["status"] in {"proposed", "confirmed", "needs_review"}, "invalid plan status")
    elif action == "outline":
        require(isinstance(data, list) and data, "outline must be a nonempty ordered list")
        for item in data:
            exact(item, {"id", "title", "role"})
            chapter_id(item["id"])
            text(item["title"], "chapter title")
            text(item["role"], "chapter role")
        ids = [item["id"] for item in data]
        require(len(ids) == len(set(ids)), "duplicate chapter id")
        require({item["id"] for item in state["outline"]} <= set(ids),
                "v0.1 supports add/reorder/rename, not deleting existing outline nodes")
    elif action == "chapter":
        exact(data, {"chapter_id", "content_type", "text", "stage", "sources", "change_note"})
        cid = data["chapter_id"]
        chapter_id(cid)
        require(cid in {item["id"] for item in state["outline"]}, "chapter not in this book outline")
        require(data["content_type"] == "manuscript", "discussion or analysis is not manuscript")
        text(data["text"], "manuscript")
        text(data["change_note"], "change_note")
        require(data["stage"] in {"draft", "reviewed"}, "a candidate cannot be final")
        require(isinstance(data["sources"], list) and all(isinstance(s, str) and s.strip() for s in data["sources"]),
                "sources must be a list of actual source references (may be empty for original fiction)")
        prior = state["chapters"].get(cid)
        if not prior or prior["stage"] == "final":
            require(data["stage"] == "draft", "first import and post-final revision must start as draft")
    elif action == "finalize":
        exact(data, {"chapter_id", "chapter_hash"})
        chapter_id(data["chapter_id"])
        require(data["chapter_id"] in state["chapters"], "no manuscript to finalize")
        require(data["chapter_hash"] == current_hash(state, data["chapter_id"]), "chapter changed")
        require(state["chapters"][data["chapter_id"]]["stage"] != "final", "already final")
    else:
        raise ValueError("unsupported action")


def propose(state, request):
    exact(request, {"book_id", "base_revision", "change"})
    require(request["book_id"] == state["book_id"], "wrong book_id")
    require(type(request["base_revision"]) is int and request["base_revision"] == state["revision"], "stale revision")
    validate_change(state, request["change"])
    cid = "candidate-" + uuid4().hex
    candidate = {**copy.deepcopy(request), "id": cid, "base_hash": fingerprint(state),
                 "status": "pending", "created_at": now()}
    state["candidates"][cid] = candidate
    return candidate


def accept(state, cid, confirmation):
    text(confirmation, "author confirmation quote")
    require(confirmation.strip().lower().rstrip("。.!！") not in {"好的", "好", "继续", "ok", "yes", "嗯"},
            "ambiguous confirmation: obtain a specific author instruction for this book/candidate/version")
    require(cid in state["candidates"], "candidate not found in this book")
    candidate = state["candidates"][cid]
    if candidate["status"] == "accepted":
        return {"already_accepted": True, "revision": candidate["accepted_revision"]}
    require(candidate["status"] == "pending", "candidate not pending")
    require(candidate["book_id"] == state["book_id"], "wrong book_id")
    require(candidate["base_revision"] == state["revision"] and candidate["base_hash"] == fingerprint(state),
            "stale candidate: show differences and obtain approval of a new candidate")
    change = candidate["change"]
    validate_change(state, change)
    action, data = change["action"], copy.deepcopy(change["data"])
    before = fingerprint(state)
    if action == "settings":
        state.update(data)
    elif action == "plan":
        state["plan"].update(data)
    elif action == "outline":
        state["outline"] = data
    elif action == "chapter":
        chapter = state["chapters"].setdefault(data["chapter_id"], {"versions": [], "finals": [], "stage": "draft"})
        title = next(x["title"] for x in state["outline"] if x["id"] == data["chapter_id"])
        chapter["versions"].append({**data, "title": title, "version": len(chapter["versions"]) + 1,
                                    "created_at": now(), "origin_final": len(chapter["finals"]) or None})
        chapter["stage"] = data["stage"]
    elif action == "finalize":
        chapter = state["chapters"][data["chapter_id"]]
        chapter["finals"].append({"version": copy.deepcopy(chapter["versions"][-1]),
                                  "outline_title": next(x["title"] for x in state["outline"] if x["id"] == data["chapter_id"]),
                                  "plan_signature": outline_signature(state), "confirmed_at": now(),
                                  "author_confirmation": confirmation})
        chapter["stage"] = "final"
    state["revision"] += 1
    candidate["status"] = "accepted"
    candidate["accepted_revision"] = state["revision"]
    state["events"].append({"revision": state["revision"], "candidate_id": cid,
                            "change": copy.deepcopy(change), "author_confirmation": confirmation,
                            "before_hash": before, "created_at": now()})
    return {"accepted": cid, "revision": state["revision"], "visibility": "private"}


def record_memory(state, request):
    exact(request, {"book_id", "base_revision", "note"})
    require(request["book_id"] == state["book_id"], "wrong book_id")
    require(type(request["base_revision"]) is int and request["base_revision"] == state["revision"], "stale revision")
    require(isinstance(request["note"], dict) and request["note"], "note must be an object")
    state["memory"].append({"kind": "working_memory_not_author_approval", "note": copy.deepcopy(request["note"]),
                             "created_at": now(), "at_revision": state["revision"]})
    state["revision"] += 1
    return {"memory_saved": True, "revision": state["revision"]}


def status(state):
    return {"book_id": state["book_id"], "revision": state["revision"], "title": state["title"],
            "author": state["author"], "assistant_name": state["assistant_name"], "mode": state["mode"],
            "visibility": state["visibility"], "plan": state["plan"], "plan_signature": outline_signature(state),
            "outline": [{**node, "stage": state["chapters"].get(node["id"], {}).get("stage", "unwritten"),
                         "chapter_hash": current_hash(state, node["id"])} for node in state["outline"]],
            "recent_memory": state["memory"][-5:], "older_memory_count": max(0, len(state["memory"]) - 5),
            "candidates": [{"id": c["id"], "action": c["change"]["action"],
                            "status": c["status"], "stale": c["status"] == "pending" and c["base_hash"] != fingerprint(state)}
                           for c in state["candidates"].values() if c["status"] == "pending"]}


def export_markdown(state, finals=False):
    lines = ["# " + state["title"], "", state["author"] or "（署名未确认）", ""]
    for node in state["outline"]:
        chapter = state["chapters"].get(node["id"])
        if finals:
            if not chapter or not chapter["finals"]:
                continue
            saved = chapter["finals"][-1]
            title, body = saved["outline_title"], saved["version"]["text"]
        else:
            title = node["title"]
            body = chapter["versions"][-1]["text"] if chapter else "（待写）"
        lines.extend(["## " + title, "", body, ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "status", "show", "propose", "accept", "note", "export"])
    parser.add_argument("--book", required=True, type=Path)
    parser.add_argument("--title")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--candidate")
    parser.add_argument("--chapter")
    parser.add_argument("--confirmation")
    parser.add_argument("--section", choices=["memory", "events"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--finals", action="store_true")
    args = parser.parse_args()
    try:
        root = args.book.expanduser().absolute()
        require(not root.is_symlink(), "use an explicit real project directory")
        if args.command == "init":
            result = status(initialize(root, args.title))
        elif args.command in {"propose", "accept", "note"}:
            with locked(root):
                state = load(root)
                if args.command == "accept":
                    result = accept(state, args.candidate, args.confirmation)
                else:
                    require(args.input is not None, "--input JSON file required")
                    request = json.loads(args.input.read_text(encoding="utf-8"))
                    result = propose(state, request) if args.command == "propose" else record_memory(state, request)
                write(root, state)
        else:
            state = load(root)
            if args.command == "status":
                result = status(state)
            elif args.command == "show":
                require(sum(bool(x) for x in [args.candidate, args.chapter, args.section]) == 1,
                        "choose exactly one --candidate, --chapter or --section")
                if args.candidate:
                    result = state["candidates"][args.candidate]
                elif args.chapter:
                    result = state["chapters"][args.chapter]
                else:
                    result = state[args.section]
            else:
                require(args.output is not None, "--output required; export never overwrites")
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(export_markdown(state, args.finals))
                result = {"exported": str(args.output.absolute()), "final_snapshots_only": args.finals}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
