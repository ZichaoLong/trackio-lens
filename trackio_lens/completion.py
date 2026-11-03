"""Parser-driven, side-effect-free completion and idempotent shell integration."""

import argparse
import os
import pwd
import shlex
from pathlib import Path

MARKER = "# Managed by Trackio Lens completion"
PATH_OPTIONS = {
    "--config",
    "--state-dir",
    "--frontend",
    "--events",
    "--manifest",
    "--report",
    "--data-dir",
    "--done-file",
    "--credentials",
    "--params-file",
    "--write-token-file",
    "--python",
    "--sample",
}


def candidates(parser, words):
    """words excludes argv[0] and includes the current, possibly empty word."""
    current = words[-1] if words else ""
    prior = words[:-1]
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    active = parser
    expecting = None
    positional = []
    for word in prior:
        if expecting is not None:
            expecting = None
            continue
        if word == "--":
            return ["__files__"]
        if word in sub.choices and active is parser:
            active = sub.choices[word]
            continue
        option = active._option_string_actions.get(word.split("=", 1)[0])
        if option:
            if option.nargs != 0 and "=" not in word:
                expecting = option
        elif not word.startswith("-"):
            positional.append(word)
    if expecting is not None:
        if expecting.choices:
            return [str(c) for c in expecting.choices if str(c).startswith(current)]
        return (
            ["__files__"]
            if any(o in PATH_OPTIONS for o in expecting.option_strings)
            else []
        )
    if current.startswith("-"):
        return [o for o in active._option_string_actions if o.startswith(current)]
    if active is parser:
        return [c for c in sub.choices if c.startswith(current)]
    choices = [a for a in active._actions if not a.option_strings and a.choices]
    if choices and not positional:
        return [str(c) for c in choices[0].choices if str(c).startswith(current)]
    return []


def script(shell, command="trackio-lens"):
    executable = shlex.quote(str(command))
    name = shlex.quote(Path(command).name)
    if shell == "bash":
        return f"""{MARKER}
_trackio_lens_complete() {{
    local item
    COMPREPLY=()
    while IFS= read -r item; do COMPREPLY+=("$item"); done < <({executable} __complete "${{COMP_WORDS[@]:1:COMP_CWORD}}")
    if [[ ${{COMPREPLY[0]-}} == __files__ ]]; then
        COMPREPLY=()
        while IFS= read -r item; do COMPREPLY+=("$item"); done < <(compgen -f -- "${{COMP_WORDS[COMP_CWORD]}}")
        compopt -o filenames 2>/dev/null || true
    fi
}}
complete -F _trackio_lens_complete {name}
"""
    if shell == "zsh":
        return f"""#compdef {name}
{MARKER}
_trackio_lens_complete() {{
    local -a replies
    replies=("${{(@f)$({executable} __complete "${{words[@]:1:$((CURRENT-1))}}")}}")
    if [[ ${{replies[1]-}} == __files__ ]]; then
        _files
    else
        compadd -- "${{replies[@]}}"
    fi
}}
compdef _trackio_lens_complete {name}
"""
    if shell == "fish":
        return f"""{MARKER}
function __trackio_lens_complete
    set -l words (commandline -opc)
    set -l replies ({executable} __complete $words[2..-1] (commandline -ct))
    if test "$replies" = __files__
        __fish_complete_path (commandline -ct)
    else
        printf '%s\\n' $replies
    end
end
complete -c {name} -f -a '(__trackio_lens_complete)'
"""
    raise ValueError("Unsupported completion shell")


def managed_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and MARKER not in path.read_text()):
        raise ValueError(
            "Refusing to overwrite unrelated completion file: " + str(path)
        )
    temporary = path.with_name(path.name + ".lens-new")
    with temporary.open("x") as stream:
        stream.write(text)
    temporary.chmod(0o600)
    temporary.replace(path)


def install(command, shell=None, home=None):
    home = Path.home() if home is None else Path(home)
    shell = shell or Path(pwd.getpwuid(os.getuid()).pw_shell).name
    if shell not in {"bash", "zsh", "fish"}:
        raise ValueError("Unsupported completion shell")
    paths = {
        "bash": home / ".local/share/bash-completion/completions" / Path(command).name,
        "zsh": home / ".local/share/trackio-lens/completion.zsh",
        "fish": home / ".config/fish/completions" / (Path(command).name + ".fish"),
    }
    target = paths[shell]
    managed_write(target, script(shell, command))
    # Fish loads its user completion directory automatically. Bash and Zsh get
    # a small marked block, preserving the rest of the user's interactive config.
    if shell != "fish":
        rc = home / (".bashrc" if shell == "bash" else ".zshrc")
        if rc.is_symlink():
            raise ValueError(
                "Shell configuration is a symlink; source completion manually"
            )
        before = rc.read_text() if rc.exists() else ""
        start, end = (
            "# >>> trackio-lens completion >>>",
            "# <<< trackio-lens completion <<<",
        )
        setup = (
            "autoload -Uz compinit; (( $+functions[compdef] )) || compinit\n"
            if shell == "zsh"
            else ""
        )
        block = (
            start
            + "\n"
            + setup
            + f"[ -r {shlex.quote(str(target))} ] && . {shlex.quote(str(target))}\n"
            + end
        )
        if start in before:
            a, b = before.index(start), before.index(end) + len(end)
            after = before[:a] + block + before[b:]
        else:
            after = before.rstrip("\n") + "\n\n" + block + "\n"
        if after != before:
            # Existing permissions and unrelated shell configuration are retained.
            rc.write_text(after)
    return {"shell": shell, "completion_file": str(target), "new_shell_required": True}
