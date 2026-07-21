#!/usr/bin/env bash

# Install integration-specific test dependencies after the template toolchain.
uv pip install --requirement script/hooks/requirements-test.txt
