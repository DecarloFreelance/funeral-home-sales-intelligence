#!/usr/bin/env bash

# Opt-in task-list helper for this repository. It never changes command status,
# environment secrets, or project data. It does not register a prompt hook;
# invoke the reminder explicitly between command sequences.
cfi_tasklist_remind() {
    printf '[tasklist] Review docs/TASKLIST.md before the next command sequence.\n'
}

# Remove the previous version's hook if this file is sourced into an existing
# shell. This preserves unrelated prompt commands.
if declare -p PROMPT_COMMAND 2>/dev/null | grep -q 'declare -a'; then
    cfi_prompt_commands=()
    for cfi_prompt_command in "${PROMPT_COMMAND[@]}"; do
        [[ "$cfi_prompt_command" == "cfi_tasklist_prompt" ]] ||
            cfi_prompt_commands+=("$cfi_prompt_command")
    done
    PROMPT_COMMAND=("${cfi_prompt_commands[@]}")
else
    PROMPT_COMMAND="${PROMPT_COMMAND//cfi_tasklist_prompt/}"
    PROMPT_COMMAND="${PROMPT_COMMAND//;;/;}"
    PROMPT_COMMAND="${PROMPT_COMMAND##;}"
    PROMPT_COMMAND="${PROMPT_COMMAND%%;}"
fi
