import hashlib
import json
import logging
import re
from datetime import timedelta

from odoo import fields, models

_logger = logging.getLogger(__name__)


class FdcDatabase(models.AbstractModel):
    _name = "fdc.database"
    _description = "Dynamic business database schema helper for IA"

    DEFAULT_EXCLUDED_MODEL_PREFIXES = (
        "ir.",
        "base.",
    )

    DEFAULT_EXCLUDED_MODEL_NAMES = {
        "res.config.settings",
    }

    DEFAULT_EXCLUDED_TABLE_PREFIXES = (
        "ir_",
        "base_",
        "bus_",
        "web_",
        "mail_",
        "sms_",
        "digest_",
        "fetchmail_",
        "auth_",
        "iap_",
        "portal_",
        "rating_",
        "utm_",
        "onboarding_",
        "payment_",
        "spreadsheet_",
        "wizard_",
    )

    DEFAULT_EXCLUDED_TABLES = {
        "ir_ui_menu",
        "ir_act_window",
        "ir_act_server",
        "ir_act_report_xml",
        "ir_actions",
        "ir_actions_act_url",
        "ir_actions_act_window",
        "ir_actions_act_window_view",
        "ir_actions_client",
        "ir_actions_report",
        "ir_actions_server",
        "ir_model",
        "ir_model_fields",
        "ir_model_access",
        "ir_rule",
        "ir_cron",
        "ir_config_parameter",
        "ir_attachment",
        "ir_logging",
        "ir_module_module",
        "ir_module_category",
        "ir_sequence",
        "ir_sequence_date_range",
        "ir_translation",
        "ir_ui_view",
        "ir_ui_view_custom",
        "ir_property",
        "ir_default",
        "ir_filters",
        "ir_exports",
        "ir_exports_line",
        "ir_mail_server",
        "res_groups",
        "res_groups_users_rel",
        "res_users_log",
        "res_users_settings",
    }

    ALWAYS_INCLUDE_TABLES = {
        "res_partner",
        "res_company",
        "res_currency",
        "res_currency_rate",
        "res_country",
        "res_country_state",
    }

    PROTECTED_WRITE_TABLES = {
        "res_users",
        "res_groups",
        "res_groups_users_rel",
        "ir_config_parameter",
        "ir_model",
        "ir_model_fields",
        "ir_model_access",
        "ir_rule",
        "ir_cron",
        "ir_ui_menu",
        "ir_ui_view",
        "ir_actions",
        "ir_actions_server",
        "ir_actions_act_window",
        "ir_attachment",
    }

    SEMANTIC_TABLE_GROUPS = {
        "partners": {
            "keywords": [
                "cliente", "clientes", "proveedor", "proveedores", "contacto", "contactos",
                "partner", "ruc", "dni", "razon social", "razón social", "telefono", "teléfono",
                "correo", "email", "direccion", "dirección"
            ],
            "tables": ["res_partner", "res_country", "res_country_state", "res_company", "res_currency"],
        },
        "sales": {
            "keywords": [
                "cotizacion", "cotización", "cotizaciones", "pedido", "pedidos", "venta", "ventas",
                "orden de venta", "so", "vendedor", "comercial", "facturado", "presupuesto"
            ],
            "tables": [
                "sale_order", "sale_order_line", "res_partner", "res_users", "product_product",
                "product_template", "uom_uom", "res_currency", "res_company"
            ],
        },
        "accounting": {
            "keywords": [
                "factura", "facturas", "boleta", "recibo", "contabilidad", "pago", "pagos",
                "pendiente", "deuda", "cobranza", "vencido", "vencidas", "diario", "asiento",
                "invoice", "account"
            ],
            "tables": [
                "account_move", "account_move_line", "account_payment", "account_journal",
                "account_account", "res_partner", "res_currency", "res_company"
            ],
        },
        "products": {
            "keywords": [
                "producto", "productos", "repuesto", "repuestos", "codigo", "código", "sku",
                "precio", "tarifa", "lista de precio", "unidad", "categoria", "categoría"
            ],
            "tables": [
                "product_template", "product_product", "product_category", "uom_uom",
                "product_pricelist", "product_pricelist_item", "res_currency", "res_company"
            ],
        },
        "stock": {
            "keywords": [
                "stock", "inventario", "almacen", "almacén", "ubicacion", "ubicación",
                "kardex", "movimiento", "movimientos", "transferencia", "picking", "existencia",
                "existencias", "lote", "serie"
            ],
            "tables": [
                "stock_quant", "stock_location", "stock_move", "stock_move_line", "stock_picking",
                "stock_picking_type", "stock_warehouse", "product_product", "product_template",
                "stock_lot", "uom_uom", "res_company"
            ],
        },
        "purchases": {
            "keywords": [
                "compra", "compras", "orden de compra", "oc", "purchase", "proveedor",
                "proveedores", "recepcion", "recepción"
            ],
            "tables": [
                "purchase_order", "purchase_order_line", "res_partner", "product_product",
                "product_template", "res_currency", "res_company", "stock_picking"
            ],
        },
        "crm": {
            "keywords": [
                "crm", "oportunidad", "oportunidades", "lead", "prospecto", "pipeline",
                "etapa", "actividad", "actividades"
            ],
            "tables": ["crm_lead", "crm_stage", "res_partner", "res_users", "res_company"],
        },
        "project": {
            "keywords": ["proyecto", "proyectos", "tarea", "tareas", "task"],
            "tables": ["project_project", "project_task", "res_partner", "res_users", "res_company"],
        },
        "maintenance": {
            "keywords": [
                "mantenimiento", "mantenimientos", "equipo", "equipos", "maquina", "máquina",
                "ot", "orden de trabajo", "servicio", "servicios", "preventivo", "correctivo"
            ],
            "tables": [
                "maintenance_equipment", "maintenance_request", "maintenance_team",
                "res_partner", "res_users", "res_company"
            ],
        },
        "hr": {
            "keywords": ["empleado", "empleados", "trabajador", "trabajadores", "personal", "asistencia"],
            "tables": ["hr_employee", "hr_department", "hr_job", "res_company"],
        },
    }

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_schema(self, force_refresh=False):
        """
        Schema funcional dinámico.
        Incluye tablas reales de modelos Odoo persistentes y excluye views/técnicas.
        """
        ICP = self.env["ir.config_parameter"].sudo()

        cache_key = "custom_api_fdccorp_ia.business_schema_cache"
        cache_date_key = "custom_api_fdccorp_ia.business_schema_cache_date"
        cache_fingerprint_key = "custom_api_fdccorp_ia.business_schema_cache_fingerprint"
        ttl_key = "custom_api_fdccorp_ia.schema_cache_ttl_seconds"

        ttl_seconds = int(ICP.get_param(ttl_key) or 86400)
        data_tables = self._get_business_data_tables()
        fingerprint = self._get_tables_fingerprint(data_tables)

        cached_schema = ICP.get_param(cache_key)
        cached_date = ICP.get_param(cache_date_key)
        cached_fingerprint = ICP.get_param(cache_fingerprint_key)

        if cached_schema and cached_date and cached_fingerprint == fingerprint and not force_refresh:
            try:
                cached_dt = fields.Datetime.from_string(cached_date)
                if cached_dt and fields.Datetime.now() - cached_dt < timedelta(seconds=ttl_seconds):
                    _logger.info("Usando business schema cacheado. Tablas: %s", len(data_tables))
                    return cached_schema
            except Exception:
                _logger.warning("No se pudo validar cache del business schema. Se regenerará.")

        schema_text = self._build_schema_text(data_tables)

        ICP.set_param(cache_key, schema_text)
        ICP.set_param(cache_date_key, fields.Datetime.to_string(fields.Datetime.now()))
        ICP.set_param(cache_fingerprint_key, fingerprint)

        _logger.info(
            "Business schema generado. Tablas: %s | Caracteres: %s",
            len(data_tables),
            len(schema_text),
        )
        return schema_text

    def get_relevant_schema(self, human_query, force_refresh=False):
        """
        Schema relevante para una pregunta.
        Mantiene detección dinámica, pero solo manda tablas útiles al modelo.
        """
        ICP = self.env["ir.config_parameter"].sudo()
        max_tables = int(ICP.get_param("custom_api_fdccorp_ia.max_relevant_tables") or 35)
        max_chars = int(ICP.get_param("custom_api_fdccorp_ia.max_schema_chars") or 60000)

        data_tables = self._get_business_data_tables()
        relevant_tables = self._select_relevant_tables(human_query, data_tables, max_tables=max_tables)

        schema_text = self._build_schema_text(relevant_tables, compact=False)

        if len(schema_text) > max_chars:
            schema_text = self._build_schema_text(relevant_tables, compact=True)

        while len(schema_text) > max_chars and len(relevant_tables) > 8:
            relevant_tables = relevant_tables[:-5]
            schema_text = self._build_schema_text(relevant_tables, compact=True)

        _logger.info(
            "Relevant schema generado. Pregunta=%s | Tablas=%s | Caracteres=%s",
            human_query,
            len(relevant_tables),
            len(schema_text),
        )
        return schema_text

    def refresh_schema_cache(self):
        return self.get_schema(force_refresh=True)

    def get_schema_tables_debug(self, relevant_query=None):
        data_tables = self._get_business_data_tables()
        relevant_tables = self._select_relevant_tables(relevant_query, data_tables) if relevant_query else []
        return {
            "business_count": len(data_tables),
            "business_tables": data_tables,
            "relevant_query": relevant_query,
            "relevant_count": len(relevant_tables),
            "relevant_tables": relevant_tables,
        }

    def is_writable_business_table(self, table_name):
        if not table_name:
            return False
        if self._is_protected_write_table(table_name):
            return False
        business_tables = {t["table"] for t in self._get_business_data_tables()}
        return table_name in business_tables

    # -------------------------------------------------------------------------
    # Table discovery
    # -------------------------------------------------------------------------

    def _get_business_data_tables(self):
        base_tables = self._get_physical_base_tables()
        ir_model_map = self._get_ir_model_map()
        result = {}

        for model_name in sorted(self.env.registry.models.keys()):
            try:
                model_obj = self.env[model_name].sudo()
            except Exception:
                continue

            if self._is_excluded_model(model_name):
                continue
            if getattr(model_obj, "_abstract", False):
                continue
            if getattr(model_obj, "_transient", False):
                continue
            if not getattr(model_obj, "_auto", False):
                continue

            table_name = getattr(model_obj, "_table", None)
            if not table_name:
                continue
            if table_name not in base_tables:
                continue
            if self._is_excluded_table(table_name):
                continue

            model_meta = ir_model_map.get(model_name, {})
            result[table_name] = {
                "table": table_name,
                "schema": "public",
                "source": "odoo_model",
                "model": model_name,
                "model_name": model_meta.get("name") or getattr(model_obj, "_description", ""),
                "description": getattr(model_obj, "_description", ""),
            }

        relation_tables = self._get_many2many_relation_tables(set(result.keys()), base_tables)
        for table_name in relation_tables:
            if table_name not in result:
                result[table_name] = {
                    "table": table_name,
                    "schema": "public",
                    "source": "many2many_relation",
                    "model": None,
                    "model_name": "Many2many relation table",
                    "description": "Tabla relacional many2many usada por modelos funcionales.",
                }

        return sorted(result.values(), key=lambda item: item["table"])

    def _select_relevant_tables(self, human_query, data_tables, max_tables=35):
        query = (human_query or "").lower()
        tokens = self._tokenize(query)
        existing = {t["table"]: t for t in data_tables}
        selected = {}
        scores = {}

        def add(table_name, points):
            if table_name in existing:
                selected[table_name] = existing[table_name]
                scores[table_name] = scores.get(table_name, 0) + points

        # Semantic groups by Spanish/English business intent
        for group in self.SEMANTIC_TABLE_GROUPS.values():
            if any(keyword in query for keyword in group["keywords"]):
                for table_name in group["tables"]:
                    add(table_name, 80)

        # Direct table mentions and fuzzy scoring by model/table names
        for info in data_tables:
            table_name = info["table"]
            model_name = info.get("model") or ""
            model_label = info.get("model_name") or ""
            haystack = f"{table_name} {model_name} {model_label}".lower()

            if table_name in query or model_name in query:
                add(table_name, 100)
                continue

            score = 0
            for token in tokens:
                if len(token) < 3:
                    continue
                if token in haystack:
                    score += 8
            if score:
                add(table_name, score)

        # Field-name matching only after broad table matching to avoid expensive huge prompts
        if tokens:
            field_hits = self._score_tables_by_field_names(tokens, list(existing.keys()))
            for table_name, score in field_hits.items():
                add(table_name, min(score, 40))

        # Always add base relational tables when there is business context
        if selected:
            for table_name in self.ALWAYS_INCLUDE_TABLES:
                add(table_name, 20)

        if not selected:
            fallback = [
                "res_partner", "sale_order", "sale_order_line", "account_move", "account_move_line",
                "product_template", "product_product", "stock_quant", "stock_location", "crm_lead",
                "purchase_order", "purchase_order_line", "res_company", "res_currency"
            ]
            for table_name in fallback:
                add(table_name, 10)

        ordered_names = sorted(selected.keys(), key=lambda name: (-scores.get(name, 0), name))
        ordered_names = ordered_names[:max_tables]
        return [selected[name] for name in ordered_names]

    def _score_tables_by_field_names(self, tokens, table_names):
        if not table_names:
            return {}

        query = """
            SELECT
                m.model,
                replace(m.model, '.', '_') AS guessed_table,
                f.name AS field_name,
                f.field_description
            FROM ir_model_fields f
            JOIN ir_model m ON m.id = f.model_id
            WHERE f.store = true
              AND replace(m.model, '.', '_') = ANY(%s)
        """
        self.env.cr.execute(query, (table_names,))
        rows = self.env.cr.dictfetchall()
        scores = {}
        for row in rows:
            table_name = row["guessed_table"]
            haystack = f"{row.get('field_name') or ''} {row.get('field_description') or ''}".lower()
            for token in tokens:
                if len(token) >= 3 and token in haystack:
                    scores[table_name] = scores.get(table_name, 0) + 4
        return scores

    def _tokenize(self, text):
        text = (text or "").lower()
        tokens = re.findall(r"[a-záéíóúñ0-9_]+", text)
        stopwords = {
            "que", "qué", "cual", "cuál", "como", "cómo", "para", "con", "sin", "los", "las",
            "una", "uno", "del", "por", "hay", "son", "sus", "este", "esta", "ese", "esa",
            "crea", "crear", "actualiza", "actualizar", "muestra", "mostrar", "dame", "quiero"
        }
        return [token for token in tokens if token not in stopwords]

    def _is_excluded_model(self, model_name):
        ICP = self.env["ir.config_parameter"].sudo()
        excluded_names = set(self.DEFAULT_EXCLUDED_MODEL_NAMES) | self._csv_param(ICP.get_param("custom_api_fdccorp_ia.exclude_models"))
        excluded_prefixes = set(self.DEFAULT_EXCLUDED_MODEL_PREFIXES) | self._csv_param(ICP.get_param("custom_api_fdccorp_ia.exclude_model_prefixes"))

        if model_name in excluded_names:
            return True
        return any(prefix and model_name.startswith(prefix) for prefix in excluded_prefixes)

    def _is_excluded_table(self, table_name):
        ICP = self.env["ir.config_parameter"].sudo()
        force_include = self._csv_param(ICP.get_param("custom_api_fdccorp_ia.include_tables"))
        force_exclude = self._csv_param(ICP.get_param("custom_api_fdccorp_ia.exclude_tables"))
        custom_excluded_prefixes = self._csv_param(ICP.get_param("custom_api_fdccorp_ia.exclude_table_prefixes"))

        if table_name in force_include:
            return False
        if table_name in self.ALWAYS_INCLUDE_TABLES:
            return False
        if table_name in set(self.DEFAULT_EXCLUDED_TABLES) | force_exclude:
            return True
        excluded_prefixes = set(self.DEFAULT_EXCLUDED_TABLE_PREFIXES) | custom_excluded_prefixes
        return any(prefix and table_name.startswith(prefix) for prefix in excluded_prefixes)

    def _is_protected_write_table(self, table_name):
        if not table_name:
            return True
        if table_name in self.PROTECTED_WRITE_TABLES:
            return True
        protected_prefixes = ("ir_", "base_", "bus_", "web_", "auth_", "payment_")
        return any(table_name.startswith(prefix) for prefix in protected_prefixes)

    def _csv_param(self, value):
        if not value:
            return set()
        return {item.strip() for item in value.split(",") if item.strip()}

    def _get_physical_base_tables(self):
        query = """
            SELECT c.relname AS table_name, c.relkind AS relkind
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind IN ('r', 'p')
            ORDER BY c.relname
        """
        self.env.cr.execute(query)
        return {row["table_name"]: row["relkind"] for row in self.env.cr.dictfetchall()}

    def _get_ir_model_map(self):
        query = """
            SELECT model, name, state, transient
            FROM ir_model
            ORDER BY model
        """
        self.env.cr.execute(query)
        return {row["model"]: row for row in self.env.cr.dictfetchall()}

    def _get_many2many_relation_tables(self, included_tables, base_tables):
        if not included_tables:
            return []
        query = """
            SELECT
                tc.table_name,
                COUNT(*) AS fk_count,
                BOOL_OR(ccu.table_name = ANY(%s)) AS references_included_table
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema = kcu.table_schema
               AND tc.table_name = kcu.table_name
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
               AND ccu.constraint_schema = tc.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
            GROUP BY tc.table_name
            HAVING COUNT(*) >= 2
               AND BOOL_OR(ccu.table_name = ANY(%s)) = true
            ORDER BY tc.table_name
        """
        included_list = list(included_tables)
        self.env.cr.execute(query, (included_list, included_list))
        rows = self.env.cr.dictfetchall()

        relation_tables = []
        for row in rows:
            table_name = row["table_name"]
            if table_name in included_tables:
                continue
            if table_name not in base_tables:
                continue
            if self._is_excluded_table(table_name):
                continue
            if table_name.endswith("_rel") or int(row["fk_count"]) >= 2:
                relation_tables.append(table_name)
        return sorted(set(relation_tables))

    # -------------------------------------------------------------------------
    # Schema text
    # -------------------------------------------------------------------------

    def _build_schema_text(self, data_tables, compact=False):
        table_names = [item["table"] for item in data_tables]
        if not table_names:
            return "NO BUSINESS TABLES AVAILABLE"

        columns = self._get_columns(table_names)
        primary_keys = self._get_primary_keys(table_names)
        foreign_keys = self._get_foreign_keys(table_names)
        odoo_fields = self._get_odoo_fields_for_models([item["model"] for item in data_tables if item.get("model")])

        pk_map = self._build_pk_map(primary_keys)
        fk_map = self._build_fk_map(foreign_keys)
        odoo_field_map = self._build_odoo_field_map(odoo_fields)

        lines = []
        lines.append("ODOO BUSINESS DATA SCHEMA FOR SQL GENERATION")
        lines.append("=" * 100)
        lines.append(f"Database: {self.env.cr.dbname}")
        lines.append(f"Tables included: {len(data_tables)}")
        lines.append("")
        lines.append("SCOPE")
        lines.append("- Includes persistent Odoo business data tables only.")
        lines.append("- SQL views, transient models, wizards, menus, actions and technical metadata are excluded.")
        lines.append("- New persistent models installed by new modules are included automatically.")
        lines.append("")
        lines.append("SQL RULES")
        lines.append("- Allowed: SELECT, INSERT, UPDATE.")
        lines.append("- Forbidden: DELETE, DROP, ALTER, CREATE, TRUNCATE, COPY, CALL, DO, GRANT, REVOKE, EXECUTE, PREPARE, VACUUM, ANALYZE, MERGE.")
        lines.append("- Generate only one SQL statement.")
        lines.append("- Do not use semicolon or SQL comments.")
        lines.append("- SELECT must use LIMIT 50 or lower.")
        lines.append("- UPDATE must include WHERE.")
        lines.append("- INSERT/UPDATE should use RETURNING id when possible.")
        lines.append("")

        for table in data_tables:
            table_name = table["table"]
            table_key = f"public.{table_name}"
            lines.append("")
            lines.append(f"TABLE: {table_key}")
            lines.append(f"SOURCE: {table['source']}")
            if table.get("model"):
                lines.append(f"ODOO_MODEL: {table['model']}")
                if not compact:
                    lines.append(f"MODEL_NAME: {table.get('model_name') or ''}")
            if table.get("description") and not compact:
                lines.append(f"DESCRIPTION: {table['description']}")
            lines.append("COLUMNS:")

            for col in [c for c in columns if c["table_name"] == table_name]:
                col_name = col["column_name"]
                col_type = self._format_column_type(col)
                tags = []
                if col_name in pk_map.get(table_key, []):
                    tags.append("PK")
                fk = fk_map.get(table_key, {}).get(col_name)
                if fk:
                    tags.append(f"FK->{fk['foreign_table_schema']}.{fk['foreign_table_name']}.{fk['foreign_column_name']}")
                if not compact:
                    odoo_field = odoo_field_map.get(table_name, {}).get(col_name)
                    if odoo_field:
                        label = odoo_field.get("field_description") or ""
                        ttype = odoo_field.get("ttype") or ""
                        relation = odoo_field.get("relation") or ""
                        field_text = f"OdooField label='{label}' type={ttype}"
                        if relation:
                            field_text += f" relation={relation}"
                        tags.append(field_text)
                tag_text = f" [{' | '.join(tags)}]" if tags else ""
                if compact:
                    lines.append(f"  - {col_name}: {col_type}{tag_text}")
                else:
                    nullable = "NULL" if col["is_nullable"] == "YES" else "NOT NULL"
                    lines.append(f"  - {col_name}: {col_type} {nullable}{tag_text}")

        return "\n".join(lines)

    def _get_columns(self, table_names):
        query = """
            SELECT
                c.table_schema,
                c.table_name,
                c.ordinal_position,
                c.column_name,
                c.data_type,
                c.udt_name AS postgres_type,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                c.is_nullable,
                c.column_default
            FROM information_schema.columns c
            WHERE c.table_schema = 'public'
              AND c.table_name = ANY(%s)
            ORDER BY c.table_name, c.ordinal_position
        """
        self.env.cr.execute(query, (table_names,))
        return self.env.cr.dictfetchall()

    def _get_primary_keys(self, table_names):
        query = """
            SELECT
                tc.table_schema,
                tc.table_name,
                tc.constraint_name,
                kcu.column_name,
                kcu.ordinal_position
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema = kcu.table_schema
               AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = ANY(%s)
            ORDER BY tc.table_name, kcu.ordinal_position
        """
        self.env.cr.execute(query, (table_names,))
        return self.env.cr.dictfetchall()

    def _get_foreign_keys(self, table_names):
        query = """
            SELECT
                tc.table_schema,
                tc.table_name,
                kcu.column_name,
                ccu.table_schema AS foreign_table_schema,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema = kcu.table_schema
               AND tc.table_name = kcu.table_name
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
               AND ccu.constraint_schema = tc.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = ANY(%s)
            ORDER BY tc.table_name, kcu.column_name
        """
        self.env.cr.execute(query, (table_names,))
        return self.env.cr.dictfetchall()

    def _get_odoo_fields_for_models(self, model_names):
        if not model_names:
            return []
        query = """
            SELECT
                m.model,
                replace(m.model, '.', '_') AS guessed_table,
                f.name AS field_name,
                f.field_description,
                f.ttype,
                f.relation,
                f.required,
                f.readonly,
                f.store
            FROM ir_model_fields f
            JOIN ir_model m ON m.id = f.model_id
            WHERE f.store = true
              AND m.model = ANY(%s)
            ORDER BY m.model, f.name
        """
        self.env.cr.execute(query, (model_names,))
        return self.env.cr.dictfetchall()

    def _format_column_type(self, col):
        data_type = col["data_type"]
        if col.get("character_maximum_length"):
            return f"{data_type}({col['character_maximum_length']})"
        if col.get("numeric_precision"):
            scale = col.get("numeric_scale")
            if scale is not None:
                return f"{data_type}({col['numeric_precision']},{scale})"
            return f"{data_type}({col['numeric_precision']})"
        return data_type

    def _build_pk_map(self, primary_keys):
        result = {}
        for pk in primary_keys:
            table_key = f"{pk['table_schema']}.{pk['table_name']}"
            result.setdefault(table_key, []).append(pk["column_name"])
        return result

    def _build_fk_map(self, foreign_keys):
        result = {}
        for fk in foreign_keys:
            table_key = f"{fk['table_schema']}.{fk['table_name']}"
            result.setdefault(table_key, {})[fk["column_name"]] = fk
        return result

    def _build_odoo_field_map(self, odoo_fields):
        result = {}
        for field in odoo_fields:
            table_name = field["guessed_table"]
            field_name = field["field_name"]
            result.setdefault(table_name, {})[field_name] = field
        return result

    def _get_tables_fingerprint(self, data_tables):
        payload = json.dumps(data_tables, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
