# Step 3: Prove it

[ResOps](https://www.commvault.com/explore/resilience-operations) asks for evidence rather than assumptions: a backup counts once you've seen it restore. Three checks, run from the repository's root folder.

## 1. Who protects each resource

```bash
tools/status.py
```

It lists every resource tagged `clumio-profile` (volumes on their own: `clumio-volume-profile`), who protects it, and its last backup. It reads AWS and Clumio and changes nothing. The first line checks the connection. Right after step 2, resources show NOT_YET or WAITING; after each first backup, PROTECTED. [Read tools/status.py](../docs/operate.md#read-toolsstatuspy) explains every other state.

Give it time. In the lab, a bucket joined its group within minutes, and every resource had its first backup within an hour. Allow up to a day before you look in Clumio's Tasks.

## 2. Restore one

In the Clumio console, restore one resource you protected, to a new name beside the original, never over it. Open the resource under **AWS**, click its backup's date, and choose a SecureVault backup. If the date lists several, choose **SecureVault Standard**, not Archive or point-in-time recovery. Labels are as seen in the lab:

| Workload | In the console |
|---|---|
| RDS | **Restore**, then **Default**. Clumio creates a new instance and fills in the subnet group, security group, key and tags. Replace the suggested name, or note it |
| Aurora | As RDS. Clumio creates a new cluster: set **Aurora cluster name** |
| EC2 | **Restore as EC2 instance**, then **Basic restore** |
| EBS | **Restore EBS volume**. The source's key and tags are filled in |
| S3 | Open the bucket. **Restore**, then **Restore prefix/buckets**, then **Custom**, not **Source**, which restores to the original location. Set the account, Region and bucket, and a new prefix, such as `restored/`. To keep the copy, use a bucket you'll keep |

When the restore task completes, open what came back and check it: it's available, under the key you expect, and holds what you expect. The key depends on the workload: see [What a restore needs from you](../docs/keys.md#what-a-restore-needs-from-you). Check a restored instance's network settings, including whether it has a public IP.

A restored database, instance or volume keeps the original's tags, profile tag included, so it joins that profile at Clumio's next discovery cycle and gets backed up and billed. When you've checked it, delete it or remove the tag. Restored S3 objects land in the bucket you name, and in a tagged bucket they're protected with it. A restored instance's Name tag is the original's, whatever name you gave in the console, so check the instance ID before you delete. Its root volume isn't deleted with it: delete that too.

## 3. Keep the evidence

Save what you saw, for whoever signs off. First, if the restored copy carries a profile tag, delete the copy or remove the tag: a tagged copy counts as a resource still waiting to join, and the report stays UNFINISHED. Then take the restore's task ID from Clumio's Tasks page:

```bash
tools/status.py --report --restore-task <task ID>
```

It writes two files from one read, in the repository's root folder: `status-<time>.json`, the evidence, and `status-<time>.html`, one page for sign-off. The page shows every resource and your own restore time, on your own data.

| Verdict | What it means | What to do |
|---|---|---|
| PROVEN | Every resource is PROTECTED, and a restore of one of them completed | Keep both files |
| UNFINISHED | Something's missing | It lists what. Fix that, or wait, then run it again |
| UNKNOWN | Couldn't read from AWS or Clumio | Run it again |

The page lists each policy's frequency and retention. To measure the restore against your limit, add `--recovery-target-minutes <minutes>`: the report says MET or MISSED beside the restore time. Your limit is what [ResOps](https://www.commvault.com/explore/resilience-operations) calls an impact tolerance. MISSED doesn't change the verdict: the restore worked, and what to do about the time is your call.

Run the report again after each restore test: each run writes new files, so earlier evidence stays. The files name your AWS account, so keep them out of anything public; this repository's `.gitignore` skips them.

## 4. Optional: restore with the source gone

A controlled test of what the copy is for. Backups live outside your account, so they outlast what they copied. To see that with S3, in a test account, delete a test bucket after you've run the report, then bring it back. The report comes first because a deleted bucket leaves it UNFINISHED. Proven live on S3 on 2026-11-02.

1. Open the protection group: under **AWS**, **Protect**, **S3**, **Protection Groups**. The deleted bucket's own page no longer links to its backups.
2. In the **All buckets** drop-down, select the deleted bucket. With **All buckets** left as it is, a restore covers only the buckets still in the group.
3. Click the backup's date, then follow the S3 row above, into a bucket that exists.

## Next

- Go live: a fresh clone in your production account: see [Production](../docs/production.md).
- Take a trial down: [Take a trial down](../README.md#take-a-trial-down).
