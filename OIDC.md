# AWS OIDC Configuration for GitHub Actions

This guide configures GitHub Actions to authenticate with AWS using OpenID Connect (OIDC) instead of static access keys.

**Repo:** `nasir19noor/cloudmindra`
**AWS Account:** `647459380434`
**Region:** `ap-southeast-1`
**State Bucket:** `cloudmindra.com`

---

## Step 1 — Add GitHub as an Identity Provider in AWS

1. Go to **AWS Console > IAM > Identity providers > Add provider**
2. Select **OpenID Connect**
3. Fill in:
   - **Provider URL:** `https://token.actions.githubusercontent.com`
   - **Audience:** `sts.amazonaws.com`
4. Click **Get thumbprint**, then **Add provider**

> If the provider already exists from another repo, skip this step.

---

## Step 2 — Create an IAM Role

1. Go to **IAM > Roles > Create role**
2. Select **Web identity** as trusted entity type
3. Choose:
   - **Identity provider:** `token.actions.githubusercontent.com`
   - **Audience:** `sts.amazonaws.com`
4. Fill in the condition fields (use plain names, NOT full URLs):
   - **GitHub organization:** `nasir19noor`
   - **GitHub repository:** `*` (all repos)
   - **GitHub branch:** `*` (all branches)
5. Click **Next**, attach the AWS managed policy **`AdministratorAccess`**
6. Name the role: `github-actions-cloudmindra`
7. Create the role

> **Note:** The GitHub organization field accepts only the account/org name (e.g. `nasir19noor`), not the full URL. Entering `https://github.com/nasir19noor` will fail with a validation error.

> AdministratorAccess is used because this repo will manage all AWS resources (VPC, EC2, RDS, S3, etc.) via Terraform. The trust policy in Step 3 restricts who can assume this role to only this repo's main branch.

---

## Step 3 — Edit the Trust Policy

After creation, go to the role > **Trust relationships** > **Edit trust policy** and replace with:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::647459380434:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:nasir19noor/*"
        }
      }
    }
  ]
}
```

This allows any repo under `nasir19noor` on any branch to assume the role.

---

## Step 4 — Verify

Push the workflow changes and check the GitHub Actions run:

- **Configure AWS Credentials (OIDC)** step should succeed
- **Verify AWS Identity** step should show the assumed role:

```
{
    "UserId": "AROA...:GitHubActions",
    "Account": "647459380434",
    "Arn": "arn:aws:sts::647459380434:assumed-role/github-actions-cloudmindra/GitHubActions"
}
```

---

## Step 5 — Cleanup

After confirming OIDC works, remove the old static key secrets from the repo:

1. Go to **GitHub > cloudmindra > Settings > Secrets and variables > Actions**
2. Delete `AWS_ACCESS_KEY_ID`
3. Delete `AWS_SECRET_ACCESS_KEY`
4. Deactivate the IAM user access keys in AWS Console

---

## How It Works

```
GitHub Actions                        AWS
    |                                  |
    |-- Request OIDC token from -----> |
    |   GitHub's token endpoint        |
    |                                  |
    |-- Present token to STS --------> |
    |   AssumeRoleWithWebIdentity      |
    |                                  |
    |<-- Temporary credentials --------|
    |   (15 min default, no keys       |
    |    stored in secrets)            |
```

- No static keys stored in GitHub secrets
- Credentials are temporary (auto-expire)
- Trust is scoped to specific repo + branch
- AWS CloudTrail logs show which repo/workflow assumed the role

---

## Files Changed

| File | Change |
|------|--------|
| `.github/workflows/cloudflare-apply.yml` | Replaced static key auth with `aws-actions/configure-aws-credentials@v4` OIDC |
| `cloudflare/backend.tf` | Updated state bucket to `cloudmindra.com` |
