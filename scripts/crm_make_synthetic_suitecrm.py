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
    stages = ["Prospecting", "Qualification", "Needs Analysis", "Proposal/Price Quote", "Negotiation/Review", "Closed Won", "Closed Lost"]
    with open(folder / "productos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID", "Código", "Nombre", "Categoría", "Costo", "Precio", "Moneda"])
        for i in range(1, 11):
            w.writerow([f"sint-prd-{i:03d}", f"SINT-{i:03d}", f"Servicio inventado {i}", "Logística", f"{100000 * i:,}".replace(",", "."), f"{150000 * i:,}".replace(",", ".") + ",00", "COP"])
    with open(folder / "oportunidades.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID", "Código Proyecto", "Nombre", "Nombre de la cuenta", "Etapa de ventas", "Importe", "Moneda", "Fecha de cierre esperada", "Fecha del evento", "Ciudad"])
        for i in range(1, n + 1):
            w.writerow([f"sint-opp-{i:04d}", 9000 + i, f"Evento inventado {i}", f"Empresa Inventada {i} SAS", stages[i % len(stages)], f"{2000000 + i * 1000:,}".replace(",", "."), "COP",
                        f"{(i % 28) + 1:02d}/12/2026", f"{(i % 28) + 1:02d}/01/2027", "Medellín"])
    with open(folder / "actividades.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID", "Tipo", "Asunto", "Estado", "Fecha de vencimiento", "ID oportunidad"])
        for i in range(1, n + 1):
            w.writerow([f"sint-act-{i:04d}", ["Call", "Meeting", "Task", "Note"][i % 4], f"Seguimiento inventado {i}", ["Planned", "Held", "Not Held"][i % 3], f"2026-12-{(i % 28) + 1:02d} 09:30", f"sint-opp-{i:04d}"])
    with open(folder / "cotizaciones.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID", "Número", "Título", "Nombre de la cuenta", "ID oportunidad", "Etapa", "Válida hasta", "Moneda", "Total"])
        for i in range(1, n + 1):
            w.writerow([f"sint-qte-{i:04d}", 7000 + i, f"Cotización inventada {i}", f"Empresa Inventada {i} SAS", f"sint-opp-{i:04d}", ["Draft", "Delivered", "Closed Accepted"][i % 3],
                        "2026-12-31", "COP", "" if i % 5 else "1.190.000"])
    with open(folder / "lineas_cotizacion.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID cotización", "Nombre", "Cantidad", "Precio unitario", "Descuento", "Impuesto"])
        for i in range(1, n + 1):
            if i % 5:
                w.writerow([f"sint-qte-{i:04d}", f"Servicio inventado {(i % 10) + 1}", 2, "500.000", "10", "19"])
                w.writerow([f"sint-qte-{i:04d}", "Transporte inventado", 1, "250000", "0", "19"])
    with open(folder / "proformas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ID", "Número", "ID cotización", "Nombre de la cuenta", "Fecha de emisión", "Estado", "Evento", "Total", "Moneda"])
        for i in range(1, n // 2 + 1):
            w.writerow([f"sint-prf-{i:04d}", 3000 + i, f"sint-qte-{i:04d}", f"Empresa Inventada {i} SAS", "2026-11-20", ["Unpaid", "Paid"][i % 2], f"Evento inventado {i}", "1.190.000", "COP"])


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 50)
