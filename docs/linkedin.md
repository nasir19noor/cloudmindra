# LinkedIn Post — Migrasi AWS Access Key ke OIDC

Saya baru saja membuang semua AWS access key dari GitHub Actions. Ini ceritanya.

Selama berbulan-bulan, workflow Terraform saya pakai AWS_ACCESS_KEY_ID dan AWS_SECRET_ACCESS_KEY yang disimpan sebagai repository secret. Berjalan? Iya. Aman? Tidak juga.

Masalahnya:

- Key tidak pernah expire — kalau bocor, game over
- Rotasi key berarti update secret di setiap repo satu per satu
- Siapa pun yang punya key bisa pakai dari mana saja
- CloudTrail tidak bisa kasih tahu workflow mana yang trigger API call

Jadi saya migrasi ke OIDC (OpenID Connect).

Bedanya? GitHub Actions minta token jangka pendek, kirim ke AWS STS, dan dapat credential sementara yang otomatis expire dalam 15 menit. Tidak ada key yang disimpan. Tidak ada yang perlu dirotasi.

Kelebihannya:

- Zero static credentials — tidak ada yang bisa bocor
- Auto-expire — credential mati sendiri setelah workflow selesai
- Scoped access — trust policy menentukan repo dan branch mana yang boleh assume role
- Full audit trail — CloudTrail log menunjukkan repo, branch, bahkan workflow run yang spesifik

Tapi prosesnya tidak semulus yang dibayangkan.

GitHub ternyata mengubah format OIDC token mereka. Claim "sub" sekarang menyertakan numeric ID yang tidak ada di dokumentasi AWS manapun. Trust policy yang ditulis dari contoh resmi? Gagal total. Error-nya: "Not authorized to perform sts:AssumeRoleWithWebIdentity."

Solusinya? Decode token-nya langsung dan cocokkan dengan trust policy karakter per karakter.

Saya dokumentasikan semuanya — dari setup, error yang saya temui, cara debugging, sampai workflow final yang sudah berjalan.

https://nasir.id/aws-oidc-github-actions

Kalau kamu masih pakai static access key di GitHub Actions, ini saatnya migrasi. Lebih aman, lebih bersih, dan setelah di-setup, zero maintenance.

#AWS #GitHubActions #OIDC #DevOps #Terraform #CloudSecurity #InfrastructureAsCode
