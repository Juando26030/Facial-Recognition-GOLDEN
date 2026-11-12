"""Genera archivos SINTÉTICOS (nombres inventados) con el formato de una exportación de SuiteCRM, para probar el importador sin datos reales.
Uso: python scripts/crm_make_synthetic_suitecrm.py carpeta_de_salida [cantidad]"""
import csv
import sys
from pathlib import Path


def main(out: str, n: int = 50) -> None:
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "cuentas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID", "Nombre", "Número de cuenta", "NIT", "Teléfono de la oficina", "Ciudad"])
        for i in range(1, n + 1):
            w.writerow([f"sint-acc-{i:04d}", f"Empresa Inventada {i} SAS", 5000 + i, f"900{i:06d}", f"300{i:07d}", "Bogotá"])
    with open(folder / "contactos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID", "Nombre", "Apellidos", "Cargo", "Correo electrónico", "Nombre de la cuenta"])
        for i in range(1, n + 1):
            w.writerow([f"sint-con-{i:04d}", f"Persona{i}", "Ficticia", "Gerente", f"persona{i}@ejemplo.test", f"Empresa Inventada {i} SAS"])


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 50)
