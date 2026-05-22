#!/bin/bash

# Upload all files in this folder to Azure Blob Storage via SAS URL
# Usage:
#   export AZURE_SAS_URL="https://..."
#   ./upload_to_azure.sh            # dry run (default): prints config, no upload
#   ./upload_to_azure.sh --dry-run  # same as above
#   ./upload_to_azure.sh --no-dry-run  # perform the actual upload
#   ./upload_to_azure.sh --list        # list files already at destination
#   ./upload_to_azure.sh --get-readme  # download README.txt from destination

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

echo "Source:      $SCRIPT_DIR"
echo "Account:     $AZURE_ACCOUNT"
echo "Container:   $AZURE_CONTAINER"
echo "Path:        $AZURE_PATH"
echo "SAS expires: $(echo "$SAS_QUERY" | grep -o 'se=[^&]*' | sed 's/se=//' | python3 -c 'import sys,urllib.parse; print(urllib.parse.unquote(sys.stdin.read().strip()))' 2>/dev/null || echo '(see SAS token)')"
echo ""

DRY_RUN=true
LIST=false
GET_README=false
for arg in "$@"; do
    case "$arg" in
        --no-dry-run) DRY_RUN=false ;;
        --dry-run)    DRY_RUN=true ;;
        --list)       LIST=true ;;
        --get-readme) GET_README=true ;;
    esac
done

if [ "$GET_README" = true ]; then
    echo "Downloading README.txt from destination..."
    rclone copyto ":azureblob,sas_url='${SAS_URL}':${AZURE_CONTAINER}/${AZURE_PATH}/README.txt" \
        "$SCRIPT_DIR/README.txt"
    exit $?
fi

if [ "$LIST" = true ]; then
    echo "Listing files at destination..."
    rclone ls ":azureblob,sas_url='${SAS_URL}':${AZURE_CONTAINER}/${AZURE_PATH}"
    exit $?
fi

if [ "$DRY_RUN" = true ]; then
    echo "Dry run — pass '--no-dry-run' to perform the actual upload."
    exit 0
fi

rclone copy "$SCRIPT_DIR" \
    ":azureblob,sas_url='${SAS_URL}':${AZURE_CONTAINER}/${AZURE_PATH}" \
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
