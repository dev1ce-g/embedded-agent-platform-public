"""Internal embedded runtime tools module."""

from __future__ import annotations

from embedded_runtime_common import *

def command_tool(args: argparse.Namespace) -> int:
    paths = agent_paths(args.root)
    background = read_background(paths, args.project)
    if not background:
        value = result(
            False,
            f"tool-{args.tool_action}",
            2,
            project_id=safe_project_id(args.project),
            first_failure="Project background not found",
            next_hint="Run project discover --write-background first",
        )
        print_result(value, args.json)
        return 2

    handlers = {
        "resolve-path": tool_resolve_path,
        "stat": tool_stat,
        "list": tool_list,
        "find": tool_find,
        "rg": tool_rg,
        "read": tool_read,
        "tail": tool_tail,
        "first-failure": tool_first_failure,
    }
    handler = handlers.get(args.tool_action)
    if handler is None:
        value = result(False, "tool", 2, project_id=background["project_id"], first_failure=f"Unknown tool action: {args.tool_action}")
        print_result(value, args.json)
        return 2
    return handler(args, background)

def tool_resolve_path(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info = resolve_tool_path(background, args.path)
    value = result(
        True,
        "tool-resolve-path",
        project_id=background["project_id"],
        workspace=background["workspace"],
        input_path=info["input_path"],
        normalized_path=info["normalized_path"],
        project_path=info["project_path"],
        exists=info["exists"],
        kind=info["kind"],
        inside_workspace=info["inside_workspace"],
    )
    print_result(value, args.json)
    return 0

def tool_stat(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info = resolve_tool_path(background, args.path)
    if not info["inside_workspace"]:
        return fail_outside_workspace("tool-stat", background, info, args.json)
    meta = file_metadata(info["path"], include_hash=args.sha256)
    value = result(
        meta.get("exists", False),
        "tool-stat",
        0 if meta.get("exists", False) else 2,
        project_id=background["project_id"],
        workspace=background["workspace"],
        input_path=info["input_path"],
        normalized_path=info["normalized_path"],
        project_path=info["project_path"],
        inside_workspace=True,
        **meta,
    )
    print_result(value, args.json)
    return int(value["exit_code"])

def tool_list(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info = resolve_tool_path(background, args.path)
    if not info["inside_workspace"]:
        return fail_outside_workspace("tool-list", background, info, args.json)
    if not info["path"].is_dir():
        value = result(
            False,
            "tool-list",
            2,
            project_id=background["project_id"],
            workspace=background["workspace"],
            input_path=info["input_path"],
            normalized_path=info["normalized_path"],
            project_path=info["project_path"],
            kind=info["kind"],
            first_failure="Path is not a directory",
        )
        print_result(value, args.json)
        return 2
    entries, entry_count, truncated = bounded_entries(info["path"], max(1, args.max_entries))
    value = result(
        True,
        "tool-list",
        project_id=background["project_id"],
        workspace=background["workspace"],
        input_path=info["input_path"],
        normalized_path=info["normalized_path"],
        project_path=info["project_path"],
        entry_count=entry_count,
        entries=entries,
        truncated=truncated,
    )
    print_result(value, args.json)
    return 0

def tool_find(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info = resolve_tool_path(background, args.tool_root)
    if not info["inside_workspace"]:
        return fail_outside_workspace("tool-find", background, info, args.json)
    files = iter_tool_files(info["path"])
    matches: list[dict[str, str]] = []
    max_count = max(1, args.max_count)
    for path in files:
        rel_path = rel(path, Path(background["workspace"]))
        if fnmatch.fnmatch(path.name, args.glob) or fnmatch.fnmatch(rel_path, args.glob):
            matches.append({"path": rel_path, "normalized_path": str(path)})
            if len(matches) >= max_count:
                break
    match_count = sum(
        1
        for path in files
        if fnmatch.fnmatch(path.name, args.glob) or fnmatch.fnmatch(rel(path, Path(background["workspace"])), args.glob)
    )
    value = result(
        True,
        "tool-find",
        project_id=background["project_id"],
        workspace=background["workspace"],
        root=info["project_path"],
        normalized_root=info["normalized_path"],
        glob=args.glob,
        match_count=match_count,
        matches=matches,
        truncated=match_count > len(matches),
    )
    print_result(value, args.json)
    return 0

def tool_rg(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info = resolve_tool_path(background, args.tool_root)
    if not info["inside_workspace"]:
        return fail_outside_workspace("tool-rg", background, info, args.json)
    if not info["path"].exists():
        value = result(False, "tool-rg", 2, project_id=background["project_id"], root=info["project_path"], first_failure="Search root does not exist")
        print_result(value, args.json)
        return 2
    rg_value = run_ripgrep(args, background, info)
    if rg_value is None:
        rg_value = run_python_search(args, background, info)
    print_result(rg_value, args.json)
    return int(rg_value["exit_code"])

def run_ripgrep(args: argparse.Namespace, background: dict[str, Any], info: dict[str, Any]) -> dict[str, Any] | None:
    command = [
        "rg",
        "--json",
        "--line-number",
        "--column",
        "--max-count",
        str(max(1, args.max_count)),
    ]
    if not args.regex:
        command.append("--fixed-strings")
    if args.ignore_case:
        command.append("--ignore-case")
    if args.glob:
        command.extend(["--glob", args.glob])
    command.extend([args.pattern, str(info["path"])])
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None

    matches: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") != "match":
            continue
        data = item.get("data", {})
        path_text = data.get("path", {}).get("text")
        lines_text = data.get("lines", {}).get("text", "")
        submatches = data.get("submatches") or [{}]
        first = submatches[0] if submatches else {}
        path = Path(path_text) if path_text else info["path"]
        matches.append({
            "path": rel(path, Path(background["workspace"])),
            "line": data.get("line_number"),
            "column": first.get("start", 0) + 1 if isinstance(first.get("start"), int) else None,
            "text": bounded_text(lines_text.strip()),
        })
        if len(matches) >= max(1, args.max_count):
            break
    ok = completed.returncode in (0, 1)
    return result(
        ok,
        "tool-rg",
        0 if ok else completed.returncode,
        project_id=background["project_id"],
        workspace=background["workspace"],
        root=info["project_path"],
        normalized_root=info["normalized_path"],
        pattern=args.pattern,
        glob=args.glob,
        match_count=len(matches),
        matches=matches,
        truncated=len(matches) >= max(1, args.max_count),
        rg_exit_code=completed.returncode,
        backend="rg",
        stderr=completed.stderr.strip(),
        first_failure=completed.stderr.strip() if completed.returncode not in (0, 1) else None,
    )

def run_python_search(args: argparse.Namespace, background: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    flags = re.IGNORECASE if args.ignore_case else 0
    pattern = re.compile(args.pattern if args.regex else re.escape(args.pattern), flags)
    matches: list[dict[str, Any]] = []
    searched = 0
    bytes_read = 0
    input_truncated = False
    max_count = max(1, args.max_count)
    max_bytes = min(MAX_TOOL_SEARCH_BYTES, max(1, args.max_bytes))
    for path in iter_tool_files(info["path"]):
        rel_path = rel(path, Path(background["workspace"]))
        if args.glob and not (fnmatch.fnmatch(path.name, args.glob) or fnmatch.fnmatch(rel_path, args.glob)):
            continue
        text, _, binary, current_bytes = read_text_file(path, max_bytes=max_bytes)
        if binary or text is None:
            continue
        searched += 1
        bytes_read += current_bytes
        try:
            input_truncated = input_truncated or path.stat().st_size > current_bytes
        except OSError:
            input_truncated = True
        for line_no, line in enumerate(text.splitlines(), start=1):
            match = pattern.search(line)
            if not match:
                continue
            matches.append({
                "path": rel_path,
                "line": line_no,
                "column": match.start() + 1,
                "text": bounded_text(line.strip()),
            })
            if len(matches) >= max_count:
                break
        if len(matches) >= max_count:
            break
    return result(
        True,
        "tool-rg",
        project_id=background["project_id"],
        workspace=background["workspace"],
        root=info["project_path"],
        normalized_root=info["normalized_path"],
        pattern=args.pattern,
        glob=args.glob,
        match_count=len(matches),
        matches=matches,
        bytes_read=bytes_read,
        max_bytes_per_file=max_bytes,
        truncated=len(matches) >= max_count or input_truncated,
        backend="python-fallback",
        files_searched=searched,
    )

def tool_read(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info = resolve_tool_path(background, args.path)
    if not info["inside_workspace"]:
        return fail_outside_workspace("tool-read", background, info, args.json)
    path = info["path"]
    if not path.is_file():
        value = result(False, "tool-read", 2, project_id=background["project_id"], path=info["project_path"], first_failure="Path is not a file")
        print_result(value, args.json)
        return 2
    size = path.stat().st_size
    offset = max(0, args.offset)
    max_bytes = max(1, args.max_bytes)
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read(max_bytes)
    text, encoding, binary = decode_text(data, args.encoding)
    value = result(
        True,
        "tool-read",
        project_id=background["project_id"],
        workspace=background["workspace"],
        input_path=info["input_path"],
        normalized_path=info["normalized_path"],
        project_path=info["project_path"],
        encoding=encoding,
        offset=offset,
        bytes_read=len(data),
        size=size,
        truncated=(offset + len(data)) < size,
        binary=binary,
    )
    if binary or text is None:
        if args.binary:
            value["content_b64"] = base64.b64encode(data).decode("ascii")
        else:
            value["first_failure"] = "File chunk appears to be binary; pass --binary to return content_b64"
    else:
        value["content"] = text
    print_result(value, args.json)
    return 0

def tool_tail(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info = resolve_tool_path(background, args.path)
    if not info["inside_workspace"]:
        return fail_outside_workspace("tool-tail", background, info, args.json)
    path = info["path"]
    if not path.is_file():
        value = result(False, "tool-tail", 2, project_id=background["project_id"], path=info["project_path"], first_failure="Path is not a file")
        print_result(value, args.json)
        return 2
    size = path.stat().st_size
    read_size = min(size, max(DEFAULT_TAIL_BYTES, args.lines * 512))
    with path.open("rb") as handle:
        handle.seek(max(0, size - read_size))
        data = handle.read(read_size)
    text, encoding, binary = decode_text(data, args.encoding)
    if binary or text is None:
        value = result(False, "tool-tail", 2, project_id=background["project_id"], path=info["project_path"], encoding=encoding, first_failure="Cannot tail binary file as text")
        print_result(value, args.json)
        return 2
    all_lines = text.splitlines()
    lines = all_lines[-max(1, args.lines):]
    failure = detect_first_failure(lines)
    value = result(
        True,
        "tool-tail",
        project_id=background["project_id"],
        workspace=background["workspace"],
        input_path=info["input_path"],
        normalized_path=info["normalized_path"],
        project_path=info["project_path"],
        encoding=encoding,
        size=size,
        line_count=len(lines),
        lines=lines,
        truncated=len(all_lines) > len(lines) or read_size < size,
        **failure,
    )
    print_result(value, args.json)
    return 0

def tool_first_failure(args: argparse.Namespace, background: dict[str, Any]) -> int:
    info = resolve_tool_path(background, args.path)
    if not info["inside_workspace"]:
        return fail_outside_workspace("tool-first-failure", background, info, args.json)
    path = info["path"]
    if not path.is_file():
        value = result(False, "tool-first-failure", 2, project_id=background["project_id"], path=info["project_path"], first_failure="Path is not a file")
        print_result(value, args.json)
        return 2
    text, encoding, binary, bytes_read = read_text_file(path, args.encoding, max(1, args.max_bytes))
    if binary or text is None:
        value = result(False, "tool-first-failure", 2, project_id=background["project_id"], path=info["project_path"], encoding=encoding, first_failure="Cannot scan binary file as text")
        print_result(value, args.json)
        return 2
    lines = text.splitlines()
    failure = detect_first_failure(lines)
    value = result(
        True,
        "tool-first-failure",
        project_id=background["project_id"],
        workspace=background["workspace"],
        input_path=info["input_path"],
        normalized_path=info["normalized_path"],
        project_path=info["project_path"],
        encoding=encoding,
        bytes_read=bytes_read,
        truncated=path.stat().st_size > bytes_read,
        hint="No failure pattern found" if failure["first_failure"] is None else "Review this line before later cascading errors",
        **failure,
    )
    print_result(value, args.json)
    return 0
