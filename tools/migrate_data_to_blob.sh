#!/usr/bin/env bash
# One-shot migration (az4): copy the registers under data/ from this checkout to the Azure Blob container lotto-data,
# one blob per file, blob name = repo-relative path (data/comps/comps.jsonl). Run it ONCE, from the repository root,
# on a checkout of main that holds the data you want to keep, BEFORE the az4 image and job files are deployed:
#   az login
#   bash tools/migrate_data_to_blob.sh              # upload
#   DRYRUN=1 bash tools/migrate_data_to_blob.sh     # list what would be uploaded, change nothing
# Needs the Azure CLI, and your user needs "Storage Blob Data Contributor" on the storage account (the jobs'
# managed identity id-personal-v5ethud2i3cfq needs the same role; see the az4 notes). Uses --auth-mode login: no keys.
# Existing blobs are never overwritten (--overwrite false), so a second run cannot clobber what the jobs wrote since.
set -euo pipefail

ACCOUNT="${LOTTO_DATA_ACCOUNT:-stpersonalv5ethud2i3cfq}"
CONTAINER="${LOTTO_DATA_CONTAINER:-lotto-data}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-personal-automation-aue}"

[ -d data ] || { echo "run this from the repository root (no data/ folder here)" >&2; exit 1; }

echo "Local files under data/: $(find data -type f | wc -l)"

echo "Blob versioning on for $ACCOUNT (a bad write can be rolled back)"
az storage account blob-service-properties update \
  --account-name "$ACCOUNT" --resource-group "$RESOURCE_GROUP" --enable-versioning true --only-show-errors > /dev/null

echo "Container $CONTAINER (created if missing; private)"
az storage container create \
  --account-name "$ACCOUNT" --name "$CONTAINER" --auth-mode login --public-access off --only-show-errors > /dev/null

dry=()
[ "${DRYRUN:-0}" = "1" ] && dry=(--dryrun)

az storage blob upload-batch \
  --account-name "$ACCOUNT" --auth-mode login \
  --destination "$CONTAINER" --source data --destination-path data \
  --overwrite false --only-show-errors ${dry[@]+"${dry[@]}"}

if [ "${DRYRUN:-0}" != "1" ]; then
  remote="$(az storage blob list --account-name "$ACCOUNT" --auth-mode login --container-name "$CONTAINER" \
    --prefix data/ --query 'length(@)' -o tsv --only-show-errors)"
  echo "Blobs under data/ in $CONTAINER: $remote (local files: $(find data -type f | wc -l))"
fi
