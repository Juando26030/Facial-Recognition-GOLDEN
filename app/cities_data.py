"""Ciudades por país para el selector del formulario de evento.

Es una lista CURADA (ciudades principales/capitales de departamento o estado), no un dataset
geográfico completo — cubrir literalmente todas las ciudades de todos los países exigiría un
dataset externo (GeoNames u otra API de geocodificación) que no está integrado todavía, ver
CLAUDE.md. El campo Ciudad en el formulario siempre acepta texto libre además de estas
sugerencias, así que un lugar que no esté aquí igual se puede escribir a mano.
"""

COUNTRY_CITIES = {
    "Colombia": [
        "Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena", "Cúcuta", "Bucaramanga",
        "Pereira", "Santa Marta", "Ibagué", "Pasto", "Manizales", "Neiva", "Villavicencio",
        "Armenia", "Valledupar", "Montería", "Sincelejo", "Popayán", "Tunja", "Riohacha",
        "Florencia", "Quibdó", "Yopal", "San Andrés", "Leticia", "Arauca", "Mocoa",
    ],
    "México": [
        "Ciudad de México", "Guadalajara", "Monterrey", "Puebla", "Tijuana", "León",
        "Querétaro", "Mérida", "Cancún", "Toluca", "Acapulco", "Chihuahua", "Culiacán",
        "Hermosillo", "Saltillo", "Aguascalientes", "Morelia", "Veracruz", "Oaxaca",
    ],
    "Argentina": [
        "Buenos Aires", "Córdoba", "Rosario", "Mendoza", "La Plata", "Mar del Plata",
        "San Miguel de Tucumán", "Salta", "Santa Fe", "San Juan", "Neuquén", "Bariloche",
    ],
    "Chile": [
        "Santiago", "Valparaíso", "Concepción", "La Serena", "Antofagasta", "Temuco",
        "Rancagua", "Talca", "Arica", "Puerto Montt", "Iquique",
    ],
    "Perú": [
        "Lima", "Arequipa", "Trujillo", "Chiclayo", "Piura", "Cusco", "Iquitos", "Huancayo",
        "Tacna", "Puno",
    ],
    "Ecuador": ["Quito", "Guayaquil", "Cuenca", "Ambato", "Manta", "Loja", "Machala"],
    "Venezuela": ["Caracas", "Maracaibo", "Valencia", "Barquisimeto", "Maracay", "Mérida"],
    "Bolivia": ["La Paz", "Santa Cruz de la Sierra", "Cochabamba", "Sucre", "Oruro"],
    "Paraguay": ["Asunción", "Ciudad del Este", "Encarnación"],
    "Uruguay": ["Montevideo", "Punta del Este", "Salto", "Maldonado"],
    "Brasil": [
        "São Paulo", "Río de Janeiro", "Brasília", "Salvador", "Fortaleza", "Belo Horizonte",
        "Manaos", "Curitiba", "Recife", "Porto Alegre",
    ],
    "Panamá": ["Ciudad de Panamá", "Colón", "David", "Santiago de Veraguas"],
    "Costa Rica": ["San José", "Alajuela", "Cartago", "Liberia", "Puntarenas"],
    "Guatemala": ["Ciudad de Guatemala", "Quetzaltenango", "Antigua Guatemala"],
    "Honduras": ["Tegucigalpa", "San Pedro Sula", "La Ceiba"],
    "El Salvador": ["San Salvador", "Santa Ana", "San Miguel"],
    "Nicaragua": ["Managua", "León", "Granada"],
    "República Dominicana": ["Santo Domingo", "Santiago de los Caballeros", "Punta Cana"],
    "Cuba": ["La Habana", "Santiago de Cuba", "Camagüey", "Varadero"],
    "Puerto Rico": ["San Juan", "Ponce", "Mayagüez", "Bayamón"],
    "España": [
        "Madrid", "Barcelona", "Valencia", "Sevilla", "Bilbao", "Málaga", "Zaragoza",
        "Palma de Mallorca", "Las Palmas de Gran Canaria",
    ],
    "Estados Unidos": [
        "Nueva York", "Los Ángeles", "Chicago", "Houston", "Miami", "Orlando", "San Francisco",
        "Washington D.C.", "Boston", "Las Vegas", "Dallas", "Atlanta", "Seattle",
    ],
    "Canadá": ["Toronto", "Vancouver", "Montreal", "Ottawa", "Calgary"],
    "Francia": ["París", "Marsella", "Lyon", "Niza", "Toulouse"],
    "Alemania": ["Berlín", "Múnich", "Fráncfort", "Hamburgo", "Colonia"],
    "Italia": ["Roma", "Milán", "Nápoles", "Turín", "Florencia", "Venecia"],
    "Reino Unido": ["Londres", "Mánchester", "Birmingham", "Edimburgo", "Glasgow"],
    "Portugal": ["Lisboa", "Oporto", "Faro"],
    "Países Bajos": ["Ámsterdam", "Róterdam", "La Haya", "Utrecht"],
    "Bélgica": ["Bruselas", "Amberes", "Gante"],
    "Suiza": ["Zúrich", "Ginebra", "Basilea", "Berna"],
    "China": ["Pekín", "Shanghái", "Cantón", "Shenzhen", "Hong Kong"],
    "Japón": ["Tokio", "Osaka", "Kioto", "Yokohama", "Nagoya"],
    "Corea del Sur": ["Seúl", "Busan", "Incheon"],
    "India": ["Nueva Delhi", "Bombay", "Bangalore", "Calcuta", "Chennai"],
    "Australia": ["Sídney", "Melbourne", "Brisbane", "Perth"],
}
