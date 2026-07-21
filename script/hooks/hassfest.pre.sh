#!/usr/bin/env bash

# An agent shell may have an unrelated virtual environment active. Force the
# template runner to activate the project environment when Home Assistant is absent.
if [[ -n ${VIRTUAL_ENV:-} ]] && ! python3 -c "import homeassistant" >/dev/null 2>&1; then
    unset VIRTUAL_ENV
fi
