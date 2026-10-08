# Migrating from AWS Access Keys to OIDC in GitHub Actions

Static AWS access keys in GitHub Actions are a ticking time bomb. I recently migrated my Terraform workflows from long-lived `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` secrets to OpenID Connect (OIDC) — and hit a few walls along the way. Here's why I did it, how I set it up, and how I debugged the errors.

## Why I Stopped Using Static Access Keys

For months, my GitHub Actions workflows authenticated to AWS using IAM user access keys stored as repository secrets. It worked, but the problems kept nagging me:

**They never expire.** Once created, access keys live forever unless you manually rotate or delete them. If a key leaks — through a log, a fork, or a compromised action — an attacker has persistent access to your AWS account.

**They're hard to rotate.** Rotating keys means updating secrets in every repository that uses them, rerunning workflows to verify nothing broke, and deactivating the old key only after you're confident the new one works everywhere. Multiply that by several repos and it becomes a chore you keep postponing.

**They're overly broad.** An IAM user with keys exists independently of any workflow. There's no built-in way to say "these credentials should only work when called from this specific repo on this specific branch." You can restrict the IAM policy, but the keys themselves are portable — anyone with them can use them from anywhere.

**Auditing is painful.** CloudTrail logs show which IAM user made API calls, but they don't tell you which repository or workflow triggered it. When something unexpected shows up in your AWS account, tracing it back to a specific GitHub Actions run requires detective work.

OIDC solves all of these. Instead of storing permanent credentials, GitHub Actions requests a short-lived token from GitHub's OIDC provider, presents it to AWS STS, and receives temporary credentials that expire in minutes. No secrets to rotate, no keys to leak, and CloudTrail logs show exactly which repo and branch assumed the role.

## How OIDC Works Between GitHub and AWS

The flow is straightforward:

```
GitHub Actions                          AWS
    |                                    |
    |  1. Request OIDC token from        |
    |     GitHub's token endpoint        |
    |                                    |
    |  2. Present token to AWS STS       |
    |     (AssumeRoleWithWebIdentity)    |
    |                                    |
    |  3. Receive temporary credentials  |
    |     (expire in ~15 minutes)        |
    |                                    |
```

GitHub acts as the identity provider. AWS trusts GitHub's OIDC provider and issues temporary credentials when the token's claims (repository, branch, etc.) match the IAM role's trust policy. No static secrets involved.

## Setting It Up

### 1. Add GitHub as an Identity Provider in AWS

Go to **IAM → Identity providers → Add provider**:

- **Provider type:** OpenID Connect
- **Provider URL:** `https://token.actions.githubusercontent.com`
- **Audience:** `sts.amazonaws.com`

Click **Get thumbprint**, then **Add provider**. You only need to do this once per AWS account — all repos under the same GitHub account share this provider.

### 2. Create an IAM Role

Go to **IAM → Roles → Create role**:

- **Trusted entity type:** Web identity
- **Identity provider:** `token.actions.githubusercontent.com`
- **Audience:** `sts.amazonaws.com`
- **GitHub organization:** Your GitHub username (e.g., `nasir19noor`)
- **GitHub repository:** `*` (or a specific repo name)
- **GitHub branch:** `*`

Attach whatever policy your workflows need. I used `AdministratorAccess` because this role manages all AWS infrastructure through Terraform — VPC, EC2, RDS, S3, and more. The trust policy (not the permission policy) is what restricts who can assume this role.

### 3. Update the Workflow

Replace the static key configuration:

```yaml
# Before (static keys)
- name: Configure AWS Credentials
  uses: aws-actions/configure-aws-credentials@v4
  with:
    aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
    aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
    aws-region: ap-southeast-1
```

With OIDC:

```yaml
# After (OIDC)
permissions:
  id-token: write
  contents: read

steps:
  - name: Configure AWS Credentials (OIDC)
    uses: aws-actions/configure-aws-credentials@v4
    with:
      role-to-assume: arn:aws:iam::YOUR_ACCOUNT_ID:role/github-actions
      aws-region: ap-southeast-1
```

The `permissions` block is critical — without `id-token: write`, GitHub won't issue the OIDC token and the step silently fails.

## The Errors I Hit (and How I Fixed Them)

### Error 1: GitHub Organization Field Validation

When creating the IAM role through the AWS Console wizard, the **GitHub organization** field asks for your GitHub account name. I initially entered the full URL `https://github.com/nasir19noor` — which threw a validation error.

**Fix:** Enter just the username: `nasir19noor`, not the full URL.

### Error 2: "Not authorized to perform sts:AssumeRoleWithWebIdentity"

After setting everything up, my workflow failed with:

```
Error: Not authorized to perform sts:AssumeRoleWithWebIdentity
```

I double-checked the trust policy, the audience, the role ARN — everything looked correct. The trust policy had this condition:

```json
"StringLike": {
    "token.actions.githubusercontent.com:sub": "repo:nasir19noor/*"
}
```

This should match any repo under my account. But it didn't work.

### Debugging with the OIDC Token

To figure out what was going wrong, I added a debug step to the workflow that decodes the actual OIDC token claims:

```yaml
- name: Debug OIDC Token
  run: |
    TOKEN=$(curl -s -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
      "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=sts.amazonaws.com" | jq -r '.value')
    echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '{sub, aud, iss}'
```

The output revealed the problem:

```json
{
  "sub": "repo:nasir19noor@330575/cloudmindra@1409520431:ref:refs/heads/main",
  "aud": "sts.amazonaws.com",
  "iss": "https://token.actions.githubusercontent.com"
}
```

The `sub` claim includes **numeric IDs** — `@330575` for the user and `@1409520431` for the repository. This is a newer GitHub OIDC token format. My trust policy pattern `repo:nasir19noor/*` expected the `sub` to look like `repo:nasir19noor/cloudmindra:ref:refs/heads/main`, but the actual value was `repo:nasir19noor@330575/cloudmindra@1409520431:ref:refs/heads/main`.

The wildcard `*` after `nasir19noor/` never matched because `nasir19noor@330575/` doesn't match `nasir19noor/`.

### The Fix

Update the trust policy condition to account for the numeric user ID:

```json
"StringLike": {
    "token.actions.githubusercontent.com:sub": "repo:nasir19noor@330575/*"
}
```

This matches the actual `sub` claim format. After updating the trust policy in the AWS Console, the workflow authenticated successfully.

**If you're setting this up for the first time**, add the debug step to your workflow, run it once, and check what `sub` claim GitHub actually sends. Don't assume the format — verify it.

## The Troubleshooting Checklist

If OIDC authentication fails, check these in order:

1. **`permissions` block exists** — Your workflow must have `id-token: write` and `contents: read` at the top level or job level.

2. **Identity provider exists** — Go to IAM → Identity providers and confirm `token.actions.githubusercontent.com` is listed with audience `sts.amazonaws.com`.

3. **Role ARN is correct** — IAM role ARNs use a double colon before the account ID: `arn:aws:iam::647459380434:role/github-actions`. This is correct — IAM is a global service, so the region field is empty.

4. **Trust policy matches the actual `sub` claim** — This is the most common failure point. Add the debug step above, decode the token, and compare the `sub` value against your trust policy's `StringLike` condition character by character.

5. **Audience matches** — The trust policy's `StringEquals` for `aud` must be `sts.amazonaws.com`, matching what the `configure-aws-credentials` action requests.

## Final Workflow

After fixing everything, here's the working workflow:

```yaml
name: 'Terraform Apply'

on:
  push:
    branches:
      - main
    paths:
      - 'cloudflare/**.tf'
      - 'cloudflare/**.tfvars'
      - '.github/workflows/cloudflare-apply.yml'

permissions:
  id-token: write
  contents: read

jobs:
  terraform-apply:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Configure AWS Credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_IAM_ROLE_ARN }}
          aws-region: ap-southeast-1

      - name: Verify AWS Identity
        run: aws sts get-caller-identity

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: '1.11.4'

      - name: Terraform Init
        working-directory: cloudflare
        run: terraform init

      - name: Terraform Plan
        working-directory: cloudflare
        run: terraform plan -no-color

      - name: Terraform Apply
        working-directory: cloudflare
        run: terraform apply -auto-approve
```

No `AWS_ACCESS_KEY_ID`. No `AWS_SECRET_ACCESS_KEY`. No keys to rotate. Credentials expire automatically after each run.

## Wrapping Up

The migration took about an hour, most of which was spent debugging the `sub` claim mismatch. The key takeaway: **always decode and inspect the actual OIDC token before writing your trust policy.** GitHub's token format includes numeric IDs that aren't documented prominently, and a trust policy written from documentation examples alone will fail silently.

If you're still using static access keys in GitHub Actions, make the switch. OIDC is more secure, easier to audit, and once set up, requires zero maintenance.
