{
    "name": "FDC GPT API Optimizada Public No Auth",
    "version": "1.2.0",
    "category": "Tools",
    "summary": "API optimizada para consultar, crear y actualizar data Odoo con IA",
    "description": """
API para conexión de GPT/IA con Odoo.
- Schema dinámico de tablas funcionales.
- Excluye views, menús, acciones y tablas técnicas.
- Selección de schema relevante por pregunta.
- Permite SELECT, INSERT y UPDATE.
- Bloquea DELETE y operaciones destructivas.
- Debug info opcional.
- Respuesta rápida sin segunda llamada a IA.
- Endpoints públicos sin token ni Bearer Auth.
""",
    "depends": ["base", "web"],
    "data": [],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
