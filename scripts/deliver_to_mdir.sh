#!/bin/bash

# Upload all files in this folder to Azure Blob Storage via SAS URL
# Usage:
#   export AZURE_SAS_URL="https://..."
#   ./upload_to_azure.sh            # dry run (default): prints config, no upload
#   ./upload_to_azure.sh --dry-run  # same as above
#   ./upload_to_azure.sh --no-dry-run  # perform the actual upload
#   ./upload_to_azure.sh --list        # list files already at destination
#   ./upload_to_azure.sh --get-readme  # download README.txt from destination
#   ./upload_to_azure.sh --clean          # delete all uploaded files from destination
#   ./upload_to_azure.sh --print-remote   # print rclone remote path for manual use

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "$AZURE_SAS_URL" ]; then
    echo "Error: AZURE_SAS_URL environment variable is not set."
    exit 1
fi

# Parse account, container and path from the SAS URL
AZURE_ACCOUNT=$(echo "$AZURE_SAS_URL" | sed 's|https://\([^.]*\)\..*|\1|')
AZURE_CONTAINER=$(echo "$AZURE_SAS_URL" | sed 's|https://[^/]*/\([^/?]*\).*|\1|')
AZURE_PATH=$(echo "$AZURE_SAS_URL" | sed 's|https://[^/]*/[^/]*/\([^?]*\).*|\1|')
SAS_QUERY=$(echo "$AZURE_SAS_URL" | sed 's|[^?]*?\(.*\)|\1|')
SAS_URL="https://${AZURE_ACCOUNT}.blob.core.windows.net/?${SAS_QUERY}"
DEST="${AZURE_CONTAINER}/${AZURE_PATH}/data"

echo "Source:      $SCRIPT_DIR"
echo "Account:     $AZURE_ACCOUNT"
echo "Container:   $AZURE_CONTAINER"
echo "Destination: $DEST"
echo "SAS expires: $(echo "$SAS_QUERY" | grep -o 'se=[^&]*' | sed 's/se=//' | python3 -c 'import sys,urllib.parse; print(urllib.parse.unquote(sys.stdin.read().strip()))' 2>/dev/null || echo '(see SAS token)')"
echo ""

DRY_RUN=true
LIST=false
GET_README=false
CLEAN=false
PRINT_REMOTE=false
for arg in "$@"; do
    case "$arg" in
        --no-dry-run) DRY_RUN=false ;;
        --dry-run)    DRY_RUN=true ;;
        --list)       LIST=true ;;
        --get-readme) GET_README=true ;;
        --clean)       CLEAN=true ;;
        --print-remote) PRINT_REMOTE=true ;;
    esac
done

if [ "$PRINT_REMOTE" = true ]; then
    echo ":azureblob,sas_url='${SAS_URL}':${AZURE_CONTAINER}/${AZURE_PATH}"
    exit 0
fi


    echo "WARNING: This will delete all files at the destination:"
    echo "  ${DEST}"
    echo ""
    read -r -p "Are you sure? [y/N] " confirm
    if [[ "$confirm" != [yY] ]]; then
        echo "Aborted."
        exit 0
    fi
    echo "Deleting all files at destination..."
    rclone delete ":azureblob,sas_url='${SAS_URL}':${DEST}" \
        --rmdirs \
        --exclude "README.txt"
    exit $?
fi


if [ "$GET_README" = true ]; then
    echo "Downloading README.txt from destination..."
    rclone copyto ":azureblob,sas_url='${SAS_URL}':${AZURE_CONTAINER}/${AZURE_PATH}/README.txt" \
        "$SCRIPT_DIR/README.txt"
    exit $?
fi

if [ "$LIST" = true ]; then
    echo "Listing files at destination..."
    rclone ls ":azureblob,sas_url='${SAS_URL}':${DEST}"
    exit $?
fi

if [ "$DRY_RUN" = true ]; then
    echo "Dry run — pass '--no-dry-run' to perform the actual upload."
    exit 0
fi

rclone copy "$SCRIPT_DIR" \
    ":azureblob,sas_url='${SAS_URL}':${DEST}" \
    --progress \
    --transfers 4 \
    --exclude "upload_to_azure.sh" \
    --exclude "*.docx"

if [ $? -eq 0 ]; then
    echo ""
    echo "Upload completed successfully."
else
    echo ""
    echo "Upload failed. Check the output above for details."
    exit 1
fi
