#!/usr/bin/env bash

# Remove an accidentally installed distribution before cleaning import packages.
project_name=$(python -c \
    'import tomllib; from pathlib import Path; print(tomllib.loads(Path("pyproject.toml").read_text())["project"]["name"])')
if pip show "$project_name" >/dev/null 2>&1; then
    log_step "Uninstalling accidentally installed project package: $project_name"
    pip uninstall -y "$project_name"
fi
