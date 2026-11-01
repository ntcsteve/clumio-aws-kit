# Step 3: Prove it

[ResOps](https://www.commvault.com/explore/resilience-operations) asks for evidence rather than assumptions: a backup counts once you've seen it restore. Three checks, run from the repository's root folder.

## 1. Who protects each resource

```bash
tools/status.py
```

It lists every resource tagged `clumio-profile` (volumes on their own: `clumio-volume-profile`), who protects it, and its last backup. It reads AWS and Clumio and changes nothing. The first line checks the connection. Right after step 2, resources show NOT_YET or WAITING; after each first backup, OURS. [Read tools/status.py](../docs/operate.md#read-toolsstatuspy) explains every other state.

Give it time. In the lab, a bucket joined its group within minutes, and every resource had its first backup within an hour. Allow up to a day before you look in Clumio's Tasks.

## 2. Restore one

In the Clumio console, restore one resource you protected, to a new name beside the original, never over it. For a database, Clumio creates a new instance or cluster. For a bucket, restore a folder to a new prefix.

When the restore task completes, open what came back and check it. The key the copy gets depends on the workload: see [What a restore needs from you](../docs/keys.md#what-a-restore-needs-from-you). In the lab, a restored Aurora cluster carried no `clumio-profile` tag, so the kit neither protects nor removes it: delete it when you're done. Check a restored RDS instance's tags: if it kept a profile tag, delete the copy or remove the tag when you're done. Restored S3 objects land in the bucket you name, and in a tagged bucket they're protected with it. A restored EC2 instance or EBS volume keeps the original's tags, profile tag included, so it joins that profile at Clumio's next discovery cycle and gets backed up and billed: delete it, or remove the tag, when you're done. Its Name tag is the original's, whatever name you gave in the console, so check the instance ID before you delete. A restored instance's root volume isn't deleted with the instance: delete it too.

## 3. Keep the evidence

Save what you saw, for whoever signs off. First delete the restored copy, or remove its profile tag: a copy that keeps its tag counts as a resource still waiting to join, and the report stays UNFINISHED. Then take the restore's task ID from Clumio's Tasks page:

```bash
tools/status.py --report --restore-task <task ID>
```

It writes two files from one read, in the repository's root folder: `status-<time>.json`, the evidence, and `status-<time>.html`, one page for sign-off. The page shows every resource and your own restore time, on your own data.

| Verdict | What it means | What to do |
|---|---|---|
| PROVEN | Every resource is OURS, and the restore completed | Check that the page's Resource line names the original you restored, and that you opened the copy. Keep both files |
| UNFINISHED | Something's missing | It lists what. Fix that, or wait, then run it again |
| UNKNOWN | AWS or Clumio didn't answer | Run it again |

Each run writes new files, so earlier evidence stays. The files name your AWS account, so keep them out of anything public; this repository's `.gitignore` skips them.

## Next

- Keep it: for production, call the same modules from your own repository, with your own state and CI: see [Production](../docs/production.md).
- Take a trial down: [Take a trial down](../docs/operate.md#take-a-trial-down).
