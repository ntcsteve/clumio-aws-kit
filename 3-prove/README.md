# Step 3: Prove it

A backup counts once you've seen it, and seen it restore. Three checks. Run the commands from the repository's root folder.

## 1. Who protects each resource

```bash
tools/status.py
```

It lists every resource tagged `clumio-profile` (and every volume tagged `clumio-volume-profile`), who protects it, and its last backup. It reads AWS and Clumio, and changes nothing. The first line checks the connection. Right after step 2, resources show NOT_YET or WAITING; once each one's first backup has run, every resource line should say OURS. [Read tools/status.py](../docs/operate.md#read-toolsstatuspy) says what each other state means, and what to do.

Give it time. In the lab run, a bucket joined its protection group within minutes, and every resource had its first backup within an hour of step 2. Allow up to a day before you look in Clumio's Tasks.

## 2. Restore one

In the Clumio console, restore one resource you protected, to a new name beside the original, never over it. For a database, Clumio creates a new instance or cluster. For a bucket, restore a folder to a new prefix.

When the restore task completes, open what came back and check it. Which key the copy gets depends on the workload: see [What a restore needs from you](../docs/keys.md#what-a-restore-needs-from-you). A restored Aurora cluster carried no `clumio-profile` tag in the lab run, so the kit neither protects nor removes it: delete it yourself when you're done. Restored S3 objects land in the bucket you name; in a tagged bucket, they're protected with it.

## 3. Keep the evidence

Save what you saw, for whoever signs off:

```bash
tools/status.py --json > status-$(date -u +%Y%m%d).json
```

The file names your AWS account, so keep it out of anything public; this repository's `.gitignore` skips `status-*.json`.

Add the restore task's ID from Clumio's Tasks page. Each backup and restore is a Clumio task, with its start and end times.

## Next

- Keep it: for production, call the same modules from your own repository, with your own state and CI: see [Production](../docs/production.md).
- Take a trial down: [Take a trial down](../docs/operate.md#take-a-trial-down).
