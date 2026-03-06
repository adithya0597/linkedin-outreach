#!/bin/bash
#
# setup.sh — Verify Claude Code best practices configuration
# Idempotent: safe to run multiple times.

set -euo pipefail

PROJECT_DIR="/Users/adithya/cowork-stuff/lineked outreach"
SCRIPTS_DIR="${PROJECT_DIR}/scripts"
CLAUDE_DIR="${PROJECT_DIR}/.claude"
SETTINGS_FILE="${CLAUDE_DIR}/settings.local.json"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass=0
fail=0

check() {
    local label="$1"
    local result="$2"
    if [ "$result" = "ok" ]; then
        echo -e "  ${GREEN}✓${NC} $label"
        ((pass++)) || true
    else
        echo -e "  ${RED}✗${NC} $label — $result"
        ((fail++)) || true
    fi
}

echo "=== Claude Code Best Practices Setup Check ==="
echo ""

# 1. Check jq
echo "Dependencies:"
if command -v jq &>/dev/null; then
    check "jq installed" "ok"
else
    check "jq installed" "MISSING: brew install jq"
fi

# 2. Check scripts
echo ""
echo "Scripts (${SCRIPTS_DIR}):"
for script in context-bar.sh check-context.sh clone-conversation.sh half-clone-conversation.sh; do
    if [ -f "${SCRIPTS_DIR}/${script}" ]; then
        if [ -x "${SCRIPTS_DIR}/${script}" ]; then
            check "$script" "ok"
        else
            check "$script" "exists but not executable"
        fi
    else
        check "$script" "MISSING"
    fi
done

# 3. Check commands
echo ""
echo "Commands (${CLAUDE_DIR}/commands/):"
for cmd in clone.md half-clone.md handoff.md review-claudemd.md; do
    if [ -f "${CLAUDE_DIR}/commands/${cmd}" ]; then
        check "/$(basename $cmd .md)" "ok"
    else
        check "/$(basename $cmd .md)" "MISSING"
    fi
done

# 4. Check agents
echo ""
echo "Agents (${CLAUDE_DIR}/agents/):"
for agent in verify-work.md code-simplifier.md; do
    if [ -f "${CLAUDE_DIR}/agents/${agent}" ]; then
        check "$(basename $agent .md)" "ok"
    else
        check "$(basename $agent .md)" "MISSING"
    fi
done

# 5. Check rules
echo ""
echo "Rules (${CLAUDE_DIR}/rules/):"
for rule in verification.md parallel-work.md; do
    if [ -f "${CLAUDE_DIR}/rules/${rule}" ]; then
        check "$(basename $rule .md)" "ok"
    else
        check "$(basename $rule .md)" "MISSING"
    fi
done

# 6. Check settings
echo ""
echo "Settings (${SETTINGS_FILE}):"
if [ -f "$SETTINGS_FILE" ]; then
    if jq . "$SETTINGS_FILE" >/dev/null 2>&1; then
        check "valid JSON" "ok"
    else
        check "valid JSON" "INVALID JSON"
    fi

    if jq -e '.env.ENABLE_TOOL_SEARCH' "$SETTINGS_FILE" >/dev/null 2>&1; then
        check "ENABLE_TOOL_SEARCH" "ok"
    else
        check "ENABLE_TOOL_SEARCH" "not set"
    fi

    if jq -e '.hooks.Stop' "$SETTINGS_FILE" >/dev/null 2>&1; then
        check "Stop hook" "ok"
    else
        check "Stop hook" "not configured"
    fi

    perm_count=$(jq '.permissions.allow | length' "$SETTINGS_FILE" 2>/dev/null || echo 0)
    if [ "$perm_count" -ge 10 ]; then
        check "permissions ($perm_count rules)" "ok"
    else
        check "permissions ($perm_count rules)" "fewer than expected"
    fi
else
    check "settings file" "MISSING"
fi

# Summary
echo ""
echo "=== Summary: ${pass} passed, ${fail} failed ==="
if [ "$fail" -eq 0 ]; then
    echo -e "${GREEN}All checks passed!${NC}"
else
    echo -e "${YELLOW}Some checks failed. Review above.${NC}"
fi
