# Running and checking JobTracker

## Live Telegram check

This needs the owner's bot token and a started private chat. Automated tests do not replace it.

1. Start the API, bot, and worker using the README commands.
2. Add a synthetic job with `/new` and change it to Applied.
3. Set a reminder a few minutes ahead with `/remind <job_id>`.
4. Check that it arrives once, then press Done. `/today` should no longer show it.
5. Restart the processes and verify the job and status remain.
6. From another Telegram account, check that `/list` does not expose jobs.

## Docker backup

Choose a new filename each time:

```text
docker compose exec api python -m scripts.backup /srv/jobtracker/data/jobtracker.db /srv/jobtracker/data/backup-2026-10-04.db
docker compose cp api:/srv/jobtracker/data/backup-2026-10-04.db ./backups/backup-2026-10-04.db
```

Create the local `backups` folder before copying. Backups contain private application data.

For a Docker restore, stop all services. Use a separate new volume and copy the backup into it with the correct file ownership. Point the API's volume mapping at that volume, start the API, and inspect records before starting the bot and worker. Keep the original volume until the restore is confirmed. This procedure is documented, but the Docker restore still needs an environment-level check.

## Before publishing

Publish this `jobtracker` folder, not its parent workspace. Check the files and Git history for `.env`, databases, tokens, real applications, and backups. `.gitignore` prevents new accidental additions but doesn't remove secrets already committed. Choose a license before making reuse permissions explicit.

No GitHub repository has been created or pushed by this implementation.
