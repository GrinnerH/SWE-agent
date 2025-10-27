#!/bin/bash

# Colors for output
BLUE='\033[0;34m'
GREEN='\033[0;32m'
BOLD='\033[1m'
RESET='\033[0m'

# Display usage information
usage() {
    echo "Usage: $0 <mode> [options]"
    echo ""
    echo "Modes:"
    echo "  poc     - Run PoC generation"
    echo "  patch   - Run patch generation"
    echo ""
    echo "Options:"
    echo "  -m MODEL     Model name (default: 4o)"
    echo "  -c COST      Cost limit (default: 1.5)"
    echo "  -e TEMP      Temperature (default: 0.0)"
    echo "  -s SPLIT     Split (default: eval)"
    echo "  -l SLICE     Slice (default: :80)"
    echo "  -n CALLS     Per instance call limit (default: 75)"
    echo "  -w WORKERS   Number of workers (default: 1)"
    echo "  -b API_BASE  API Base URL (optional)"
    echo "  -h           Show this help message"
    echo ""
    echo "Available models: sonnet, haiku, 4o, o1, o3, gemini-pro, flash, human, deepseek"
    echo ""
    echo "Examples:"
    echo "  $0 poc"
    echo "  $0 patch -m sonnet -c 1.5 -w 2"
    echo "  $0 poc -l :30 -n 100"
}

# Check if mode argument is provided
if [ $# -eq 0 ]; then
    usage
    exit 1
fi

mode="$1"
shift

# Validate mode argument
if [ "$mode" != "poc" ] && [ "$mode" != "patch" ]; then
    echo "Error: Mode must be either 'poc' or 'patch'"
    usage
    exit 1
fi

# Set default values based on mode
if [ "$mode" == "poc" ]; then
    config="./config/secb_poc.yaml"
    type="secb_poc"
elif [ "$mode" == "patch" ]; then
    config="./config/secb_patch.yaml"
    type="secb_patch"
fi

# Default values
model="4o"
cost_limit="1.5"
temperature="0.0"
split="eval"
slice=":80"
call_limit="75"
api_base=""
workers="1"

# Parse command line options
while getopts "m:c:e:s:l:n:w:b:h" opt; do
    case $opt in
        m) model="$OPTARG" ;;
        c) cost_limit="$OPTARG" ;;
        e) temperature="$OPTARG" ;;
        s) split="$OPTARG" ;;
        l) slice="$OPTARG" ;;
        n) call_limit="$OPTARG" ;;
        w) workers="$OPTARG" ;;
        b) api_base="$OPTARG" ;;
        h) usage; exit 0 ;;
        \?) echo "Invalid option: -$OPTARG" >&2; usage; exit 1 ;;
    esac
done

clear

# Map model names to full model names
if [ "$model" == "sonnet" ]; then
    model_name="anthropic/claude-3-7-sonnet-20250219"
    max_input_tokens=200000
elif [ "$model" == "haiku" ]; then
    model_name="claude-3-haiku-20240307"
elif [ "$model" == "4o" ]; then
    model_name="gpt-4o"
elif [ "$model" == "o3" ]; then
    model_name="o3"
elif [ "$model" == "gemini-pro" ]; then
    model_name="gemini/gemini-2.5-pro-preview-03-25"
elif [ "$model" == "human" ]; then
    model_name="human"
elif [ "$model" == "deepseek" ]; then
    model_name="openai/deepseek-chat"
    api_base="https://www.dmxapi.cn/v1"
else
    echo "Invalid model: $model"
    echo "Available models: sonnet, haiku, 4o, o3, gemini-pro, human, deepseek"
    exit 1
fi

# Display configuration
echo -e "${BOLD}============================${RESET}"
echo "Mode: $mode"
echo "Model: $model ($model_name)"
echo "Config: $config"
echo "Type: $type"
echo "Cost Limit: $cost_limit"
echo "Temperature: $temperature"
echo "Split: $split"
echo "Slice: $slice"
echo "Call Limit: $call_limit"
echo "Workers: $workers"
if [ -n "$api_base" ]; then
    echo "API Base: $api_base"
fi
echo ""

# Build the sweagent command
cmd="sweagent run-batch \
    --num_workers $workers \
    --config $config \
    --agent.model.name $model_name \
    --agent.model.temperature $temperature \
    --agent.model.top_p 0.95 \
    --agent.model.per_instance_call_limit $call_limit \
    --agent.model.per_instance_cost_limit $cost_limit \
    --agent.model.delay 1.0 \
    --instances.type $type \
    --instances.dataset_name \"SEC-bench/SEC-bench\" \
    --instances.split $split \
    --instances.slice $slice \
    --instances.shuffle=False"

# Add API base URL if provided
if [ -n "$api_base" ]; then
    echo -e "${GREEN}${BOLD}Adding API base URL: ${RESET}$api_base"
    cmd="$cmd \
    --agent.model.api_base $api_base"
fi

# Add max input tokens if provided
if [ -n "$max_input_tokens" ]; then
    echo -e "${GREEN}${BOLD}Adding max input tokens: ${RESET}$max_input_tokens"
    cmd="$cmd \
    --agent.model.max_input_tokens $max_input_tokens"
fi

echo -e "${BLUE}${BOLD}Executing: sweagent run-batch...${RESET}"
echo ""

# Execute the command directly
eval "$cmd"