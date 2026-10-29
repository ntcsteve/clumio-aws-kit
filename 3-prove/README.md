# Step 3: Prove it

A backup counts once you've seen it restore. Three checks, run from the repository's root folder.

## 1. Who protects each resource

```bash
tools/status.py
```

It lists every resource tagged `clumio-profile` (volumes on their own: `clumio-volume-profile`), who protects it, and its last backup. It reads AWS and Clumio and changes nothing. The first line checks the connection. Right after step 2, resources show NOT_YET or WAITING; after each first backup, OURS. [Read tools/status.py](../docs/operate.md#read-toolsstatuspy) explains every other state.

Give it time. In the lab, a bucket joined its group within minutes, and every resource had its first backup within an hour. Allow up to a day before you look in Clumio's Tasks.

## 2. Restore one

In the Clumio console, restore one resource you protected, to a new name beside the original, never over it. For a database, Clumio creates a new instance or cluster. For a bucket, restore a folder to a new prefix.

When the restore task completes, open what came back and check it. The key the copy gets depends on the workload: see [What a restore needs from you](../docs/keys.md#what-a-restore-needs-from-you). In the lab, a restored Aurora cluster carried no `clumio-profile` tag, so the kit neither protects nor removes it: delete it when you're done. Restored S3 objects land in the bucket you name, and in a tagged bucket they're protected with it. A restored EC2 instance or EBS volume keeps the original's tags, profile tag included, so it joins that profile at Clumio's next discovery cycle and gets backed up and billed: delete it, or remove the tag, when you're done. Its Name tag is the original's, whatever name you gave in the console, so check the instance ID before you delete. A restored instance's root volume isn't deleted with the instance: delete it too.

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
