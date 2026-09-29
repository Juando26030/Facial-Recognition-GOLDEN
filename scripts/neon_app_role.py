"""Rol `golden_app` con mínimo privilegio en Neon: la APP se conecta con él (lee y escribe datos, nada más); las MIGRACIONES y los respaldos
usan el rol dueño (`golden_db_owner`, conexión directa). Idempotente: crear el rol si falta y (re)aplicar permisos se puede repetir.

    # staging (en este PC): lee la conexión DIRECTA del dueño de .env.staging y deja DATABASE_URL = golden_app por el pooler
    python scripts/neon_app_role.py --env-file .env.staging

    # producción (Cloud Shell): lee y escribe en Secret Manager, sin que la cadena pase por la pantalla
    python scripts/neon_app_role.py --owner-secret golden-db-owner-url-production --app-secret golden-database-url-production

    --rotate       cambia la contraseña de golden_app (y reescribe DATABASE_URL / el secreto)
    --grants-only  solo vuelve a aplicar los permisos (lo usa scripts/migrate_db_to_neon.py después de restaurar)

La contraseña se genera aquí (256 bits), viaja al servidor por TLS (Neon no acepta un verificador SCRAM precalculado) y solo se escribe
en el archivo o en el secreto: nunca se imprime."""
import argparse
import os
import secrets
import subprocess
import sys
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg2
from psycopg2 import sql

APP_ROLE = "golden_app"


def grant_sql(owner: str, db: str) -> list:
    """Permisos de la app: DML sobre todo lo que existe y lo que creen las migraciones futuras (privilegios por defecto del dueño)."""
    r, o = sql.Identifier(APP_ROLE), sql.Identifier(owner)
    return [
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db), r),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(r),
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(r),
        sql.SQL("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}").format(r),
        sql.SQL("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {}").format(r),
        sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(o, r),
        sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {}").format(o, r),
        sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO {}").format(o, r),
    ]


def apply_grants(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT current_user, current_database()")
        owner, db = cur.fetchone()
        for stmt in grant_sql(owner, db):
            cur.execute(stmt)
    conn.commit()


def ensure_role(conn, rotate: bool, role: str = APP_ROLE):
    """Crea el rol si falta (o le cambia la contraseña con rotate). Devuelve la contraseña nueva, o None si no se tocó."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        exists = cur.fetchone() is not None
        if exists and not rotate:
            return None
        password = secrets.token_urlsafe(32)
        # Neon exige la contraseña en claro (la sincroniza con su plano de control; rechaza un verificador SCRAM): viaja por TLS.
        if exists:
            # Rotación: SOLO login y contraseña. En Postgres 16+ un ALTER ROLE que menciona (NO)SUPERUSER, aunque no cambie nada, exige ser
            # superusuario, y el dueño en Neon no lo es. Que siga sin privilegios lo comprueba check_attributes() después.
            cur.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
        else:
            cur.execute(sql.SQL("CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)))
    conn.commit()
    return password


def check_attributes(conn, role: str = APP_ROLE) -> None:
    """El rol de la app puede entrar y NO es superusuario ni crea bases ni roles (pg_roles). Si no, se detiene con error."""
    with conn.cursor() as cur:
        cur.execute("SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = %s", (role,))
        row = cur.fetchone()
    if row is None:
        raise SystemExit(f"El rol {role} no existe.")
    can_login, is_super, create_db, create_role = row
    wrong = [name for name, bad in (("no puede iniciar sesión", not can_login), ("es SUPERUSER", is_super),
                                    ("tiene CREATEDB", create_db), ("tiene CREATEROLE", create_role)) if bad]
    if wrong:
        raise SystemExit(f"El rol {role} tiene privilegios de más o le falta el acceso: {', '.join(wrong)}. Corrígelo antes de usarlo.")


def app_url(owner_direct_url: str, password: str) -> str:
    """Misma base y opciones que la del dueño, con golden_app y por el POOLER (host del endpoint con «-pooler»)."""
    u = urlsplit(owner_direct_url)
    host = u.hostname
    first, _, rest = host.partition(".")
    if not first.endswith("-pooler"):
        host = f"{first}-pooler.{rest}"
    netloc = f"{APP_ROLE}:{quote(password, safe='')}@{host}" + (f":{u.port}" if u.port else "")
    return urlunsplit(u._replace(netloc=netloc))


def check_app(url: str) -> None:
    """golden_app entra por el pooler, lee, y NO puede crear tablas."""
    conn = psycopg2.connect(url, connect_timeout=15)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM alembic_version")
            try:
                cur.execute("CREATE TABLE _golden_app_no_debe_poder (x int)")
                raise SystemExit("golden_app pudo crear una tabla: los permisos quedaron demasiado amplios")
            except psycopg2.errors.InsufficientPrivilege:
                conn.rollback()
    finally:
        conn.close()


def read_env(path: str) -> tuple:
    raw = open(path, "rb").read().decode("utf8")
    return raw, ("\r\n" if "\r\n" in raw else "\n")


def env_value(raw: str, name: str) -> str:
    for line in raw.splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def write_env(path: str, raw: str, nl: str, name: str, value: str) -> None:
    lines = raw.split(nl)
    lines = [f"{name}={value}" if l.startswith(name + "=") else l for l in lines]
    if not any(l.startswith(name + "=") for l in lines):
        lines.insert(len(lines) - (1 if lines and lines[-1] == "" else 0), f"{name}={value}")
    open(path, "wb").write(nl.join(lines).encode("utf8"))


def gcloud_secret(name: str) -> str:
    return subprocess.run(["gcloud", "secrets", "versions", "access", "latest", f"--secret={name}"], check=True, capture_output=True, text=True).stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--owner-secret", help="secreto con la cadena DIRECTA del dueño")
    ap.add_argument("--app-secret", help="secreto donde se guarda la cadena de golden_app (pooler)")
    ap.add_argument("--rotate", action="store_true")
    ap.add_argument("--grants-only", action="store_true")
    args = ap.parse_args()

    if args.env_file:
        raw, nl = read_env(args.env_file)
        owner_url = env_value(raw, "DIRECT_DATABASE_URL")
    elif args.owner_secret:
        owner_url = gcloud_secret(args.owner_secret)
    else:
        owner_url = os.environ.get("DIRECT_DATABASE_URL", "")
    if not owner_url:
        sys.exit("Falta la cadena DIRECTA del dueño (DIRECT_DATABASE_URL, --env-file o --owner-secret).")
    if urlsplit(owner_url).username == APP_ROLE:
        sys.exit("La cadena directa debe ser la del DUEÑO, no la de golden_app.")
    if not args.grants_only and not (args.env_file or args.app_secret):
        sys.exit("Indica dónde guardar la cadena de golden_app (--env-file o --app-secret): la contraseña no se muestra nunca.")

    conn = psycopg2.connect(owner_url, connect_timeout=15)
    try:
        password = None if args.grants_only else ensure_role(conn, args.rotate)
        apply_grants(conn)
        check_attributes(conn)
    finally:
        conn.close()
    print("Permisos de golden_app aplicados; sin SUPERUSER, CREATEDB ni CREATEROLE (pg_roles).")
    if password is None:
        if not args.grants_only:
            print("golden_app ya existía: contraseña sin cambios (usa --rotate para cambiarla).")
        return
    url = app_url(owner_url, password)
    check_app(url)
    if args.env_file:
        write_env(args.env_file, raw, nl, "DATABASE_URL", url)
        print(f"DATABASE_URL de {args.env_file} ahora usa golden_app por el pooler (DIRECT_DATABASE_URL sigue con el dueño).")
    else:
        subprocess.run(["gcloud", "secrets", "versions", "add", args.app_secret, "--data-file=-"], input=url, text=True, check=True, capture_output=True)
        print(f"Nueva versión del secreto {args.app_secret} con golden_app. Redespliega los servicios para que la tomen.")


if __name__ == "__main__":
    main()
