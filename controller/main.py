import json
import logging
import traceback
import uuid
from datetime import datetime

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class FdcGptController(http.Controller):

    # -------------------------------------------------------------------------
    # Endpoint principal PUBLICO SIN TOKEN
    # -------------------------------------------------------------------------

    @http.route(
        "/api/gpt/sql",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def human_query(self, **kwargs):
        """
        Endpoint publico sin autenticacion.

        IMPORTANTE:
        - No valida Bearer Token.
        - No valida api_token.
        - Permite ejecutar SELECT, INSERT y UPDATE si el servicio SQL lo valida.
        - DELETE y operaciones destructivas siguen bloqueadas en gpt_sql_service.py.
        """
        request_id = str(uuid.uuid4())
        debug_info = {
            "request_id": request_id,
            "endpoint": "/api/gpt/sql",
            "auth": "public_no_token",
            "started_at": datetime.now().isoformat(),
        }

        show_debug = False

        try:
            body = self._json_body()
            show_debug = bool(body.get("debug", False))

            debug_info["show_debug"] = show_debug
            debug_info["body_keys"] = list(body.keys())

            human_query = body.get("human_query") or body.get("pregunta") or body.get("question")
            if not human_query:
                return request.make_json_response(
                    {
                        "ok": False,
                        "error": "Debe enviar 'human_query', 'pregunta' o 'question'.",
                        "debug_info": debug_info if show_debug else None,
                    },
                    status=400,
                )

            debug_info["human_query"] = human_query
            service = request.env["fdc.gpt.sql.service"].sudo()

            _logger.info("[%s] GPT SQL public request recibido", request_id)

            # 1. Lenguaje natural -> SQL
            debug_info["step"] = "human_query_to_sql"
            sql_payload = service.human_query_to_sql(
                human_query=human_query,
                debug_info=debug_info,
            )

            sql_query = sql_payload.get("sql_query")
            sql_action = sql_payload.get("sql_action")

            debug_info["generated_sql_query"] = sql_query
            debug_info["generated_sql_action"] = sql_action

            if not sql_query:
                debug_info["finished_at"] = datetime.now().isoformat()
                return request.make_json_response(
                    {
                        "ok": False,
                        "error": "No se pudo generar SQL seguro para esta solicitud.",
                        "details": sql_payload,
                        "debug_info": debug_info if show_debug else None,
                    },
                    status=400,
                )

            # 2. Ejecutar SQL validado por el servicio
            debug_info["step"] = "query_execution"
            execution_result = service.query(
                sql_query=sql_query,
                debug_info=debug_info,
            )

            # 3. Respuesta rapida sin segunda llamada a IA por defecto
            debug_info["step"] = "build_answer"
            answer = service.build_answer(
                execution_result=execution_result,
                human_query=human_query,
                sql_query=sql_query,
                debug_info=debug_info,
            )

            debug_info["finished_at"] = datetime.now().isoformat()
            debug_info["ok"] = True

            response = {
                "ok": True,
                "answer": answer,
                "sql_query": sql_query,
                "sql_action": execution_result.get("action"),
                "rowcount": execution_result.get("rowcount"),
                "result": execution_result.get("rows"),
                "total_rows": len(execution_result.get("rows") or []),
                "sql_generation": sql_payload,
            }

            if show_debug:
                response["debug_info"] = debug_info

            return request.make_json_response(response, status=200)

        except Exception as e:
            debug_info["ok"] = False
            debug_info["error"] = str(e)
            debug_info["finished_at"] = datetime.now().isoformat()

            if show_debug:
                debug_info["traceback"] = traceback.format_exc()

            _logger.error("[%s] Error en /api/gpt/sql: %s", request_id, str(e))
            _logger.error("[%s] Traceback: %s", request_id, traceback.format_exc())

            status = self._status_from_error(str(e))

            return request.make_json_response(
                {
                    "ok": False,
                    "error": str(e),
                    "debug_info": debug_info if show_debug else {
                        "request_id": request_id,
                        "step": debug_info.get("step"),
                        "finished_at": debug_info.get("finished_at"),
                    },
                },
                status=status,
            )

    # -------------------------------------------------------------------------
    # Endpoints de schema PUBLICOS SIN TOKEN
    # -------------------------------------------------------------------------

    @http.route(
        "/api/gpt/schema/refresh",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def schema_refresh(self, **kwargs):
        """
        Endpoint publico sin autenticacion para regenerar cache de schema.
        """
        try:
            schema = request.env["fdc.database"].sudo().refresh_schema_cache()
            return request.make_json_response(
                {
                    "ok": True,
                    "message": "Schema funcional regenerado correctamente.",
                    "schema_length": len(schema or ""),
                },
                status=200,
            )
        except Exception as e:
            _logger.exception("Error regenerando schema GPT.")
            return request.make_json_response(
                {
                    "ok": False,
                    "error": str(e),
                },
                status=500,
            )

    @http.route(
        "/api/gpt/schema/tables",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
        save_session=False,
    )
    def schema_tables(self, **kwargs):
        """
        Endpoint publico sin autenticacion para listar tablas funcionales/relevantes.
        """
        try:
            relevant_query = None
            if request.httprequest.method == "POST":
                body = self._json_body()
                relevant_query = body.get("human_query") or body.get("pregunta") or body.get("question")
            else:
                relevant_query = request.httprequest.args.get("q")

            data = request.env["fdc.database"].sudo().get_schema_tables_debug(relevant_query=relevant_query)
            return request.make_json_response(
                {
                    "ok": True,
                    "business_count": data["business_count"],
                    "business_tables": data["business_tables"],
                    "relevant_query": data["relevant_query"],
                    "relevant_count": data["relevant_count"],
                    "relevant_tables": data["relevant_tables"],
                },
                status=200,
            )
        except Exception as e:
            _logger.exception("Error consultando tablas del schema GPT.")
            return request.make_json_response(
                {
                    "ok": False,
                    "error": str(e),
                },
                status=500,
            )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _json_body(self):
        raw = request.httprequest.data.decode("utf-8") if request.httprequest.data else "{}"
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise Exception("Body JSON inválido.")

    def _status_from_error(self, error_text):
        text = (error_text or "").lower()
        if "429" in text or "too many requests" in text:
            return 429
        if "timeout" in text:
            return 504
        if "sql rechazado" in text:
            return 400
        if "payload demasiado grande" in text:
            return 400
        if "body json inválido" in text:
            return 400
        return 500
