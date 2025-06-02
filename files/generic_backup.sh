#!/bin/bash
set -eo pipefail

# --- Logging Functions ---
_log_timestamp() {
    # You can customize the date format here if needed
    date '+%Y-%m-%d %H:%M:%S'
}

log_message() {
    echo "$(_log_timestamp) - INFO - $1"
}

log_warning() {
    # For non-critical issues or notable events
    echo "$(_log_timestamp) - WARN - $1"
}

log_error() {
    # For errors, output to stderr
    echo "$(_log_timestamp) - ERROR - $1" >&2
}
# --- End Logging Functions ---

CONTAINER_NAMES=()
SOURCE_PATHS=()
DESTINATION_PATH=""

# --- Simple Argument Parsing ---
while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        --containers)
        if [[ -n "$2" ]]; then IFS=' ' read -r -a CONTAINER_NAMES <<< "$2"; fi
        shift # past argument
        shift # past value
        ;;
        --sources)
        if [[ -n "$2" ]]; then IFS=' ' read -r -a SOURCE_PATHS <<< "$2"; fi
        shift # past argument
        shift # past value
        ;;
        --dest)
        DESTINATION_PATH="$2"
        shift # past argument
        shift # past value
        ;;
        *)    # unknown option
        log_error "Unknown option: $1"
        exit 1
        ;;
    esac
done

if [ ${#SOURCE_PATHS[@]} -eq 0 ] || [ -z "$DESTINATION_PATH" ]; then
    log_error "Usage: $0 --sources \"/src1 /src2\" --dest /path/to/dest [--containers \"container1 container2\"]"
    log_error "--sources and --dest are mandatory."
    exit 1
fi

log_message "----------------------------------------------------" # Separators will also be timestamped
log_message "Starting backup process"
log_message "Sources: ${SOURCE_PATHS[*]}"
log_message "Destination: $DESTINATION_PATH"
if [ ${#CONTAINER_NAMES[@]} -gt 0 ]; then
    log_message "Containers: ${CONTAINER_NAMES[*]}"
fi
log_message "----------------------------------------------------"

# Stop containers
if [ ${#CONTAINER_NAMES[@]} -gt 0 ]; then
    log_message "Stopping containers: ${CONTAINER_NAMES[*]}..."
    for container in "${CONTAINER_NAMES[@]}"; do
        if docker ps -q --filter name="^${container}$" | grep -q .; then
            log_message "Stopping container: $container"
            docker stop "$container"
        else
            log_warning "Container $container is not running or does not exist. Skipping stop."
        fi
    done
fi

# Ensure base destination directory exists.
# This action itself isn't explicitly logged by a log_message call, which is usually fine.
mkdir -p "$DESTINATION_PATH"

# Copy folders/files
log_message "Copying data..."
for src_path in "${SOURCE_PATHS[@]}"; do
    log_message "Processing source: $src_path"
    if [ -e "$src_path" ]; then
        dest_target_item="$DESTINATION_PATH/$(basename "$src_path")"
        log_message "Backing up $src_path to $dest_target_item"
        if [ -d "$src_path" ]; then
            rsync -avh --delete "${src_path}/" "${dest_target_item}/"
        else # Source is a file
            rsync -avh --delete "$src_path" "$dest_target_item"
        fi
    else
        log_warning "Source path $src_path does not exist. Skipping."
    fi
done

# Restart containers
if [ ${#CONTAINER_NAMES[@]} -gt 0 ]; then
    log_message "Restarting containers: ${CONTAINER_NAMES[*]}..."
    for container in "${CONTAINER_NAMES[@]}"; do
        if docker ps -aq --filter name="^${container}$" | grep -q .; then
            log_message "Starting container: $container"
            docker start "$container"
        else
            log_warning "Container $container does not exist. Skipping start."
        fi
    done
fi

log_message "Backup to $DESTINATION_PATH completed successfully."
log_message "----------------------------------------------------"

exit 0