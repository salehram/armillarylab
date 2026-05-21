"""
Transfer Cursor chat history from old workspace to new workspace.

Run AFTER opening the new project location in Cursor:
    python scripts/fix_cursor_workspace.py

How it works:
    1. Detects the current project path (where this script lives)
    2. Finds the OLD workspace folder (OneDrive path)
    3. Finds or creates the NEW workspace folder (current path)
    4. Copies agent-transcripts, canvases, assets, uploads, mcps
"""
import shutil
import sys
from pathlib import Path

CURSOR_PROJECTS = Path.home() / ".cursor" / "projects"

OLD_WORKSPACE = "c-Users-SalehRam-OneDrive-Desktop-Python-astroplanner"

FOLDERS_TO_COPY = [
    "agent-transcripts",
    "canvases",
    "assets",
    "uploads",
    "mcps",
    "agent-tools",
]


def path_to_workspace_name(project_path: Path) -> list[str]:
    """Generate possible workspace folder names from a project path."""
    resolved = project_path.resolve()
    raw = str(resolved).replace(":\\", "-").replace("\\", "-").replace("/", "-")
    candidates = [
        raw,
        raw[0].lower() + raw[1:],
        raw[0].upper() + raw[1:],
    ]
    return list(dict.fromkeys(candidates))


def find_workspace_folder(project_path: Path) -> Path | None:
    """Find the Cursor workspace folder for the given project path."""
    if not CURSOR_PROJECTS.is_dir():
        return None

    candidates = path_to_workspace_name(project_path)
    for name in candidates:
        folder = CURSOR_PROJECTS / name
        if folder.is_dir():
            return folder

    parts = project_path.name.lower()
    for folder in CURSOR_PROJECTS.iterdir():
        if folder.is_dir() and folder.name.lower().endswith(parts):
            folder_lower = folder.name.lower()
            if "onedrive" not in folder_lower and folder.name != OLD_WORKSPACE:
                return folder

    return None


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    print(f"Project root: {project_root}")

    old_ws = CURSOR_PROJECTS / OLD_WORKSPACE
    if not old_ws.is_dir():
        print(f"ERROR: Old workspace not found at {old_ws}")
        print("Nothing to copy.")
        return 1

    transcript_count = len(list((old_ws / "agent-transcripts").glob("*.jsonl"))) if (old_ws / "agent-transcripts").is_dir() else 0
    print(f"Old workspace: {old_ws.name} ({transcript_count} chat transcripts)")

    new_ws = find_workspace_folder(project_root)
    if new_ws and new_ws.name == OLD_WORKSPACE:
        print("WARNING: You're still running from the OneDrive location.")
        print("Open the project from D:\\Projects\\Python\\astroplanner in Cursor first.")
        return 1

    if not new_ws:
        candidates = path_to_workspace_name(project_root)
        new_ws = CURSOR_PROJECTS / candidates[0]
        print(f"New workspace folder not found. Creating: {new_ws.name}")
        new_ws.mkdir(parents=True, exist_ok=True)
    else:
        print(f"New workspace: {new_ws.name}")

    copied_any = False
    for folder_name in FOLDERS_TO_COPY:
        src = old_ws / folder_name
        dst = new_ws / folder_name

        if not src.is_dir():
            continue

        src_files = list(src.rglob("*"))
        src_file_count = sum(1 for f in src_files if f.is_file())
        if src_file_count == 0:
            continue

        if dst.is_dir():
            existing = sum(1 for f in dst.rglob("*") if f.is_file())
            if existing >= src_file_count:
                print(f"  {folder_name}/: already has {existing} files (source has {src_file_count}), skipping")
                continue
            print(f"  {folder_name}/: merging {src_file_count} files into existing {existing}...")
        else:
            print(f"  {folder_name}/: copying {src_file_count} files...")

        shutil.copytree(src, dst, dirs_exist_ok=True)
        copied_any = True

    if copied_any:
        print()
        print("Chat history transferred successfully!")
        print("Restart Cursor (Ctrl+Shift+P > 'Reload Window') to pick up the transcripts.")
    else:
        print()
        print("No new data to copy (everything already present).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
