#!/usr/bin/env python3
"""Plan, install, and optionally publish this skill using explicit local state.

No third-party packages are required. Configuration and synchronization state
are local files, never part of the published or installed payload.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


RUNTIME_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/writing-and-review.md",
    "references/ui-workflow.md",
    "references/color-and-recovery.md",
    "references/learning-loop.md",
    "scripts/sync_skill.py",
)
PUBLIC_FILES = RUNTIME_FILES + (
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "LICENSE",
    ".github/ISSUE_TEMPLATE/problem-solution.yml",
    ".github/pull_request_template.md",
)
OPTIONAL_PUBLIC_FILES = ("tests/test_sync_skill.py",)


class SyncError(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise SyncError(f"Cannot read JSON file {path}: {exc}") from exc


def is_within(path, directory):
    return path == directory or directory in path.parents


def load_config(path):
    config = read_json(path)
    if not isinstance(config, dict):
        raise SyncError("Configuration must be a JSON object")
    for name in ("source", "install", "git_dir", "baseline"):
        value = config.get(name)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise SyncError(f"Configuration {name} must be an absolute path")
        config[name] = Path(value).resolve()
    source, install = config["source"], config["install"]
    if not source.is_dir():
        raise SyncError("Source skill directory does not exist")
    if is_within(source, install) or is_within(install, source):
        raise SyncError("Source and installation must be separate directories")
    for name in ("baseline", "git_dir"):
        if any(is_within(config[name], root) for root in (source, install)):
            raise SyncError(f"{name} must be outside the source and installation")
    if not isinstance(config.get("repo_url"), str) or not config["repo_url"].strip():
        raise SyncError("Configuration repo_url is required; there is no default repository")
    if not isinstance(config.get("branch"), str) or not config["branch"].strip():
        raise SyncError("Configuration branch is required")
    if "git_proxy" in config:
        proxy = config["git_proxy"]
        try:
            if not isinstance(proxy, str) or any(character.isspace() for character in proxy):
                raise ValueError
            parsed = urlsplit(proxy)
            if (
                parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
            ):
                raise ValueError
            parsed.port  # Validate the optional port without supplying a default.
        except ValueError as exc:
            raise SyncError("git_proxy must be an HTTP(S) URL without username or password") from exc
    return config


def load_baseline(path):
    state = read_json(path)
    if not isinstance(state, dict) or state.get("version") != 1:
        raise SyncError("Baseline must be an existing version 1 JSON object")
    if not isinstance(state.get("install"), dict):
        raise SyncError("Baseline install must contain explicitly verified file hashes")
    for value in state["install"].values():
        if value is not None and not (
            isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value)
        ):
            raise SyncError("Installation baseline values must be SHA-256 strings or null")
    state["install"] = {
        key: value.lower() if isinstance(value, str) else None
        for key, value in state["install"].items()
    }
    return state


def managed_path(root, relative):
    path = root / relative
    if not is_within(path.resolve(), root):
        raise SyncError(f"Managed file resolves outside its directory: {relative}")
    cursor = path
    while cursor != root:
        if cursor.is_symlink():
            raise SyncError(f"Symbolic links are not synchronized: {relative}")
        cursor = cursor.parent
    return path


def read_payload(source):
    payload = {}
    for relative in PUBLIC_FILES + OPTIONAL_PUBLIC_FILES:
        path = managed_path(source, relative)
        if not path.is_file():
            if relative in OPTIONAL_PUBLIC_FILES and not path.exists():
                continue
            raise SyncError(f"Required skill file is missing or not a file: {relative}")
        payload[relative] = path.read_bytes()
    return payload


def installation_plan(config, state, payload):
    files, conflicts = [], []
    for relative in RUNTIME_FILES:
        path = managed_path(config["install"], relative)
        if path.exists() and not path.is_file():
            raise SyncError(f"Installation target is not a regular file: {relative}")
        target_hash = digest(path.read_bytes()) if path.exists() else None
        source_hash = digest(payload[relative])
        if relative not in state["install"]:
            action = "conflict"
            reason = "No verified installation baseline; initialize this entry explicitly"
        elif target_hash != state["install"][relative] and target_hash != source_hash:
            action = "conflict"
            reason = "Installation changed since the baseline; merge it before syncing"
        else:
            action = "unchanged" if target_hash == source_hash else "copy"
            reason = None
        item = {
            "path": relative,
            "action": action,
            "source_sha256": source_hash,
            "install_sha256": target_hash,
        }
        if reason:
            item["reason"] = reason
            conflicts.append(relative)
        files.append(item)
    return files, conflicts


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=path.name + ".", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def save_baseline(path, state):
    atomic_write(path, (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def ensure_source_unchanged(source, payload):
    if read_payload(source) != payload:
        raise SyncError("Source files changed during synchronization; run the plan again")


def apply_installation(config, state, payload, plan):
    ensure_source_unchanged(config["source"], payload)
    current_plan, conflicts = installation_plan(config, state, payload)
    if conflicts or current_plan != plan:
        raise SyncError("Installation changed after preflight; no files were copied")
    for item in plan:
        if item["action"] == "copy":
            atomic_write(managed_path(config["install"], item["path"]), payload[item["path"]])
    for relative in RUNTIME_FILES:
        if managed_path(config["install"], relative).read_bytes() != payload[relative]:
            raise SyncError(f"Installation read-back failed: {relative}")
    ensure_source_unchanged(config["source"], payload)
    state["install"].update({relative: digest(payload[relative]) for relative in RUNTIME_FILES})
    save_baseline(config["baseline"], state)


def git(config, *arguments, data=None):
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    command = ["git", "--git-dir=" + str(config["git_dir"])]
    if "git_proxy" in config:
        command.extend(["-c", "http.proxy=" + config["git_proxy"]])
    result = subprocess.run(
        [*command, *arguments],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise SyncError(f"Git command failed ({arguments[0]}): {detail}")
    return result.stdout


def remote_preflight(config, state):
    if config.get("authorized_publish") is not True:
        raise SyncError("Publishing requires authorized_publish: true in this repository's local config")
    expected = state.get("remote_commit")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", expected):
        raise SyncError("A previously verified remote_commit baseline is required for publishing")
    if git(config, "rev-parse", "--is-bare-repository").strip() != b"true":
        raise SyncError("Publishing requires independent bare Git metadata")
    git(config, "check-ref-format", "--branch", config["branch"])
    git(config, "fetch", "--no-tags", config["repo_url"], "refs/heads/" + config["branch"])
    current = git(config, "rev-parse", "FETCH_HEAD").decode().strip()
    if current.lower() != expected.lower():
        raise SyncError("Remote branch differs from the verified baseline; review and merge before publishing")
    names = git(config, "ls-tree", "-r", "--name-only", "-z", current).decode("utf-8").split("\0")
    unexpected = set(filter(None, names)) - set(PUBLIC_FILES + OPTIONAL_PUBLIC_FILES)
    if unexpected:
        raise SyncError("Remote tree contains files outside the skill whitelist; review before publishing")
    return current


def create_public_tree(config, payload):
    directories = {}
    for relative, data in payload.items():
        node = directories
        parts = relative.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = git(config, "hash-object", "-w", "--stdin", data=data).decode().strip()

    def write_tree(node):
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode, kind, object_id = "040000", "tree", write_tree(value)
            else:
                mode, kind, object_id = "100644", "blob", value
            entries.append(f"{mode} {kind} {object_id}\t{name}\0".encode("utf-8"))
        return git(config, "mktree", "-z", data=b"".join(entries)).decode().strip()

    return write_tree(directories)


def publish(config, state, payload, parent):
    ensure_source_unchanged(config["source"], payload)
    tree = create_public_tree(config, payload)
    previous_tree = git(config, "rev-parse", parent + "^{tree}").decode().strip()
    commit = parent
    if tree != previous_tree:
        commit = git(
            config, "-c", "user.name=Skill Sync", "-c", "user.email=skill-sync@example.invalid",
            "commit-tree", tree, "-p", parent, "-m", "Sync reusable skill files",
        ).decode().strip()
        git(config, "push", config["repo_url"], commit + ":refs/heads/" + config["branch"])
    remote = git(config, "ls-remote", config["repo_url"], "refs/heads/" + config["branch"]).split()
    if not remote or remote[0].decode() != commit:
        raise SyncError("Remote read-back differs after publishing; verify the remote before retrying")
    for relative, data in payload.items():
        if git(config, "show", commit + ":" + relative) != data:
            raise SyncError(f"Published file read-back failed: {relative}")
    git(config, "update-ref", "refs/heads/" + config["branch"], commit)
    state["remote_commit"] = commit
    save_baseline(config["baseline"], state)
    return commit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path,
        default=Path(__file__).resolve().parents[1] / ".sync.local.json",
        help="External/local JSON config; defaults to the executing skill's .sync.local.json",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", "--plan", dest="check", action="store_true", help="Read-only plan (default)")
    mode.add_argument("--apply", action="store_true", help="Synchronize verified runtime files locally")
    mode.add_argument("--push", action="store_true", help="Check remote baseline, install locally, then publish")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config.resolve())
        state = load_baseline(config["baseline"])
        payload = read_payload(config["source"])
        plan, conflicts = installation_plan(config, state, payload)
        result = {
            "mode": "push" if args.push else "apply" if args.apply else "check",
            "files": plan,
            "public_files": sorted(payload),
            "conflicts": conflicts,
        }
        if conflicts:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        parent = remote_preflight(config, state) if args.push else None
        if args.apply or args.push:
            apply_installation(config, state, payload, plan)
            result["installation_verified"] = True
        if args.push:
            result["published_commit"] = publish(config, state, payload, parent)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (SyncError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
