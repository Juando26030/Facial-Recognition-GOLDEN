"""Archivos de la VM (`data/`: fotos, firmas, logos, documentos, informes, archivos de formularios) → bucket de Cloud Storage, con MD5.

    python scripts/migrate_files_to_gcs.py --source ~/Facial-Recognition/data --bucket <GCS_BUCKET> [--prefix <GCS_PREFIX>] [--dry-run]
    python scripts/migrate_files_to_gcs.py --source ... --bucket ... --verify-only        # solo comparar, no sube nada

Las claves en el bucket son las mismas que usa la app (`<prefijo>/acme/known_people/1001.jpg`, ver app/storage.py), así que con
`STORAGE_BACKEND=gcs` + `GCS_BUCKET` + `GCS_PREFIX` la app los encuentra sin tocar la base. Se puede repetir las veces que haga falta
(p. ej. una primera pasada días antes y otra en la ventana del cambio): solo sube lo que falta o cambió (mismo MD5 = se salta). Cada
subida la verifica la librería con MD5 de punta a punta, y al final se compara TODO lo local contra el bucket (falta / distinto → código 1).
No sube temporales (`*.part`, `.readyz`, `uploads/`: las subidas directas a medio procesar). Las fotos cifradas (GWENC1) se copian tal cual.
Credenciales: las de gcloud del que corre (Cloud Shell / VM con permiso de escritura en el bucket)."""
import argparse
import base64
import hashlib
import os
import sys

SKIP_DIRS = {"uploads"}


def md5_b64(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode()


def local_files(root: str) -> dict:
    """{clave: ruta} de todo lo que hay que migrar."""
    out = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        rel_folder = os.path.relpath(folder, root).replace("\\", "/")
        if rel_folder == ".":
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".part") or name == ".readyz":
                continue
            path = os.path.join(folder, name)
            if os.path.islink(path):
                continue
            key = name if rel_folder == "." else f"{rel_folder}/{name}"
            out[key] = path
    return out


def main(argv=None, client=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args(argv)
    from google.cloud import storage as gcs

    client = client or gcs.Client()
    bucket = client.bucket(args.bucket)
    prefix = args.prefix.strip("/")
    name = (lambda key: f"{prefix}/{key}") if prefix else (lambda key: key)

    files = local_files(os.path.expanduser(args.source))
    remote = {b.name: b.md5_hash for b in client.list_blobs(bucket, prefix=f"{prefix}/" if prefix else None)}
    uploaded = skipped = size = 0
    for key, path in sorted(files.items()):
        local_md5 = md5_b64(path)
        size += os.path.getsize(path)
        if remote.get(name(key)) == local_md5:
            skipped += 1
            continue
        if args.dry_run or args.verify_only:
            continue
        bucket.blob(name(key)).upload_from_filename(path, checksum="md5")
        remote[name(key)] = local_md5
        uploaded += 1
        if uploaded % 200 == 0:
            print(f"  … {uploaded} subidos")

    if args.dry_run:
        print(f"{len(files)} archivos ({size / 1e6:.1f} MB): {len(files) - skipped} por subir, {skipped} ya están iguales.")
        return 0
    remote = {b.name: b.md5_hash for b in client.list_blobs(bucket, prefix=f"{prefix}/" if prefix else None)}
    missing = [k for k in files if name(k) not in remote]
    different = [k for k, p in files.items() if name(k) in remote and remote[name(k)] != md5_b64(p)]
    print(f"Archivos locales: {len(files)} ({size / 1e6:.1f} MB) · subidos ahora: {uploaded} · ya estaban iguales: {skipped}")
    print(f"Verificación contra el bucket: {len(files) - len(missing) - len(different)} idénticos (MD5), {len(missing)} faltan, {len(different)} distintos")
    for k in (missing + different)[:20]:
        print("  revisar:", k)
    return 1 if missing or different else 0


if __name__ == "__main__":
    sys.exit(main())
