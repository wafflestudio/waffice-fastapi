#!/bin/bash

# Ralph Wiggum Loop Runner for Waffice FastAPI Refactoring
# Usage: ./.ralph/run.sh [max_iterations]

set -e

MAX_ITERATIONS=${1:-50}
PROMPT_FILE=".ralph/refactor-prompt.md"
COMPLETION_SIGNAL="<promise>COMPLETE</promise>"
LOG_FILE=".ralph/ralph.log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Ralph Wiggum Loop ===${NC}"
echo "Max iterations: $MAX_ITERATIONS"
echo "Prompt file: $PROMPT_FILE"
echo "Log file: $LOG_FILE"
echo ""

# Check if prompt file exists
if [ ! -f "$PROMPT_FILE" ]; then
    echo -e "${RED}Error: Prompt file not found: $PROMPT_FILE${NC}"
    exit 1
fi

PROMPT=$(cat "$PROMPT_FILE")

# Initialize log
echo "=== Ralph Loop Started: $(date) ===" > "$LOG_FILE"
echo "Max iterations: $MAX_ITERATIONS" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

iteration=0
while [ $iteration -lt $MAX_ITERATIONS ]; do
    iteration=$((iteration + 1))
    echo -e "${YELLOW}--- Iteration $iteration / $MAX_ITERATIONS ---${NC}"
    echo "--- Iteration $iteration: $(date) ---" >> "$LOG_FILE"

    # Run Claude with the prompt (skip permission prompts for automation)
    # Capture output to check for completion signal
    OUTPUT=$(claude --dangerously-skip-permissions --print "$PROMPT" 2>&1) || true

    # Log output
    echo "$OUTPUT" >> "$LOG_FILE"
    echo "" >> "$LOG_FILE"

    # Check for completion signal
    if echo "$OUTPUT" | grep -q "$COMPLETION_SIGNAL"; then
        echo -e "${GREEN}=== COMPLETE ===${NC}"
        echo "Completion signal received at iteration $iteration"
        echo "=== COMPLETE at iteration $iteration: $(date) ===" >> "$LOG_FILE"
        exit 0
    fi

    echo "Completion signal not found. Continuing..."
    echo ""

    # Small delay to avoid rate limiting
    sleep 2
done

echo -e "${RED}=== Max iterations reached ===${NC}"
echo "=== Max iterations reached: $(date) ===" >> "$LOG_FILE"
exit 1
