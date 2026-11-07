"""Colombia: base GeoNames (ciudades >= 15.000 hab., app/cities_by_country.json) depurada a mano.
Se quitan localidades/corregimientos que no son municipios, se corrigen nombres y se agregan
capitales departamentales y municipios usados en los cupos de producción (Girardot, Boyacá...)."""
QUITAR = {"Kennedy", "Payandé", "Darien", "Anaime", "Padua", "Girardot City", "Piendamo", "Tolú Viejo", "Villa Rica"}
AGREGAR = [
    # capitales departamentales que podrían faltar
    "Inírida", "Mitú", "Puerto Carreño", "Leticia", "San Andrés", "Mocoa", "Arauca", "Yopal", "Quibdó", "Florencia",
    "San José del Guaviare", "Popayán", "Riohacha", "Sincelejo", "Tunja",
    # correcciones de nombre
    "Girardot", "Piendamó", "Tolúviejo", "Villarrica",
    # municipios usados en cupos o frecuentes en eventos
    "Boyacá", "Bogotá", "Cajicá", "Tocancipá", "Sopó", "La Calera", "Tenjo", "Tabio", "Villa de Leyva", "Paipa", "Nobsa",
    "Ricaurte", "Agua de Dios", "Anapoima", "Villavicencio", "Santa Marta", "Cartagena", "Guatapé", "Jardín", "Santa Marta",
    "Barichara", "Socorro", "Lebrija", "Rionegro", "Girón", "Mariquita", "Honda", "Ibagué", "Melgar", "Carmen de Apicalá",
    "Villeta", "Útica", "La Vega", "Sasaima", "Anolaima", "Zipacón", "Subachoque", "El Rosal", "Bojacá", "Sesquilé",
    "Guasca", "Gachancipá", "Cogua", "Nemocón", "Tausa", "Ubaté", "Simijaca", "Choachí", "Une", "Cáqueza",
]
