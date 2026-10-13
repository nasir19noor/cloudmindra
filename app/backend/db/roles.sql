-- One-time setup of per-module database roles (DESIGN.md §6.1).
-- Run as a Postgres superuser on the database server, choosing strong passwords:
--
--   psql -d <your database> \
--        -v core_pw="'…'" -v uptime_pw="'…'" -v site_pw="'…'" \
--        -f db/roles.sql
--
-- Then add to the backend .env (and upload it to S3):
--   DATABASE_URL_CORE=postgresql://core_svc:…@localhost:5432/cloudmindra
--   DATABASE_URL_UPTIME=postgresql://uptime_svc:…@localhost:5432/cloudmindra
--   DATABASE_URL_SITE=postgresql://site_svc:…@localhost:5432/cloudmindra
--
-- DATABASE_URL stays the migration/owner role. Table privileges are granted by
-- migrate.py on every start, so this script only creates the logins.

CREATE ROLE core_svc   LOGIN PASSWORD :core_pw;
CREATE ROLE uptime_svc LOGIN PASSWORD :uptime_pw;
CREATE ROLE site_svc   LOGIN PASSWORD :site_pw;

-- :"DBNAME" is psql's built-in name of the database you connected to with -d
GRANT CONNECT ON DATABASE :"DBNAME" TO core_svc, uptime_svc, site_svc;
