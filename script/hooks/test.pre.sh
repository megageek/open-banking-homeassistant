#!/usr/bin/env bash

# Keep live tests opt-in while leaving the template-managed test runner generic.
if ! python -c "import playwright, pytest" >/dev/null 2>&1; then
    log_info "Installing integration-specific test dependencies..."
    uv pip install \
        --requirement requirements_test.txt \
        --requirement script/hooks/requirements-test.txt
fi

has_marker_expression=false
for argument in "${PYTEST_ARGS[@]}"; do
    if [[ "$argument" == "-m" || "$argument" == "--markexpr" || "$argument" == --markexpr=* ]]; then
        has_marker_expression=true
        break
    fi
done

if [[ "$has_marker_expression" == "false" ]]; then
    PYTEST_ARGS+=("-m" "not live_api and not live_e2e")
elif [[ " ${PYTEST_ARGS[*]} " == *" live_e2e "* ]]; then
    log_info "Ensuring the Playwright Chromium browser is installed..."
    python -m playwright install chromium
fi
