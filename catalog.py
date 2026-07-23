"""
Catálogo de ciudades y sectores para los selectores de LeadForge.

Las ciudades están ordenadas por volumen de negocios esperado, para que las
primeras opciones sean también las más rentables.
"""

__version__ = "4.0"


CITIES: dict[str, list[str]] = {
    "es": [
        "Madrid", "Barcelona", "Valencia", "Sevilla", "Zaragoza", "Málaga", "Murcia",
        "Palma", "Las Palmas", "Bilbao", "Alicante", "Córdoba", "Valladolid", "Vigo",
        "Gijón", "Granada", "A Coruña", "Vitoria", "Elche", "Oviedo", "Badalona",
        "Cartagena", "Terrassa", "Jerez de la Frontera", "Sabadell", "Móstoles",
        "Santa Cruz de Tenerife", "Pamplona", "Almería", "Alcalá de Henares", "Fuenlabrada",
        "Leganés", "San Sebastián", "Getafe", "Burgos", "Santander", "Castellón",
        "Albacete", "Alcorcón", "San Cristóbal de La Laguna", "Logroño", "Badajoz",
        "Salamanca", "Huelva", "Lleida", "Marbella", "Tarragona", "León", "Cádiz",
        "Dos Hermanas", "Mataró", "Torrejón de Ardoz", "Parla", "Algeciras", "Alcobendas",
        "Reus", "Ourense", "Girona", "Lugo", "Cáceres", "Toledo", "Pontevedra",
        "Guadalajara", "Jaén", "Ceuta", "Melilla", "Ávila", "Cuenca", "Zamora", "Segovia",
        "Palencia", "Soria", "Teruel", "Huesca", "Mérida", "Ciudad Real",
    ],
    "mx": [
        "Ciudad de México", "Guadalajara", "Monterrey", "Puebla", "Tijuana", "León",
        "Juárez", "Zapopan", "Mérida", "San Luis Potosí", "Querétaro", "Aguascalientes",
        "Mexicali", "Acapulco", "Culiacán", "Hermosillo", "Saltillo", "Morelia",
        "Cancún", "Toluca", "Chihuahua", "Torreón", "Veracruz", "Villahermosa",
        "Tuxtla Gutiérrez", "Reynosa", "Durango", "Oaxaca", "Tampico", "Xalapa",
        "Cuernavaca", "Irapuato", "Pachuca", "Celaya", "Mazatlán", "Ensenada",
    ],
    "co": [
        "Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena", "Cúcuta",
        "Bucaramanga", "Pereira", "Santa Marta", "Ibagué", "Manizales", "Villavicencio",
        "Pasto", "Neiva", "Armenia", "Popayán", "Montería", "Valledupar", "Sincelejo",
        "Tunja", "Envigado", "Bello", "Soacha", "Palmira",
    ],
    "ar": [
        "Buenos Aires", "Córdoba", "Rosario", "Mendoza", "La Plata", "Tucumán",
        "Mar del Plata", "Salta", "Santa Fe", "San Juan", "Resistencia", "Neuquén",
        "Corrientes", "Bahía Blanca", "Posadas", "Paraná", "Formosa", "San Luis",
    ],
    "cl": [
        "Santiago", "Valparaíso", "Concepción", "La Serena", "Antofagasta", "Temuco",
        "Rancagua", "Talca", "Arica", "Iquique", "Puerto Montt", "Viña del Mar",
        "Chillán", "Valdivia", "Osorno", "Calama",
    ],
    "pe": [
        "Lima", "Arequipa", "Trujillo", "Chiclayo", "Piura", "Cusco", "Huancayo",
        "Iquitos", "Tacna", "Chimbote", "Pucallpa", "Ica", "Juliaca", "Ayacucho",
    ],
}

# Términos de búsqueda por sector. La clave es el sector; el valor, los términos
# tal y como se escriben en Google Maps.
SECTORS: dict[str, list[str]] = {
    "Clubes deportivos": [
        "club de futbol base", "escuela de futbol", "academia de futbol",
        "club de baloncesto", "club de balonmano", "club de futbol sala",
        "club de voleibol", "club de rugby", "club deportivo", "club multideporte",
        "asociacion deportiva", "club de atletismo",
    ],
    "Raqueta y pádel": [
        "club de padel", "escuela de padel", "club de tenis", "escuela de tenis",
        "club de tenis de mesa", "club de badminton",
    ],
    "Agua y piscina": [
        "club de natacion", "escuela de natacion", "club de waterpolo",
        "club de piraguismo", "club de remo", "escuela de surf", "club de vela",
    ],
    "Artes marciales y combate": [
        "club de judo", "escuela de karate", "gimnasio de boxeo", "club de taekwondo",
        "escuela de artes marciales", "club de lucha",
    ],
    "Gimnasios y fitness": [
        "gimnasio", "box crossfit", "estudio de pilates", "centro de yoga",
        "entrenamiento personal", "centro de fitness",
    ],
    "Academias y formación": [
        "academia de idiomas", "centro de estudios", "academia de refuerzo escolar",
        "escuela de musica", "escuela de danza", "autoescuela",
    ],
    "Hostelería": [
        "restaurante", "cafeteria", "bar de tapas", "pizzeria", "hamburgueseria",
        "cerveceria",
    ],
    "Salud y bienestar": [
        "clinica dental", "centro de fisioterapia", "clinica veterinaria",
        "centro de estetica", "peluqueria", "podologo",
    ],
    "Comercio local": [
        "tienda de deportes", "libreria", "floristeria", "ferreteria",
        "tienda de mascotas", "optica",
    ],
}


def cities_for(country_code: str) -> list[str]:
    return CITIES.get(country_code, [])


def all_terms() -> list[str]:
    seen, terms = set(), []
    for values in SECTORS.values():
        for term in values:
            if term not in seen:
                seen.add(term)
                terms.append(term)
    return terms
