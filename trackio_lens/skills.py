"""One discoverable skill entry follows the managed release, never a checkout."""

import hashlib
import json
from pathlib import Path

from .config import private_json, private_path

NAME = "use-trackio-lens"
PACKAGE = Path("skills") / NAME


def source_manifest(source):
    package = Path(source) / PACKAGE
    if package.is_symlink() or package.parent.is_symlink():
        raise ValueError("Skill source cannot contain symlinks")
    if not (package / "SKILL.md").is_file():
        raise ValueError("The release must include the Lens integration skill")
    files = {}
    for path in sorted(package.rglob("*")):
        if path.is_symlink():
            raise ValueError("Skill source cannot contain symlinks")
        if path.is_file():
            files[path.relative_to(package).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return {"name": NAME, "files": files}


def validate_release(release):
    source = Path(release) / "source"
    manifest = json.loads((source / "frontend/dist/lens-build.json").read_text())
    expected = manifest.get("integration_skill")
    if expected is None:
        return None  # Authenticated releases before the skill was introduced.
    if expected != source_manifest(source):
        raise ValueError("Integration skill differs from the release manifest")
    return manifest["source_commit"]


def settings(root):
    path = Path(root) / "skill.json"
    if not path.exists():
        return None
    private_path(path)
    value = json.loads(path.read_text())
    for target in [value["destination"], *value.get("retired", [])]:
        if target is not None and not Path(target).is_absolute():
            raise ValueError("Skill destination must be absolute")
    return value


def link_target(root):
    return Path(root).resolve() / "current/source" / PACKAGE


def check_destination(root, destination):
    if destination is None:
        return
    path = Path(destination)
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"Skill parent is not a directory: {parent}")
    if path.is_symlink():
        if path.readlink() == link_target(root):
            return
    elif not path.exists():
        return
    raise ValueError(f"Refusing to overwrite an unrelated skill: {path}")


def preflight(root):
    value = settings(root)
    if value:
        for target in [value["destination"], *value.get("retired", [])]:
            check_destination(root, target)


def prepare(root, enabled=None, directory=None):
    """Persist an explicit installation preference; publish touches the entry."""
    root = Path(root).resolve()
    previous = settings(root)
    target = (
        previous["destination"]
        if previous
        else str(Path.home() / ".agents/skills" / NAME)
    )
    if directory is not None:
        if enabled is False:
            raise ValueError("--skills-dir cannot be combined with --no-skill")
        target = str(Path(directory).expanduser().absolute() / NAME)
    elif enabled is True and target is None:
        target = str(Path.home() / ".agents/skills" / NAME)
    if enabled is False:
        target = None
    retired = list(previous.get("retired", [])) if previous else []
    if previous and previous["destination"] not in (None, target):
        retired.append(previous["destination"])
    retired = sorted(set(retired) - {target})
    for destination in [target, *retired]:
        check_destination(root, destination)
    private_json(root / "skill.json", {"destination": target, "retired": retired})


def remove_entry(root, destination):
    if destination is not None:
        check_destination(root, destination)
        Path(destination).unlink(missing_ok=True)


def sync(root, release):
    """Reconcile after actual HTTP validation, including legacy recovery."""
    root = Path(root).resolve()
    value = settings(root)
    if value is None:
        return {"installed": False}
    preflight(root)
    commit = validate_release(release)
    target = value["destination"]
    if target is not None and commit is not None:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_symlink():
            # Creation is atomic and refuses a concurrently created entry.
            path.symlink_to(link_target(root), target_is_directory=True)
        if path.resolve() != (Path(release) / "source" / PACKAGE).resolve():
            raise ValueError("Skill entry does not follow the running release")
    else:
        remove_entry(root, target)
    for retired in value.get("retired", []):
        remove_entry(root, retired)
    private_json(root / "skill.json", {"destination": target, "retired": []})
    return {
        "installed": target is not None and commit is not None,
        "source_commit": commit,
    }


def withdraw(root):
    """A first failed activation must not advertise an unverified integration."""
    value = settings(root)
    if value:
        for target in [value["destination"], *value.get("retired", [])]:
            remove_entry(root, target)
