# Stash Unified Repository

A single Stash plugin-manager source index built from the [community source list](https://discourse.stashapp.cc/t/list-of-plugin-sources/122) plus optional entries in `sources.txt`.

## Setup

1. Create a **public** GitHub repository named `stash-unified-repository` (or another name).
2. Upload all the contents of this folder, including `.github/workflows/update.yml`, to the `main` branch.
3. In GitHub **Settings → Actions → General → Workflow permissions**, allow **Read and write permissions** if needed for the workflow to commit updates.
4. In **Settings → Pages**, choose **Deploy from a branch**, `main`, `/docs`, and save.
5. Open **Actions → Update Stash catalog → Run workflow**. Wait for it to finish and for Pages to publish.
6. In Stash **Settings → Plugins → Available Plugins → Add Source**, enter:

   `https://YOUR-USERNAME.github.io/stash-unified-repository/index.yml`

   Change the repository segment if you used a different name. Test installing one plugin before deleting existing source entries.

## How it works

- Runs daily (09:17 UTC) and manually through Actions.
- Collects index URLs from the community forum and `sources.txt`.
- Converts relative ZIP paths to absolute upstream URLs; no ZIP files are mirrored.
- Deduplicates by exact package ID. If IDs conflict, the alphabetically first source URL wins. See `docs/report.json` for conflicts.
- Keeps previously published entries when an upstream source fails or disappears. **This also means removed packages may linger**; review before relying on a retired package.
- Reports failed sources and conflicting package IDs in `docs/report.json`.

## Important limitations

- The source-list discovery depends on the forum's HTML; check `docs/sources.json` and add missing URLs manually to `sources.txt`.
- If two sources share an ID but publish different packages, only one can be exposed under that ID. The chosen package may not be the preferred one; inspect conflicts.
- This is a catalog, not a security review. Install only plugins you trust.
- Stash's update/migration behavior with already-installed plugins should be verified before removing old source entries.
- Existing sources remain untouched until you remove them yourself.
