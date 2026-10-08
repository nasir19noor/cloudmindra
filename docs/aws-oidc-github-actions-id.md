# Migrasi dari AWS Access Key ke OIDC di GitHub Actions

Static AWS access key di GitHub Actions adalah bom waktu. Saya baru saja melakukan migrasi workflow Terraform dari `AWS_ACCESS_KEY_ID` dan `AWS_SECRET_ACCESS_KEY` yang tersimpan sebagai secret ke OpenID Connect (OIDC) — dan menemui beberapa kendala di sepanjang proses. Berikut alasan saya melakukannya, cara setup-nya, dan bagaimana saya men-debug error yang muncul.

## Kenapa Saya Berhenti Menggunakan Static Access Key

Selama berbulan-bulan, workflow GitHub Actions saya melakukan autentikasi ke AWS menggunakan IAM user access key yang disimpan sebagai repository secret. Cara ini memang berjalan, tapi masalahnya terus mengganggu:

**Access key tidak pernah kedaluwarsa.** Begitu dibuat, access key akan hidup selamanya kecuali Anda secara manual melakukan rotasi atau menghapusnya. Jika key bocor — melalui log, fork, atau action yang terkompromi — penyerang mendapat akses permanen ke akun AWS Anda.

**Rotasi key itu merepotkan.** Rotasi key berarti harus update secret di setiap repository yang menggunakannya, menjalankan ulang workflow untuk memastikan tidak ada yang rusak, dan menonaktifkan key lama setelah yakin key baru bekerja di mana-mana. Kalikan itu dengan beberapa repo dan prosesnya menjadi pekerjaan yang terus Anda tunda.

**Cakupannya terlalu luas.** IAM user dengan key-nya ada secara independen dari workflow mana pun. Tidak ada cara bawaan untuk mengatakan "credential ini hanya boleh dipakai kalau dipanggil dari repo tertentu di branch tertentu." Anda bisa membatasi IAM policy, tapi key itu sendiri bersifat portabel — siapa pun yang memilikinya bisa menggunakannya dari mana saja.

**Audit itu menyulitkan.** CloudTrail log menunjukkan IAM user mana yang melakukan API call, tapi tidak memberitahu repository atau workflow mana yang memicunya. Ketika ada sesuatu yang tidak terduga muncul di akun AWS Anda, melacaknya kembali ke GitHub Actions run tertentu membutuhkan kerja detektif.

OIDC menyelesaikan semua masalah ini. Alih-alih menyimpan credential permanen, GitHub Actions meminta token jangka pendek dari OIDC provider GitHub, menyerahkannya ke AWS STS, dan menerima credential sementara yang kedaluwarsa dalam hitungan menit. Tidak ada secret yang perlu dirotasi, tidak ada key yang bisa bocor, dan CloudTrail log menunjukkan dengan tepat repo dan branch mana yang meng-assume role tersebut.

## Cara Kerja OIDC Antara GitHub dan AWS

Alurnya cukup sederhana:

```
GitHub Actions                          AWS
    |                                    |
    |  1. Minta OIDC token dari          |
    |     endpoint token GitHub          |
    |                                    |
    |  2. Kirim token ke AWS STS         |
    |     (AssumeRoleWithWebIdentity)    |
    |                                    |
    |  3. Terima credential sementara    |
    |     (kedaluwarsa dalam ~15 menit)  |
    |                                    |
```

GitHub bertindak sebagai identity provider. AWS mempercayai OIDC provider GitHub dan menerbitkan credential sementara ketika claim token (repository, branch, dll.) sesuai dengan trust policy IAM role. Tidak ada static secret yang terlibat.

## Cara Setup

### 1. Tambahkan GitHub sebagai Identity Provider di AWS

Buka **IAM → Identity providers → Add provider**:

- **Provider type:** OpenID Connect
- **Provider URL:** `https://token.actions.githubusercontent.com`
- **Audience:** `sts.amazonaws.com`

Klik **Get thumbprint**, lalu **Add provider**. Anda hanya perlu melakukan ini sekali per akun AWS — semua repo di bawah akun GitHub yang sama berbagi provider ini.

### 2. Buat IAM Role

Buka **IAM → Roles → Create role**:

- **Trusted entity type:** Web identity
- **Identity provider:** `token.actions.githubusercontent.com`
- **Audience:** `sts.amazonaws.com`
- **GitHub organization:** Username GitHub Anda (contoh: `nasir19noor`)
- **GitHub repository:** `*` (atau nama repo tertentu)
- **GitHub branch:** `*`

Lampirkan policy yang dibutuhkan workflow Anda. Saya menggunakan `AdministratorAccess` karena role ini mengelola semua infrastruktur AWS melalui Terraform — VPC, EC2, RDS, S3, dan lainnya. Trust policy (bukan permission policy) yang membatasi siapa yang bisa meng-assume role ini.

### 3. Update Workflow

Ganti konfigurasi static key:

```yaml
# Sebelum (static key)
- name: Configure AWS Credentials
  uses: aws-actions/configure-aws-credentials@v4
  with:
    aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
    aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
    aws-region: ap-southeast-1
```

Dengan OIDC:

```yaml
# Sesudah (OIDC)
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

Blok `permissions` sangat penting — tanpa `id-token: write`, GitHub tidak akan menerbitkan OIDC token dan step tersebut gagal secara diam-diam.

## Error yang Saya Temui (dan Cara Memperbaikinya)

### Error 1: Validasi Field GitHub Organization

Saat membuat IAM role melalui wizard AWS Console, field **GitHub organization** meminta nama akun GitHub Anda. Awalnya saya memasukkan URL lengkap `https://github.com/nasir19noor` — yang menghasilkan error validasi.

**Solusi:** Masukkan hanya username: `nasir19noor`, bukan URL lengkap.

### Error 2: "Not authorized to perform sts:AssumeRoleWithWebIdentity"

Setelah semua di-setup, workflow saya gagal dengan error:

```
Error: Not authorized to perform sts:AssumeRoleWithWebIdentity
```

Saya sudah memeriksa ulang trust policy, audience, role ARN — semuanya terlihat benar. Trust policy memiliki kondisi ini:

```json
"StringLike": {
    "token.actions.githubusercontent.com:sub": "repo:nasir19noor/*"
}
```

Seharusnya ini cocok dengan repo mana pun di bawah akun saya. Tapi tetap tidak berhasil.

### Debugging dengan OIDC Token

Untuk mencari tahu apa yang salah, saya menambahkan step debug ke workflow yang mendekode claim OIDC token yang sebenarnya:

```yaml
- name: Debug OIDC Token
  run: |
    TOKEN=$(curl -s -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
      "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=sts.amazonaws.com" | jq -r '.value')
    echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '{sub, aud, iss}'
```

Output-nya mengungkap masalahnya:

```json
{
  "sub": "repo:nasir19noor@330575/cloudmindra@1409520431:ref:refs/heads/main",
  "aud": "sts.amazonaws.com",
  "iss": "https://token.actions.githubusercontent.com"
}
```

Claim `sub` menyertakan **numeric ID** — `@330575` untuk user dan `@1409520431` untuk repository. Ini adalah format OIDC token GitHub yang lebih baru. Pattern trust policy saya `repo:nasir19noor/*` mengharapkan `sub` berbentuk `repo:nasir19noor/cloudmindra:ref:refs/heads/main`, tapi nilai sebenarnya adalah `repo:nasir19noor@330575/cloudmindra@1409520431:ref:refs/heads/main`.

Wildcard `*` setelah `nasir19noor/` tidak pernah cocok karena `nasir19noor@330575/` tidak cocok dengan `nasir19noor/`.

### Solusinya

Update kondisi trust policy untuk memperhitungkan numeric user ID:

```json
"StringLike": {
    "token.actions.githubusercontent.com:sub": "repo:nasir19noor@330575/*"
}
```

Ini cocok dengan format claim `sub` yang sebenarnya. Setelah mengupdate trust policy di AWS Console, workflow berhasil melakukan autentikasi.

**Jika Anda baru pertama kali setup**, tambahkan step debug ke workflow Anda, jalankan sekali, dan periksa claim `sub` apa yang sebenarnya dikirim GitHub. Jangan berasumsi formatnya — verifikasi langsung.

## Checklist Troubleshooting

Jika autentikasi OIDC gagal, periksa hal-hal berikut secara berurutan:

1. **Blok `permissions` ada** — Workflow Anda harus memiliki `id-token: write` dan `contents: read` di level top atau level job.

2. **Identity provider sudah ada** — Buka IAM → Identity providers dan pastikan `token.actions.githubusercontent.com` terdaftar dengan audience `sts.amazonaws.com`.

3. **Role ARN benar** — IAM role ARN menggunakan double colon sebelum account ID: `arn:aws:iam::647459380434:role/github-actions`. Ini benar — IAM adalah layanan global, sehingga field region kosong.

4. **Trust policy cocok dengan claim `sub` yang sebenarnya** — Ini adalah titik kegagalan paling umum. Tambahkan step debug di atas, dekode token-nya, dan bandingkan nilai `sub` dengan kondisi `StringLike` trust policy Anda karakter per karakter.

5. **Audience cocok** — `StringEquals` trust policy untuk `aud` harus `sts.amazonaws.com`, sesuai dengan yang diminta oleh action `configure-aws-credentials`.

## Workflow Final

Setelah memperbaiki semuanya, berikut workflow yang sudah berjalan:

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

Tidak ada `AWS_ACCESS_KEY_ID`. Tidak ada `AWS_SECRET_ACCESS_KEY`. Tidak ada key yang perlu dirotasi. Credential kedaluwarsa secara otomatis setelah setiap run.

## Penutup

Migrasi ini memakan waktu sekitar satu jam, yang sebagian besar dihabiskan untuk men-debug ketidakcocokan claim `sub`. Poin penting yang bisa diambil: **selalu dekode dan periksa OIDC token yang sebenarnya sebelum menulis trust policy Anda.** Format token GitHub menyertakan numeric ID yang tidak didokumentasikan secara menonjol, dan trust policy yang ditulis hanya dari contoh dokumentasi akan gagal secara diam-diam.

Jika Anda masih menggunakan static access key di GitHub Actions, segera lakukan migrasi. OIDC lebih aman, lebih mudah di-audit, dan setelah di-setup, tidak membutuhkan maintenance sama sekali.
