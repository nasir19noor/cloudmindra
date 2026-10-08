# Threads — Migrasi AWS Access Key ke OIDC

## Post 1

Saya baru buang semua AWS access key dari GitHub Actions.

Selama ini pakai static key yang disimpan di repository secret. Masalahnya? Key nggak pernah expire, susah dirotasi, dan kalau bocor — akun AWS kamu terbuka lebar.

Ini cerita migrasi saya ke OIDC. Thread 🧵

## Post 2

Dulu workflow saya pakai AWS_ACCESS_KEY_ID dan AWS_SECRET_ACCESS_KEY.

Kelemahannya:
→ Key hidup selamanya
→ Rotasi = update secret di semua repo
→ Siapa pun yang punya key bisa pakai dari mana saja
→ Audit susah, CloudTrail nggak tahu workflow mana yang panggil

## Post 3

Solusinya: OIDC (OpenID Connect).

GitHub Actions minta token sementara → kirim ke AWS STS → dapat credential yang expire dalam 15 menit.

Nggak ada key yang disimpan. Nggak ada yang perlu dirotasi. Selesai workflow, credential mati sendiri.

## Post 4

Kelebihan OIDC:

✅ Zero static credentials — nggak ada yang bisa bocor
✅ Auto-expire — credential otomatis mati
✅ Scoped access — cuma repo & branch tertentu yang boleh akses
✅ Full audit — CloudTrail tahu persis repo mana yang trigger

## Post 5

Tapi setup-nya nggak semulus yang dibayangkan.

Error pertama: isi field GitHub organization pakai URL lengkap. Salah. Cukup username aja.

Error kedua: "Not authorized to perform sts:AssumeRoleWithWebIdentity" — padahal semua udah benar.

## Post 6

Ternyata GitHub diam-diam ubah format OIDC token.

Claim "sub" sekarang ada numeric ID:
repo:nasir19noor@330575/cloudmindra@1409520431

Trust policy saya expect:
repo:nasir19noor/*

Format beda = nggak match = gagal.

## Post 7

Cara debug-nya: decode langsung OIDC token di workflow.

Tambah step ini, jalankan sekali, dan lihat claim "sub" yang sebenarnya dikirim GitHub. Jangan tulis trust policy dari dokumentasi doang — verifikasi dulu.

## Post 8

Setelah fix trust policy sesuai format token yang sebenarnya, workflow langsung jalan.

Sekarang nggak ada lagi:
❌ AWS_ACCESS_KEY_ID
❌ AWS_SECRET_ACCESS_KEY
❌ Key yang perlu dirotasi

Semua otomatis, aman, dan zero maintenance.

## Post 9

Saya tulis lengkap step-by-step nya — dari setup, error, debugging, sampai workflow final.

Baca di: https://nasir.id/aws-oidc-github-actions

Kalau kamu masih pakai static access key di GitHub Actions, saatnya pindah ke OIDC. 🔐

#AWS #GitHubActions #OIDC #DevOps
