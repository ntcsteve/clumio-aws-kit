# Does Clumio need our keys?

You don't hand over a key, and you don't change a key policy. Clumio backed up and restored data under AWS-managed keys (AMK) and customer-managed keys (CMK) as they were. Your keys stay in KMS, and you stay in control: Clumio's role in your account uses them through AWS services, and your key policies decide which keys it can reach. To keep Clumio away from a key, deny Clumio's role in that key's policy: the earlier lab run below tested that, and Clumio reports the object it couldn't back up. `0-check/preview/preview.sh` lists every permission Clumio's role holds, KMS included, before anything is created.

Two lab runs show it, each with raw AWS and Clumio answers you can check yourself.

## What was shown

| Workload | AWS-managed key | Customer-managed key | Restore |
|---|---|---|---|
| S3 | Backed up | Backed up, in the same backup | Byte for byte, same and another Region. The restored copy takes the target bucket's default encryption, even when the source object used a CMK |
| RDS | Backed up | Backed up | A new, available, encrypted instance, same and another Region |
| Aurora | Backed up | Backed up | The CMK cluster restored as a new cluster under the same customer-managed key, chosen by Clumio |
| EC2 | Backed up | Backed up | A new instance. Its key depends on how you restore: see [What a restore needs from you](#what-a-restore-needs-from-you) |
| EBS on its own | Backed up | Backed up | A new volume, restored in the Clumio console. Its key: see [What a restore needs from you](#what-a-restore-needs-from-you) |

AWS doesn't let anyone share an RDS snapshot under an AWS-managed key, and Clumio doesn't. It copies the snapshot under a key it can share, and shares only the copy: [the CloudTrail record](https://github.com/ntcsteve/get-started-clumio-byok/blob/4a6dc5d/docs/PROOF.md#c9-rds-what-clumio-did-and-who-did-it).

A customer-managed key's default policy, which lets IAM in the account decide, is enough: the 2026-10-28 run used one and changed nothing. A key policy that explicitly denies Clumio's role blocks it: the object isn't backed up, and Clumio reports it with AWS's error.

## The evidence

| Run | Covers | Where |
|---|---|---|
| 2026-10-28, this kit's own code | S3, Aurora, EC2 and EBS backed up under AMK and CMK, and RDS under AMK; the Aurora CMK cluster restored. An S3 restore was checked byte for byte live but not captured | [`proof/evidence/keys-lab-2026-10-28/`](../proof/evidence/keys-lab-2026-10-28): `protected-*` (each resource's key and Clumio's backup record) and `restored-*` (the restored cluster's key and tags) |
| 2026-10-25 to 27, an earlier lab | S3, RDS and EC2 under AMK and CMK, restores in two Regions, a key policy with an explicit Deny, and CloudTrail showing who called KMS | [get-started-clumio-byok](https://github.com/ntcsteve/get-started-clumio-byok/tree/4a6dc5d), commit `4a6dc5d`, with its own claims table and verifier |

Check the captures here, offline: `proof/verify-evidence.sh`. Each folder matches its `_sha256.txt`, and account numbers are masked. How the lab is built and captured: [proof/README.md](../proof/README.md).

## What a restore needs from you

- **S3:** restored copies take the target bucket's default encryption (seen live). If they must use a customer-managed key, make it the bucket's default before you restore, then check a restored object.
- **EC2 and EBS:** the Clumio console's restore fills in the source's key, and the copy comes back under it (seen live on this kit with an AWS-managed key). Through Clumio's API, always name the key.
- **RDS and Aurora, same Region:** nothing. The restore keeps the source's key.
- **RDS, another Region:** name a key, a subnet group and a security group in that Region.

## Not covered here

- Whether an S3 restore into a bucket whose default is a customer-managed key gets that key.
- Bring your own key (BYOK). It's a tenant-wide choice, made with Clumio, so these runs don't include it.
