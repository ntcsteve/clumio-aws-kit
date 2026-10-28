# Does Clumio need our keys?

No. Clumio backed up and restored data under AWS-managed keys (AMK) and customer-managed keys (CMK) without anyone changing a key policy for it. Clumio's IAM role asks the AWS service to read the data, and the service uses the key in KMS. No key is handed over.

Two lab runs show it, each with raw AWS and Clumio answers you can check yourself.

## What was shown

| Workload | AWS-managed key | Customer-managed key | Restore |
|---|---|---|---|
| S3 | Backed up | Backed up, in the same backup | Byte for byte, same and another Region. The restored copy takes the target bucket's default encryption, even when the source object used a CMK |
| RDS | Backed up | Backed up | A new, available, encrypted instance, same and another Region |
| Aurora | Backed up | Backed up | The CMK cluster restored as a new cluster under the same customer-managed key, chosen by Clumio |
| EC2 | Backed up | Backed up | Encrypted under the key the restore names; without one, unencrypted |
| EBS on its own | Backed up | Backed up | Not restored in a lab run |

A customer-managed key's default policy, which lets IAM in the account decide, is enough: the 2026-10-28 run used one and changed nothing. A key policy that explicitly denies Clumio's role blocks it: the object isn't backed up, and Clumio reports it with AWS's error.

## The evidence

| Run | Covers | Where |
|---|---|---|
| 2026-10-28, this kit's own code | S3, Aurora, EC2 and EBS backed up under AMK and CMK, and RDS under AMK; the Aurora CMK cluster restored. An S3 restore was checked byte for byte live but not captured | [`proof/evidence/keys-lab-2026-10-28/`](../proof/evidence/keys-lab-2026-10-28): `protected-*` (each resource's key and Clumio's backup record) and `restored-*` (the restored cluster's key and tags) |
| 2026-10-25 to 27, an earlier lab | S3, RDS and EC2 under AMK and CMK, restores in two Regions, a key policy with an explicit Deny, and CloudTrail showing who called KMS | [get-started-clumio-byok](https://github.com/ntcsteve/get-started-clumio-byok/tree/4a6dc5d), commit `4a6dc5d`, with its own claims table and verifier |

Check the captures here, offline: `proof/verify-evidence.sh`. Each folder matches its `_sha256.txt`, and account numbers are masked. How the lab is built and captured: [proof/README.md](../proof/README.md).

## What a restore needs from you

- **S3:** if restored copies must use a customer-managed key, make that key the target bucket's default encryption before you restore.
- **EC2:** name the key in the restore, or the volumes come back unencrypted.
- **RDS and Aurora, same Region:** nothing. The restore keeps the source's key.
- **RDS, another Region:** name a key, a subnet group and a security group in that Region.

## What isn't proven

- Whether an S3 restore into a bucket whose default is a customer-managed key gets that key.
- An EBS volume on its own, restored.
- Bring your own key (BYOK). It binds a whole Clumio tenant to one key, for good, so it needs a tenant of its own to test.
