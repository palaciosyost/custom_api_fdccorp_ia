import json
import logging
import re
import time
from datetime import datetime

import requests

from odoo import models

_logger = logging.getLogger(__name__)


class FdcGptSqlService(models.AbstractModel):
    _name = "fdc.gpt.sql.service"
    _description = "Natural language to SQL service optimized"

    ALLOWED_SQL_ACTIONS = {"select", "insert", "update"}

    BLOCKED_WORDS = [
        "delete",
        "drop",
        "alter",
        "create",
        "truncate",
        "copy",
        "call",
        "do",
        "grant",
        "revoke",
        "execute",
        "prepare",
        "vacuum",
        "analyze",
        "merge",
        "pg_sleep",
        "pg_read_file",
        "pg_ls_dir",
        "pg_stat_file",
        "lo_import",
        "lo_export",
    ]

    BLOCKED_WRITE_COLUMNS = {
        "password",
        "new_password",
        "api_key",
        "token",
        "access_token",
        "access_token_id",
        "signup_token",
        "reset_password_token",
        "oauth_access_token",
        "session_id",
        "secret",
    }

    def human_query_to_sql(self, human_query, debug_info=None):
        """
        Convierte lenguaje natural a SQL.
        Optimización principal:
        - Primero intenta plantilla interna sin IA.
        - Si no aplica, manda solo schema relevante.
        - Devuelve JSON estructurado.
        """
        debug_info = debug_info or {}
        debug_info["step_human_query_to_sql_start"] = datetime.now().isoformat()

        fast_sql = self.try_fast_template(human_query)
        if fast_sql:
            debug_info["used_fast_template"] = True
            debug_info["step_human_query_to_sql_end"] = datetime.now().isoformat()
            return fast_sql

        debug_info["used_fast_template"] = False

        database_schema = self.env["fdc.database"].sudo().get_relevant_schema(human_query)
        debug_info["schema_chars"] = len(database_schema or "")

        api_key = self._get_param("custom_api_fdccorp_ia.openai_api_key")
        model = self._get_param("custom_api_fdccorp_ia.model") or "gpt-5.4-nano"
        api_url = self._get_param("custom_api_fdccorp_ia.openai_responses_url") or "https://api.openai.com/v1/responses"

        debug_info["openai_model"] = model
        debug_info["openai_url"] = api_url

        if not api_key:
            raise Exception("Falta configurar custom_api_fdccorp_ia.openai_api_key")

        system_message = f"""
You are a secure SQL generator for a PostgreSQL database used by Odoo.

Given the following Odoo business database schema subset, write ONE SQL statement that satisfies the user request.

Return ONLY valid JSON with this exact structure:
{{
  "sql_query": "SQL statement here",
  "sql_action": "select | insert | update",
  "original_query": "User original question",
  "explanation": "Short explanation",
  "requires_write": true
}}

Allowed SQL actions:
1. SELECT for reading data.
2. INSERT for creating new records.
3. UPDATE for modifying existing records.

Forbidden SQL actions:
1. DELETE is forbidden.
2. DROP is forbidden.
3. ALTER is forbidden.
4. CREATE is forbidden.
5. TRUNCATE is forbidden.
6. COPY, CALL, DO, GRANT, REVOKE, EXECUTE, PREPARE, VACUUM, ANALYZE and MERGE are forbidden.

Mandatory rules:
1. Generate only ONE SQL statement.
2. Do not use semicolon.
3. Do not use SQL comments.
4. Use only tables and columns from the schema.
5. Do not invent tables.
6. Do not invent columns.
7. SELECT queries must use LIMIT 50 or lower.
8. UPDATE queries must always include a WHERE clause.
9. UPDATE queries must never update all rows.
10. INSERT and UPDATE should include RETURNING id when the table has an id column.
11. For Odoo customers, use res_partner with customer_rank > 0 when appropriate.
12. For vendors/suppliers, use res_partner with supplier_rank > 0 when appropriate.
13. For active records, use active = true when the table has an active column.
14. If the request is ambiguous or cannot be answered safely, return an empty sql_query.
15. Never generate DELETE.
16. Avoid writing to users, permissions, menus, actions, views, config, passwords, tokens or technical tables.
17. For INSERT into Odoo business tables, include create_date and write_date when those columns exist using NOW().
18. For UPDATE into Odoo business tables, include write_date = NOW() when the column exists.

<schema>
{database_schema}
</schema>
"""

        payload = {
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": system_message,
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": human_query,
                        }
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "sql_query_response",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "sql_query",
                            "sql_action",
                            "original_query",
                            "explanation",
                            "requires_write",
                        ],
                        "properties": {
                            "sql_query": {"type": "string"},
                            "sql_action": {"type": "string", "enum": ["select", "insert", "update"]},
                            "original_query": {"type": "string"},
                            "explanation": {"type": "string"},
                            "requires_write": {"type": "boolean"},
                        },
                    },
                }
            },
        }

        debug_info["openai_payload_chars"] = len(json.dumps(payload, ensure_ascii=False, default=str))

        response = self._post_openai_with_retry(
            payload=payload,
            api_key=api_key,
            url=api_url,
            timeout=int(self._get_param("custom_api_fdccorp_ia.openai_timeout") or 120),
            max_retries=int(self._get_param("custom_api_fdccorp_ia.openai_max_retries") or 3),
            debug_info=debug_info,
        )

        data = response.json()
        output_text = self._extract_output_text(data)
        debug_info["openai_response_received"] = True
        debug_info["openai_output_chars"] = len(output_text or "")
        debug_info["step_human_query_to_sql_end"] = datetime.now().isoformat()

        if debug_info.get("show_debug"):
            _logger.info("OpenAI output_text: %s", output_text)

        if not output_text:
            raise Exception("OpenAI no devolvió output_text.")

        try:
            result = json.loads(output_text)
            debug_info["sql_generation"] = result
            return result
        except json.JSONDecodeError:
            _logger.error("Respuesta no JSON de OpenAI: %s", output_text)
            raise Exception("OpenAI devolvió una respuesta que no es JSON válido.")

    def try_fast_template(self, human_query):
        """
        Plantillas internas sin IA para bajar costo y latencia.
        Agrega aquí las preguntas frecuentes de tu operación.
        """
        q = (human_query or "").lower()
        normalized = self._normalize(q)

        if "cuantos clientes" in normalized or "cuantas clientes" in normalized or "cantidad de clientes" in normalized:
            return {
                "sql_query": "SELECT COUNT(*) AS total_clientes FROM res_partner WHERE customer_rank > 0 AND active = true LIMIT 1",
                "sql_action": "select",
                "original_query": human_query,
                "explanation": "Consulta rápida interna para contar clientes activos.",
                "requires_write": False,
                "source": "fast_template",
            }

        if "cuantos proveedores" in normalized or "cantidad de proveedores" in normalized:
            return {
                "sql_query": "SELECT COUNT(*) AS total_proveedores FROM res_partner WHERE supplier_rank > 0 AND active = true LIMIT 1",
                "sql_action": "select",
                "original_query": human_query,
                "explanation": "Consulta rápida interna para contar proveedores activos.",
                "requires_write": False,
                "source": "fast_template",
            }

        if "ultimas cotizaciones" in normalized or "ultimos presupuestos" in normalized:
            return {
                "sql_query": "SELECT so.id, so.name, so.date_order, rp.name AS cliente, so.amount_total, so.state FROM sale_order so LEFT JOIN res_partner rp ON rp.id = so.partner_id ORDER BY so.date_order DESC LIMIT 10",
                "sql_action": "select",
                "original_query": human_query,
                "explanation": "Consulta rápida interna para listar últimas cotizaciones/pedidos.",
                "requires_write": False,
                "source": "fast_template",
            }

        if "facturas pendientes" in normalized or "facturas por cobrar" in normalized:
            return {
                "sql_query": "SELECT am.id, am.name, am.invoice_date, rp.name AS cliente, am.amount_total, am.amount_residual, am.payment_state FROM account_move am LEFT JOIN res_partner rp ON rp.id = am.partner_id WHERE am.move_type IN ('out_invoice','out_refund') AND am.state = 'posted' AND am.payment_state IN ('not_paid','partial') ORDER BY am.invoice_date DESC LIMIT 50",
                "sql_action": "select",
                "original_query": human_query,
                "explanation": "Consulta rápida interna para facturas pendientes de cobro.",
                "requires_write": False,
                "source": "fast_template",
            }

        return None

    def query(self, sql_query, debug_info=None):
        """
        Ejecuta SQL validado.
        SELECT devuelve filas.
        INSERT/UPDATE hace commit y devuelve RETURNING si existe.
        """
        debug_info = debug_info or {}
        debug_info["step_sql_execution_start"] = datetime.now().isoformat()
        debug_info["sql_query"] = sql_query

        validation = self.validate_sql(sql_query)
        debug_info["sql_validation"] = validation

        if not validation["ok"]:
            raise Exception(f"SQL rechazado: {validation['reason']}")

        sql_action = validation["action"]
        debug_info["sql_action"] = sql_action

        try:
            self.env.cr.execute("SET statement_timeout = '120s'")
            _logger.info("[GPT SQL] Ejecutando acción=%s", sql_action)
            if debug_info.get("show_debug"):
                _logger.info("[GPT SQL] SQL=%s", sql_query)

            self.env.cr.execute(sql_query)

            rows = []
            if self.env.cr.description:
                columns = [desc[0] for desc in self.env.cr.description]
                rows = [dict(zip(columns, row)) for row in self.env.cr.fetchall()]
                debug_info["sql_returning_columns"] = columns
            else:
                debug_info["sql_returning_columns"] = []

            rowcount = self.env.cr.rowcount
            debug_info["sql_returning_rows"] = len(rows)
            debug_info["sql_rowcount"] = rowcount

            if sql_action in ["insert", "update"]:
                self.env.cr.commit()
                debug_info["transaction_committed"] = True
                debug_info["transaction_commit_at"] = datetime.now().isoformat()
            else:
                debug_info["transaction_committed"] = False

            debug_info["step_sql_execution_end"] = datetime.now().isoformat()

            return {
                "action": sql_action,
                "rowcount": rowcount,
                "rows": rows,
            }

        except Exception as e:
            self.env.cr.rollback()
            debug_info["transaction_rolled_back"] = True
            debug_info["sql_error"] = str(e)
            _logger.exception("[GPT SQL] Error ejecutando SQL generado.")
            raise Exception(f"Error ejecutando SQL: {str(e)}")

    def build_fast_answer(self, execution_result, human_query=None, sql_query=None):
        """
        Respuesta sin segunda llamada a IA.
        Reduce costo y latencia.
        """
        action = execution_result.get("action")
        rowcount = execution_result.get("rowcount")
        rows = execution_result.get("rows") or []

        if action == "select":
            if not rows:
                return "No se encontraron resultados para la consulta."
            return f"Consulta realizada correctamente. Se encontraron {len(rows)} resultado(s)."

        if action == "insert":
            if rows:
                return f"Registro creado correctamente. Filas afectadas: {rowcount}. Resultado: {json.dumps(rows, ensure_ascii=False, default=str)}"
            return f"Registro creado correctamente. Filas afectadas: {rowcount}."

        if action == "update":
            if rows:
                return f"Registro actualizado correctamente. Filas afectadas: {rowcount}. Resultado: {json.dumps(rows, ensure_ascii=False, default=str)}"
            return f"Registro actualizado correctamente. Filas afectadas: {rowcount}."

        return "Operación ejecutada correctamente."

    def build_answer(self, execution_result, human_query, sql_query, debug_info=None):
        """
        Método conservado por compatibilidad.
        Por defecto devuelve respuesta rápida sin IA.
        Si custom_api_fdccorp_ia.use_ai_answer = true, usa una segunda llamada a IA.
        """
        use_ai_answer = (self._get_param("custom_api_fdccorp_ia.use_ai_answer") or "false").lower() == "true"
        if not use_ai_answer:
            return self.build_fast_answer(execution_result, human_query, sql_query)

        debug_info = debug_info or {}
        debug_info["step_build_answer_start"] = datetime.now().isoformat()

        api_key = self._get_param("custom_api_fdccorp_ia.openai_api_key")
        model = self._get_param("custom_api_fdccorp_ia.answer_model") or self._get_param("custom_api_fdccorp_ia.model") or "gpt-5.4-nano"
        api_url = self._get_param("custom_api_fdccorp_ia.openai_responses_url") or "https://api.openai.com/v1/responses"

        if not api_key:
            raise Exception("Falta configurar custom_api_fdccorp_ia.openai_api_key")

        system_message = f"""
Given a user's question and SQL execution result from an Odoo/PostgreSQL database, write a clear Spanish answer.

Rules:
1. Do not invent data.
2. If rows are empty, say no rows were returned.
3. If an INSERT or UPDATE was executed, clearly say that the operation was completed.
4. Mention how many rows were affected when available.
5. Do not expose internal tokens, credentials or server configuration.

<user_question>
{human_query}
</user_question>

<sql_query>
{sql_query}
</sql_query>

<sql_execution_result>
{json.dumps(execution_result, ensure_ascii=False, default=str)}
</sql_execution_result>
"""
        payload = {
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_message}],
                }
            ],
        }

        response = self._post_openai_with_retry(
            payload=payload,
            api_key=api_key,
            url=api_url,
            timeout=int(self._get_param("custom_api_fdccorp_ia.openai_timeout") or 120),
            max_retries=int(self._get_param("custom_api_fdccorp_ia.openai_max_retries") or 3),
            debug_info=debug_info,
        )

        data = response.json()
        output_text = self._extract_output_text(data)
        debug_info["step_build_answer_end"] = datetime.now().isoformat()

        if not output_text:
            raise Exception("OpenAI no devolvió respuesta final.")
        return output_text

    def validate_sql(self, sql_query):
        if not sql_query or not isinstance(sql_query, str):
            return {"ok": False, "reason": "Consulta vacía.", "action": None}

        sql = sql_query.strip()
        sql_lower = sql.lower()

        if ";" in sql:
            return {"ok": False, "reason": "No se permite punto y coma.", "action": None}
        if "--" in sql_lower or "/*" in sql_lower or "*/" in sql_lower:
            return {"ok": False, "reason": "No se permiten comentarios SQL.", "action": None}
        if re.match(r"^\s*with\b", sql_lower):
            return {"ok": False, "reason": "No se permiten CTE/WITH para este endpoint.", "action": None}

        action_match = re.match(r"^\s*(select|insert|update)\b", sql_lower)
        if not action_match:
            return {"ok": False, "reason": "Solo se permiten SELECT, INSERT o UPDATE.", "action": None}

        action = action_match.group(1)
        if action not in self.ALLOWED_SQL_ACTIONS:
            return {"ok": False, "reason": f"Acción no permitida: {action}", "action": action}

        for word in self.BLOCKED_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", sql_lower):
                return {"ok": False, "reason": f"Palabra bloqueada detectada: {word}", "action": action}

        if action == "select":
            limit_match = re.search(r"\blimit\s+(\d+)\b", sql_lower)
            if not limit_match:
                return {"ok": False, "reason": "Las consultas SELECT deben incluir LIMIT.", "action": action}
            if int(limit_match.group(1)) > 50:
                return {"ok": False, "reason": "El LIMIT máximo permitido es 50.", "action": action}

        if action == "update":
            if not re.search(r"\bwhere\b", sql_lower):
                return {"ok": False, "reason": "UPDATE debe incluir WHERE.", "action": action}
            if re.search(r"\bwhere\s+1\s*=\s*1\b", sql_lower) or re.search(r"\bwhere\s+true\b", sql_lower):
                return {"ok": False, "reason": "UPDATE masivo no permitido.", "action": action}

        if action in ["insert", "update"]:
            write_enabled = (self._get_param("custom_api_fdccorp_ia.allow_write_sql") or "true").lower() == "true"
            if not write_enabled:
                return {"ok": False, "reason": "Escritura SQL desactivada por parámetro custom_api_fdccorp_ia.allow_write_sql.", "action": action}

            table_validation = self._validate_write_table(sql_lower, action)
            if not table_validation["ok"]:
                return table_validation

            column_validation = self._validate_write_columns(sql_lower, action)
            if not column_validation["ok"]:
                return column_validation

        return {"ok": True, "reason": "SQL válido.", "action": action}

    def _validate_write_table(self, sql_lower, action):
        table_name = self._extract_target_table(sql_lower, action)
        if not table_name:
            return {"ok": False, "reason": "No se pudo identificar la tabla de escritura.", "action": action}

        if not self.env["fdc.database"].sudo().is_writable_business_table(table_name):
            return {"ok": False, "reason": f"No se permite escribir sobre tabla no funcional/protegida: {table_name}", "action": action}

        return {"ok": True, "reason": "Tabla de escritura permitida.", "action": action, "table": table_name}

    def _validate_write_columns(self, sql_lower, action):
        columns = []

        if action == "insert":
            match = re.search(r"\binsert\s+into\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\((.*?)\)\s*values\b", sql_lower, re.S)
            if match:
                columns = [c.strip().strip('"') for c in match.group(1).split(",")]

        if action == "update":
            match = re.search(r"\bupdate\s+[a-zA-Z_][a-zA-Z0-9_]*\s+set\s+(.*?)\s+where\b", sql_lower, re.S)
            if match:
                set_part = match.group(1)
                columns = []
                for assignment in set_part.split(","):
                    col = assignment.split("=")[0].strip().strip('"')
                    if col:
                        columns.append(col)

        for col in columns:
            if col in self.BLOCKED_WRITE_COLUMNS:
                return {"ok": False, "reason": f"No se permite escribir sobre columna sensible: {col}", "action": action}
            if any(term in col for term in ["password", "token", "secret", "api_key"]):
                return {"ok": False, "reason": f"No se permite escribir sobre columna sensible: {col}", "action": action}

        return {"ok": True, "reason": "Columnas de escritura permitidas.", "action": action}

    def _extract_target_table(self, sql_lower, action):
        if action == "insert":
            match = re.search(r"\binsert\s+into\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", sql_lower)
            return match.group(1) if match else None
        if action == "update":
            match = re.search(r"\bupdate\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", sql_lower)
            return match.group(1) if match else None
        return None

    def _post_openai_with_retry(self, payload, api_key, url, timeout=120, max_retries=3, debug_info=None):
        debug_info = debug_info or {}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        max_payload_chars = int(self._get_param("custom_api_fdccorp_ia.max_payload_chars") or 120000)
        last_error = None

        for attempt in range(max_retries):
            try:
                payload_chars = len(json.dumps(payload, ensure_ascii=False, default=str))
                if payload_chars > max_payload_chars:
                    raise Exception(
                        f"Payload demasiado grande para IA: {payload_chars} caracteres. Máximo configurado: {max_payload_chars}."
                    )

                debug_info.setdefault("openai_attempts", [])
                debug_info["openai_attempts"].append({
                    "attempt": attempt + 1,
                    "payload_chars": payload_chars,
                    "started_at": datetime.now().isoformat(),
                })

                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
                debug_info["openai_last_status_code"] = response.status_code

                if response.status_code == 400:
                    _logger.error("IA 400 Bad Request")
                    _logger.error("IA response body: %s", response.text)
                    _logger.error("IA request model: %s", payload.get("model"))
                    _logger.error("IA payload size approx: %s characters", payload_chars)
                    raise Exception(f"IA rechazó el payload con 400 Bad Request. Detalle: {response.text}")

                if response.status_code in [401, 403]:
                    _logger.error("IA auth/permission error %s", response.status_code)
                    _logger.error("IA response body: %s", response.text)
                    raise Exception(f"Error de autenticación/permisos IA {response.status_code}. Detalle: {response.text}")

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait_seconds = int(float(retry_after)) if retry_after else min(2 ** attempt, 20)
                    _logger.warning("IA 429. Intento %s/%s. Esperando %s segundos. Body: %s", attempt + 1, max_retries, wait_seconds, response.text)
                    debug_info["openai_retry_wait_seconds"] = wait_seconds
                    time.sleep(wait_seconds)
                    continue

                if response.status_code in [500, 502, 503, 504]:
                    wait_seconds = min(2 ** attempt, 20)
                    _logger.warning("IA error %s. Intento %s/%s. Esperando %s segundos. Body: %s", response.status_code, attempt + 1, max_retries, wait_seconds, response.text)
                    debug_info["openai_retry_wait_seconds"] = wait_seconds
                    time.sleep(wait_seconds)
                    continue

                response.raise_for_status()
                debug_info["openai_success"] = True
                debug_info["openai_success_at"] = datetime.now().isoformat()
                return response

            except requests.exceptions.Timeout as e:
                last_error = e
                wait_seconds = min(2 ** attempt, 20)
                _logger.warning("Timeout llamando IA. Intento %s/%s. Esperando %s segundos.", attempt + 1, max_retries, wait_seconds)
                debug_info["openai_timeout"] = True
                debug_info["openai_retry_wait_seconds"] = wait_seconds
                time.sleep(wait_seconds)

            except requests.exceptions.RequestException as e:
                last_error = e
                _logger.exception("Error HTTP llamando IA.")
                break

        if last_error:
            raise Exception(f"No se pudo completar la llamada a IA: {str(last_error)}")

        raise Exception("IA no respondió correctamente después de varios intentos.")

    def _extract_output_text(self, data):
        if data.get("output_text"):
            return data["output_text"]

        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("text"):
                    return content["text"]
        return ""

    def _normalize(self, text):
        replacements = {
            "á": "a",
            "é": "e",
            "í": "i",
            "ó": "o",
            "ú": "u",
            "ñ": "n",
        }
        text = text or ""
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        return text

    def _get_param(self, key):
        return self.env["ir.config_parameter"].sudo().get_param(key)
