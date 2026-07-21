#!/usr/bin/env bash

# Browser tests are project-specific, so install their system dependencies via
# the template's post-create customization hook instead of a container feature.
python -m playwright install --with-deps chromium
