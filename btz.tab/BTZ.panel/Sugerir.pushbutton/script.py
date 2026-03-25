# -*- coding: utf-8 -*-
"""
pyRevit — Sugerir

Checklist de sugerencias BTZ; payload con CSV completo (flags 0/1 por columna temática);
n8n/OpenAI infiere columnas y devuelve candidatos; pyRevit asigna slots _01…13 en local.
"""
from __future__ import print_function

__title__ = "Sugerir"
__doc__ = (
    "Sugerencias BTZ: payload con CSV y flags temáticos para n8n/OpenAI; "
    "aplicación a slots vacíos en Revit."
)
__author__ = "btz.extension"

import os
import csv
import codecs
import clr
import json
import urllib2

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    ElementId,
    FamilyInstance,
    FamilySymbol,
    BuiltInParameter,
    Transaction,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ObjectType

from System.Windows import (
    Window,
    ResizeMode,
    Thickness,
    FontWeights,
    TextWrapping,
    HorizontalAlignment,
    VerticalAlignment,
)
from System.Windows.Controls import (
    StackPanel,
    TextBlock,
    ScrollViewer,
    Separator,
    ScrollBarVisibility,
    Button,
    CheckBox,
    DockPanel,
    Dock,
    Orientation,
)
from System.Windows.Media import Brushes

from pyrevit import revit, forms


# -----------------------------------------------------------------------------
# Rutas y CSV (misma convención que AsignarBTZ)
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(__file__)
EXT_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".."))
RESOURCES_DIR = os.path.join(EXT_DIR, "resources")
BLOCKS_CSV_FILE = os.path.join(RESOURCES_DIR, "blocks.csv")

CSV_CODE_COL = "code"
CSV_DESC_COL = "description"
CSV_START_DATE_COL = "start_date"
CSV_END_DATE_COL = "end_date"
# Columnas temáticas (0/1): todo lo que sigue a esta columna en el encabezado
CSV_LAST_BASE_COL = "displacement_date"

# -----------------------------------------------------------------------------
# Integración n8n — Production URL del webhook
# -----------------------------------------------------------------------------
N8N_WEBHOOK_URL = "https://jrcontrera.app.n8n.cloud/webhook/btz-suggest"
N8N_TIMEOUT_SEC = 60

RULES_FOR_WEBHOOK = {
    u"max_suggestions": 5,
    u"do_not_repeat_existing_values": True,
    u"infer_columns_first": True,
}

PARAM_BASE = "BTZ_Description"
PARAM_NUMERIC = [
    "BTZ_Description_01",
    "BTZ_Description_02",
    "BTZ_Description_03",
    "BTZ_Description_04",
    "BTZ_Description_05",
    "BTZ_Description_06",
    "BTZ_Description_07",
    "BTZ_Description_08",
    "BTZ_Description_09",
    "BTZ_Description_10",
    "BTZ_Description_11",
    "BTZ_Description_12",
    "BTZ_Description_13",
]
ALL_BTZ_PARAMS = [PARAM_BASE] + PARAM_NUMERIC

# Tras marcar checkboxes: orden por confidence descendente.
# Alternativa: sorted(sel, key=lambda s: s["_ui_index"]) para orden del checklist.


def _element_id_as_int(element_id):
    try:
        return element_id.IntegerValue
    except AttributeError:
        return int(element_id.Value)


def _safe_type_display_name(elem):
    if elem is None:
        return ""
    try:
        n = elem.Name
        if n is not None:
            return n
    except Exception:
        pass
    for bip in (
        BuiltInParameter.ALL_MODEL_TYPE_NAME,
        BuiltInParameter.SYMBOL_NAME_PARAM,
    ):
        try:
            p = elem.get_Parameter(bip)
            if p is not None and p.HasValue:
                s = p.AsString()
                if s:
                    return s
        except Exception:
            pass
    return ""


def _safe_family_display_name(fam):
    if fam is None:
        return ""
    try:
        n = fam.Name
        if n is not None:
            return n
    except Exception:
        pass
    try:
        p = fam.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
        if p is not None and p.HasValue:
            s = p.AsString()
            if s:
                return s
    except Exception:
        pass
    return ""


def _param_value_as_string(element, param_name):
    p = element.LookupParameter(param_name)
    if p is None or not p.HasValue:
        return ""
    try:
        st = p.AsString()
        if st is not None:
            return st
    except Exception:
        pass
    try:
        return p.AsValueString() or ""
    except Exception:
        return ""


def _safe_category_name(element):
    cat = element.Category
    return cat.Name if cat is not None else ""


def _family_and_type_names(doc, element):
    family_name = ""
    type_name = ""

    tid = element.GetTypeId()
    if tid and tid != ElementId.InvalidElementId:
        et = doc.GetElement(tid)
        if et is not None:
            type_name = _safe_type_display_name(et)
            if isinstance(et, FamilySymbol):
                fam = et.Family
                family_name = _safe_family_display_name(fam)
                if not family_name:
                    try:
                        p = et.get_Parameter(
                            BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM
                        )
                        if p is not None and p.HasValue:
                            family_name = p.AsString() or ""
                    except Exception:
                        pass

    return family_name, type_name


def _level_name(doc, element):
    if isinstance(element, FamilyInstance):
        lvl_id = element.LevelId
        if lvl_id and lvl_id != ElementId.InvalidElementId:
            lvl = doc.GetElement(lvl_id)
            if lvl is not None:
                return lvl.Name or ""

    try:
        p = element.get_Parameter(BuiltInParameter.LEVEL_PARAM)
        if p is not None and p.HasValue:
            lid = p.AsElementId()
            if lid and lid != ElementId.InvalidElementId:
                lvl = doc.GetElement(lid)
                if lvl is not None:
                    return lvl.Name or ""
    except Exception:
        pass

    for alt in ("Nivel", "Level", "Reference Level", "Nivel de referencia"):
        v = _param_value_as_string(element, alt)
        if v:
            return v

    return ""


def build_element_context(doc, element):
    eid = _element_id_as_int(element.Id)
    family_name, type_name = _family_and_type_names(doc, element)
    params = {}
    for name in ALL_BTZ_PARAMS:
        params[name] = _param_value_as_string(element, name)

    return {
        "element_id": eid,
        "category_name": _safe_category_name(element),
        "family_name": family_name,
        "type_name": type_name,
        "level_name": _level_name(doc, element),
        "parameters": params,
    }


def missing_btz_parameters(element):
    missing = []
    for name in ALL_BTZ_PARAMS:
        if element.LookupParameter(name) is None:
            missing.append(name)
    return missing


def _is_slot_empty(display_value):
    return not (display_value or u"").strip()


def _norm_key(s):
    return (s or u"").strip().lower()


def _format_stored_value(matched_code, suggested_value):
    c = (matched_code or u"").strip()
    v = (suggested_value or u"").strip()
    if c and v:
        return u"{0} - {1}".format(c, v)
    return v or c


def suggestion_already_on_element(element, suggestion):
    code = suggestion.get("matched_code") or u""
    sugg = suggestion.get("suggested_value") or u""
    full = _norm_key(_format_stored_value(code, sugg))
    only_desc = _norm_key(sugg)
    if not full and not only_desc:
        return False

    for pname in PARAM_NUMERIC:
        existing = _param_value_as_string(element, pname)
        en = _norm_key(existing)
        if not en:
            continue
        if full and en == full:
            return True
        if only_desc and en == only_desc:
            return True
    return False


def list_empty_slots_in_order(element):
    empty = []
    for pname in PARAM_NUMERIC:
        val = _param_value_as_string(element, pname)
        if _is_slot_empty(val):
            empty.append(pname)
    return empty


def _cell_flag_01(cell):
    """Convierte celda CSV temática a 0 o 1."""
    v = unicode(cell or u"").strip()
    if v == u"1":
        return 1
    return 0


def load_btz_blocks_csv(csv_path):
    """
    Lee blocks.csv y separa:
    - fixed_columns: nombres reales de columnas base (code, description, fechas).
    - thematic_columns: columnas 0/1 después de displacement_date.
    - rows: cada fila con code, description, fechas y flags {columna: 0|1}.
    """
    if not csv_path or not os.path.isfile(csv_path):
        raise IOError(u"No se encontró el CSV: {0}".format(csv_path))

    encodings = [u"utf-8-sig", u"utf-8", u"cp1252", u"latin1"]
    last_error = None

    for enc in encodings:
        try:
            with codecs.open(csv_path, "r", enc) as fp:
                sample = fp.read(4096)
                fp.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=u";,")
                    delimiter = dialect.delimiter
                except Exception:
                    delimiter = u";" if sample.count(u";") > sample.count(u",") else u","

                reader = csv.DictReader(fp, delimiter=delimiter)
                if not reader.fieldnames:
                    continue

                fields = [f.strip() for f in reader.fieldnames]
                code_field = None
                desc_field = None
                start_field = None
                end_field = None
                displ_field = None

                for f in fields:
                    low = f.lower().strip()
                    if low == CSV_CODE_COL:
                        code_field = f
                    if low == CSV_DESC_COL:
                        desc_field = f
                    if low == CSV_START_DATE_COL:
                        start_field = f
                    if low == CSV_END_DATE_COL:
                        end_field = f
                    if low == CSV_LAST_BASE_COL.lower():
                        displ_field = f

                if not desc_field:
                    raise ValueError(u"El CSV no tiene columna description")

                dd_idx = None
                for i, f in enumerate(fields):
                    if displ_field and f == displ_field:
                        dd_idx = i
                        break
                    if f.lower().strip() == CSV_LAST_BASE_COL.lower():
                        dd_idx = i
                        break

                if dd_idx is None:
                    raise ValueError(
                        u"El CSV no tiene columna {0}".format(CSV_LAST_BASE_COL)
                    )

                thematic_columns = [
                    fields[j] for j in range(dd_idx + 1, len(fields)) if fields[j]
                ]

                fixed_columns = {
                    u"code": code_field,
                    u"description": desc_field,
                    u"start_date": start_field,
                    u"end_date": end_field,
                    u"displacement_date": displ_field,
                }

                rows = []
                seen = set()
                for row in reader:
                    code = (row.get(code_field, u"") if code_field else u"").strip()
                    desc = (row.get(desc_field, u"") if desc_field else u"").strip()
                    if not desc:
                        continue

                    flags = {}
                    for tc in thematic_columns:
                        flags[tc] = _cell_flag_01(row.get(tc, u""))

                    key = (code, desc)
                    if key in seen:
                        continue
                    seen.add(key)

                    rows.append({
                        u"code": code,
                        u"description": desc,
                        u"start_date": (
                            (row.get(start_field, u"") or u"").strip()
                            if start_field
                            else u""
                        ),
                        u"end_date": (
                            (row.get(end_field, u"") or u"").strip()
                            if end_field
                            else u""
                        ),
                        u"displacement_date": (
                            (row.get(displ_field, u"") or u"").strip()
                            if displ_field
                            else u""
                        ),
                        u"flags": flags,
                    })

                rows.sort(key=lambda x: (x[u"description"] or u"").lower())
                if not rows:
                    raise ValueError(u"El CSV no tiene filas útiles")

                return {
                    u"fixed_columns": fixed_columns,
                    u"thematic_columns": thematic_columns,
                    u"rows": rows,
                }
        except Exception as ex:
            last_error = ex
            continue

    raise ValueError(
        u"No se pudo leer el CSV. Error: {0}".format(last_error)
    )


def _project_display_name(doc):
    try:
        t = doc.Title
        if t:
            return t
    except Exception:
        pass
    try:
        p = doc.PathName
        if p:
            return os.path.splitext(os.path.basename(p))[0]
    except Exception:
        pass
    return u"(sin título)"


def _active_view_name(uidoc):
    try:
        v = uidoc.ActiveView
        if v is not None:
            return v.Name or u""
    except Exception:
        pass
    return u""


def _occupied_btz_values(element):
    """Valores no vacíos actuales en BTZ_Description y _01…_13."""
    vals = []
    seen = set()
    for pname in ALL_BTZ_PARAMS:
        raw = _param_value_as_string(element, pname)
        s = (raw or u"").strip()
        if not s:
            continue
        k = _norm_key(s)
        if k in seen:
            continue
        seen.add(k)
        vals.append(s)
    return vals


def build_sugerir_webhook_payload(
    doc,
    uidoc,
    element,
    note_text=None,
    note_source=u"manual",
):
    """
    Arma el JSON exacto que pyRevit envía al webhook n8n.

    Se envía:
    - mode, project_name, view_name
    - element (element_id, unique_id, category_name, family_name, type_name, level_name)
    - note_context (note_text, source)
    - btz_state (todos los BTZ_Description actuales)
    - free_slots (BTZ_Description_01…13 vacíos)
    - occupied_values (valores no vacíos ya cargados)
    - thematic_columns (columnas 0/1 del CSV)
    - csv_rows (filas con code, description, fechas, flags)
    - rules (max_suggestions, do_not_repeat_existing_values, infer_columns_first)

    n8n NO devuelve target_parameter; pyRevit resuelve slots en local.
    """
    csv_struct = load_btz_blocks_csv(BLOCKS_CSV_FILE)

    btz_state = {}
    for pname in ALL_BTZ_PARAMS:
        btz_state[pname] = _param_value_as_string(element, pname)

    free_slots = list_empty_slots_in_order(element)
    occupied_values = _occupied_btz_values(element)

    uid = u""
    try:
        uid = element.UniqueId or u""
    except Exception:
        pass

    fam_name, typ_name = _family_and_type_names(doc, element)
    cat_name = _safe_category_name(element)
    lvl_name = _level_name(doc, element)

    nt = (note_text or u"").strip()
    src = note_source or u"manual"

    return {
        u"mode": u"suggest_btz_by_column_inference",
        u"project_name": _project_display_name(doc),
        u"view_name": _active_view_name(uidoc),
        u"element": {
            u"element_id": _element_id_as_int(element.Id),
            u"unique_id": uid,
            u"category_name": cat_name,
            u"family_name": fam_name,
            u"type_name": typ_name,
            u"level_name": lvl_name,
        },
        u"note_context": {
            u"note_text": nt,
            u"source": src,
        },
        u"btz_state": btz_state,
        u"free_slots": free_slots,
        u"occupied_values": occupied_values,
        u"thematic_columns": list(csv_struct[u"thematic_columns"]),
        u"csv_rows": csv_struct[u"rows"],
        u"rules": dict(RULES_FOR_WEBHOOK),
    }


def print_webhook_payload_debug(payload, title=u"[Sugerir] Webhook payload (JSON)"):
    """Serializa el payload con indentación para la consola pyRevit."""
    try:
        txt = json.dumps(payload, ensure_ascii=False, indent=2)
        sep = u"\n" + (u"=" * 72) + u"\n"
        print(sep + title + sep + txt + sep)
    except Exception as ex:
        print(u"[Sugerir] No se pudo serializar payload: {0}".format(ex))


def _mock_infer_thematic_columns(category_name, thematic_columns):
    """
    Simula inferencia de columnas (sustituir por lógica real en n8n/OpenAI).
    """
    if not thematic_columns:
        return []

    cn = (category_name or u"").upper()
    cn_compact = cn.replace(u" ", u"").replace(u"_", u"")

    inferred = []
    for col in thematic_columns:
        c2 = col.upper().replace(u" ", u"")
        if not c2:
            continue
        if c2 in cn or c2 in cn_compact:
            inferred.append({
                u"column_name": col,
                u"confidence": 0.88,
                u"reason": u"Mock: nombre de columna contenido en la categoría Revit",
            })
            continue
        for token in cn.replace(u"_", u" ").split():
            t = token.strip().upper()
            if len(t) >= 4 and t in c2:
                inferred.append({
                    u"column_name": col,
                    u"confidence": 0.72,
                    u"reason": u"Mock: token de categoría relacionado con columna",
                })
                break

    seen = set()
    dedup = []
    for item in inferred:
        k = item[u"column_name"]
        if k in seen:
            continue
        seen.add(k)
        dedup.append(item)

    if not dedup:
        preferred = (
            u"GENERAL",
            u"ESTRUCTURA",
            u"ARQUITECTURA",
            u"INSTALACION ELECTRICA",
        )
        for pref in preferred:
            for col in thematic_columns:
                if col.upper() == pref:
                    dedup.append({
                        u"column_name": col,
                        u"confidence": 0.65,
                        u"reason": u"Mock: columna temática por defecto {0}".format(
                            pref
                        ),
                    })
                    break
            if dedup:
                break

    if not dedup:
        dedup.append({
            u"column_name": thematic_columns[0],
            u"confidence": 0.45,
            u"reason": u"Mock: fallback primera columna temática del CSV",
        })

    return dedup[:5]


def fetch_suggestions_mock(webhook_payload):
    """
    Simula n8n: inferred_columns + filas CSV con flag=1 en esas columnas +
    suggestions ordenadas por confianza (sin target_parameter).

    Contrato de salida alineado con OpenAI/n8n real.
    """
    el_block = webhook_payload.get(u"element") or {}
    eid = el_block.get(u"element_id", 0)
    cat = el_block.get(u"category_name") or u""

    thematic = webhook_payload.get(u"thematic_columns") or []
    csv_rows = webhook_payload.get(u"csv_rows") or []
    rules = webhook_payload.get(u"rules") or {}
    try:
        max_sug = int(rules.get(u"max_suggestions") or 5)
    except Exception:
        max_sug = 5

    inferred_columns = _mock_infer_thematic_columns(cat, thematic)
    inferred_names = [x[u"column_name"] for x in inferred_columns]

    matched = []
    for r in csv_rows:
        flags = r.get(u"flags") or {}
        ok = False
        for c in inferred_names:
            if flags.get(c) == 1:
                ok = True
                break
        if ok:
            matched.append(r)

    suggestions = []
    for i, r in enumerate(matched[: max_sug * 2]):
        code = (r.get(u"code") or u"").strip()
        desc = (r.get(u"description") or u"").strip()
        if not desc:
            continue
        flags = r.get(u"flags") or {}
        mcols = [c for c in inferred_names if flags.get(c) == 1]
        dv = _format_stored_value(code, desc)
        suggestions.append({
            u"matched_code": code,
            u"suggested_value": desc,
            u"display_value": dv,
            u"matching_columns": mcols,
            u"confidence": max(0.35, 0.92 - (i * 0.04)),
            u"reason": u"Mock: fila con flag=1 en columnas inferidas",
            u"already_present": False,
        })

    suggestions.sort(key=lambda x: -float(x.get(u"confidence") or 0))
    suggestions = suggestions[:max_sug]

    low_conf = inferred_columns and float(
        inferred_columns[0].get(u"confidence") or 0
    ) < 0.55

    return {
        u"mode": u"suggest_btz_result",
        u"element_id": eid,
        u"inferred_columns": inferred_columns,
        u"suggestions": suggestions,
        u"needs_review": bool(low_conf or not suggestions),
    }


def call_n8n(payload, timeout=None):
    """
    Envía el payload al webhook n8n y devuelve el JSON parseado.

    Raises ValueError con mensaje claro si:
    - timeout
    - status HTTP != 200
    - respuesta vacía
    - JSON inválido

    Debug: imprime URL, payload (resumido), status, response (resumido).
    """
    url = N8N_WEBHOOK_URL
    if not url:
        raise ValueError(u"N8N_WEBHOOK_URL no configurada")

    tout = timeout if timeout is not None else N8N_TIMEOUT_SEC

    print(u"[Sugerir] URL: {0}".format(url))
    try:
        payload_preview = json.dumps(payload, ensure_ascii=False)
        print(u"[Sugerir] Payload enviado ({0} chars): {1}...".format(
            len(payload_preview), payload_preview[:400]
        ))
    except Exception:
        print(u"[Sugerir] Payload (no serializable para debug)")

    data = json.dumps(payload, ensure_ascii=False)
    if isinstance(data, unicode):
        data = data.encode("utf-8")

    req = urllib2.Request(
        url,
        data,
        headers={u"Content-Type": u"application/json; charset=utf-8"},
    )

    try:
        resp = urllib2.urlopen(req, timeout=tout)
    except urllib2.HTTPError as e:
        print(u"[Sugerir] HTTP Error {0}".format(e.code))
        try:
            body = e.read()
            if isinstance(body, str):
                body = body.decode("utf-8")
            if isinstance(body, bytes):
                body = body.decode("utf-8")
        except Exception:
            body = u"(no se pudo leer)"
        print(u"[Sugerir] Response body: {0}".format(body[:500]))
        raise ValueError(
            u"n8n devolvió HTTP {0}. {1}".format(e.code, body[:300])
        )
    except urllib2.URLError as e:
        print(u"[Sugerir] URLError: {0}".format(e.reason))
        msg = unicode(e.reason) if e.reason else u"Error de red"
        if u"timed out" in msg.lower() or u"timeout" in msg.lower():
            raise ValueError(u"Timeout al conectar con n8n ({0}s)".format(tout))
        raise ValueError(u"No se pudo conectar con n8n: {0}".format(msg))
    except Exception as e:
        print(u"[Sugerir] Error: {0}".format(e))
        raise ValueError(u"Error al llamar n8n: {0}".format(unicode(e)))

    raw = resp.read()
    if hasattr(raw, "decode"):
        raw = raw.decode("utf-8")

    code = resp.getcode()
    print(u"[Sugerir] Status: {0}".format(code))
    print(u"[Sugerir] Response ({0} chars): {1}...".format(
        len(raw), raw[:500]
    ))

    if code != 200:
        raise ValueError(
            u"n8n devolvió HTTP {0}. Respuesta: {1}".format(code, raw[:300])
        )

    if not raw or not raw.strip():
        raise ValueError(u"n8n devolvió respuesta vacía")

    try:
        parsed = json.loads(raw)
    except ValueError as e:
        raise ValueError(
            u"n8n devolvió JSON inválido: {0}. Raw: {1}".format(
                unicode(e), raw[:200]
            )
        )

    return parsed


def validate_n8n_response(parsed):
    """
    Valida que la respuesta de n8n tenga la estructura esperada.

    Esperado:
    - suggestions: lista
    - cada item: matched_code, suggested_value, display_value, matching_columns,
      confidence, reason, already_present

    Raises ValueError con mensaje claro si falta algo.
    """
    if parsed is None:
        raise ValueError(u"Respuesta de n8n es None")

    sug = parsed.get(u"suggestions") or parsed.get("suggestions")
    if sug is None:
        keys = list(parsed.keys()) if hasattr(parsed, "keys") else []
        raise ValueError(
            u"n8n no devolvió el campo 'suggestions'. "
            u"Campos recibidos: {0}".format(u", ".join(unicode(k) for k in keys))
        )

    if not isinstance(sug, list):
        raise ValueError(
            u"'suggestions' debe ser una lista, no {0}".format(type(sug))
        )

    REQUIRED = [
        u"matched_code",
        u"suggested_value",
        u"display_value",
        u"matching_columns",
        u"confidence",
        u"reason",
        u"already_present",
    ]

    for i, item in enumerate(sug):
        if not isinstance(item, dict):
            raise ValueError(
                u"Sugerencia #{0} no es un objeto: {1}".format(i + 1, type(item))
            )
        for key in REQUIRED:
            if key not in item and str(key) not in item:
                raise ValueError(
                    u"Sugerencia #{0} no tiene '{1}'. "
                    u"Campos: {2}".format(
                        i + 1,
                        key,
                        u", ".join(unicode(k) for k in item.keys()),
                    )
                )

    return parsed


def fetch_suggestions_for_payload(webhook_payload):
    """
    Punto único: llama al webhook n8n real, valida la respuesta y la devuelve.

    Flujo principal: call_n8n -> validate_n8n_response -> retorno.
    Si falla (timeout, HTTP != 200, JSON inválido, sin suggestions):
    lanza ValueError con mensaje claro; la UI lo muestra y no rompe el flujo.

    Fallback opcional (comentado): usar fetch_suggestions_mock si n8n no está.
    """
    if not N8N_WEBHOOK_URL:
        raise ValueError(
            u"N8N_WEBHOOK_URL no configurada. "
            u"Definir la URL del webhook al inicio del script."
        )

    parsed = call_n8n(webhook_payload)
    validate_n8n_response(parsed)
    return parsed

    # Fallback opcional si n8n no está disponible (descomentar para usar mock):
    # try:
    #     parsed = call_n8n(webhook_payload)
    #     validate_n8n_response(parsed)
    #     return parsed
    # except (ValueError, Exception) as e:
    #     print(u"[Sugerir] Webhook falló, usando mock: {0}".format(e))
    #     return fetch_suggestions_mock(webhook_payload)


def n8n_response_to_ui_bundle(api_result):
    """
    Adapta suggest_btz_result (inferred_columns + suggestions) al checklist.
    Orden: confidence descendente. Sin target_parameter.
    """
    raw = api_result.get("suggestions")
    if raw is None:
        raw = api_result.get(u"suggestions")
    if not raw or not isinstance(raw, list):
        raw = []

    inf = api_result.get("inferred_columns")
    if inf is None:
        inf = api_result.get(u"inferred_columns")
    if not inf or not isinstance(inf, list):
        inf = []

    inferred_clean = []
    for it in inf:
        if not isinstance(it, dict):
            continue
        try:
            cf = float(it.get("confidence", it.get(u"confidence", 0)) or 0)
        except Exception:
            cf = 0.0
        inferred_clean.append({
            u"column_name": unicode(
                it.get("column_name") or it.get(u"column_name") or u""
            ),
            u"confidence": cf,
            u"reason": unicode(it.get("reason") or it.get(u"reason") or u""),
        })

    sug = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        code = unicode(s.get("matched_code") or s.get(u"matched_code") or u"").strip()
        val = unicode(
            s.get("suggested_value") or s.get(u"suggested_value") or u""
        ).strip()
        disp = s.get("display_value")
        if disp is None:
            disp = s.get(u"display_value")
        if disp is None or disp == u"":
            disp = _format_stored_value(code, val)
        else:
            disp = unicode(disp)

        try:
            conf = float(s.get("confidence", s.get(u"confidence", 0)))
        except Exception:
            conf = 0.0

        mc = s.get("matching_columns")
        if mc is None:
            mc = s.get(u"matching_columns")
        if not isinstance(mc, list):
            mc = []
        mc = [unicode(x) for x in mc]

        alr = s.get("already_present", s.get(u"already_present", False))

        sug.append({
            u"matched_code": code,
            u"suggested_value": val,
            u"confidence": conf,
            u"reason": unicode(s.get("reason") or s.get(u"reason") or u""),
            u"display_value": disp,
            u"matching_columns": mc,
            u"already_present": bool(alr),
        })

    sug.sort(key=lambda x: -x[u"confidence"])

    eid = api_result.get("element_id")
    if eid is None:
        eid = api_result.get(u"element_id")

    nr = api_result.get("needs_review", api_result.get(u"needs_review", False))

    return {
        u"element_id": eid,
        u"needs_review": bool(nr),
        u"inferred_columns": inferred_clean,
        u"suggestions": sug,
    }


def _fmt_confidence(c):
    try:
        return u"{0:.0%}".format(float(c))
    except Exception:
        return unicode(c)


def set_text_parameter(element, param_name, value):
    param = element.LookupParameter(param_name)
    if param is None:
        return False, u"sin parámetro"
    if param.IsReadOnly:
        return False, u"solo lectura"
    try:
        param.Set(value)
        return True, None
    except Exception as ex:
        return False, unicode(ex)


def apply_suggestions_to_element(doc, element, slot_assignments):
    tx = Transaction(doc, u"Sugerir BTZ")
    tx.Start()
    try:
        ok_star, err_star = set_text_parameter(element, PARAM_BASE, u"*")
        if not ok_star:
            tx.RollBack()
            return False, [], u"No se pudo escribir {0}: {1}".format(
                PARAM_BASE, err_star
            )

        applied = []
        for pname, val in slot_assignments:
            ok, err = set_text_parameter(element, pname, val)
            if not ok:
                tx.RollBack()
                return False, [], u"Error en {0}: {1}".format(pname, err)
            applied.append((pname, val))

        tx.Commit()
        return True, applied, None
    except Exception as ex:
        try:
            tx.RollBack()
        except Exception:
            pass
        return False, [], unicode(ex)


def _dedupe_suggestions_by_storage(suggestions):
    best = {}
    for s in suggestions:
        key = _norm_key(
            _format_stored_value(
                s.get("matched_code") or u"",
                s.get("suggested_value") or u"",
            )
        )
        if not key:
            key = _norm_key(s.get("suggested_value") or u"")
        if not key:
            continue
        conf = float(s.get("confidence") or 0.0)
        if key not in best or conf > best[key][0]:
            best[key] = (conf, s)
    return [pair[1] for pair in best.values()]


def prepare_application_plan(element, raw_selected):
    if not raw_selected:
        return False, [], [], u"No hay sugerencias seleccionadas."

    ranked = sorted(
        raw_selected,
        key=lambda s: float(s.get("confidence") or 0.0),
        reverse=True,
    )
    ranked = _dedupe_suggestions_by_storage(ranked)

    skipped_dup = []
    to_apply = []
    for s in ranked:
        if suggestion_already_on_element(element, s):
            label = _format_stored_value(
                s.get("matched_code") or u"",
                s.get("suggested_value") or u"",
            )
            skipped_dup.append(
                u"Ya presente en el elemento, omitida: {0}".format(label)
            )
            continue
        to_apply.append(s)

    if not to_apply:
        return False, [], skipped_dup, u"Todas las sugerencias ya están en los slots BTZ."

    empty_slots = list_empty_slots_in_order(element)
    need = len(to_apply)
    avail = len(empty_slots)
    if need > avail:
        msg = (
            u"Hay {0} sugerencia(s) para aplicar pero solo {1} slot(s) libre(s) "
            u"(BTZ_Description_01…13). No se aplicará ningún cambio.\n\n"
            u"Liberá slots o marcá menos ítems."
        ).format(need, avail)
        return False, [], skipped_dup, msg

    slot_assignments = []
    for i, s in enumerate(to_apply):
        pname = empty_slots[i]
        val = _format_stored_value(
            s.get("matched_code") or u"",
            s.get("suggested_value") or u"",
        )
        slot_assignments.append((pname, val))

    return True, slot_assignments, skipped_dup, None


def show_sugerir_window(elements, sample_context, api_response):
    """
    elements: lista no vacía de Element (todos con BTZ ya validados).
    sample_context: contexto del primer elemento (encabezado + estado BTZ de referencia).
    """
    sug_list = api_response.get("suggestions") or []
    outcome = {"apply": False, "per_element": []}

    root = DockPanel()
    root.LastChildFill = True

    main_panel = StackPanel()
    main_panel.Margin = Thickness(16, 16, 16, 8)

    title = TextBlock()
    title.Text = u"Sugerencias BTZ"
    title.FontSize = 18
    title.FontWeight = FontWeights.Bold
    title.Margin = Thickness(0, 0, 0, 10)
    main_panel.Children.Add(title)

    hdr = TextBlock()
    hdr.TextWrapping = TextWrapping.Wrap
    hdr.Margin = Thickness(0, 0, 0, 8)
    hdr.Foreground = Brushes.DarkSlateGray
    n_el = len(elements)
    id_lines = []
    max_ids = 18
    for i, el in enumerate(elements[:max_ids]):
        id_lines.append(unicode(_element_id_as_int(el.Id)))
    ids_txt = u", ".join(id_lines)
    if n_el > max_ids:
        ids_txt += u" … (+{0} más)".format(n_el - max_ids)

    hdr.Text = (
        u"{0} elemento(s) · Ids: {1} · {2}"
    ).format(
        n_el,
        ids_txt,
        sample_context.get("category_name") or u"(sin categoría)",
    )
    main_panel.Children.Add(hdr)

    main_panel.Children.Add(Separator())

    chk_title = TextBlock()
    chk_title.Text = u"Sugerencias — marcá las que querés aplicar"
    chk_title.FontWeight = FontWeights.SemiBold
    chk_title.Margin = Thickness(0, 10, 0, 6)
    main_panel.Children.Add(chk_title)

    scroll_sug = ScrollViewer()
    scroll_sug.MaxHeight = 520
    scroll_sug.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    sug_stack = StackPanel()

    check_pairs = []

    if not sug_list:
        empty = TextBlock()
        empty.Text = u"No hay sugerencias en la respuesta."
        empty.Foreground = Brushes.Gray
        sug_stack.Children.Add(empty)
    else:
        for i, s in enumerate(sug_list):
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            row.Margin = Thickness(0, 2, 0, 2)

            cb = CheckBox()
            cb.VerticalAlignment = VerticalAlignment.Top
            cb.Margin = Thickness(0, 2, 8, 0)

            detail = StackPanel()
            code = s.get("matched_code") or u""
            val = s.get("suggested_value") or u""
            disp = s.get("display_value") or u""
            line1 = TextBlock()
            line1.FontWeight = FontWeights.SemiBold
            line1.TextWrapping = TextWrapping.Wrap
            line1.Text = disp if disp else u"{0} - {1}".format(code, val).strip(u" -")
            if s.get("already_present"):
                line1.Foreground = Brushes.DarkOrange

            line2 = TextBlock()
            line2.TextWrapping = TextWrapping.Wrap
            line2.Margin = Thickness(0, 2, 0, 0)
            line2.Foreground = Brushes.DimGray
            reason = s.get("reason") or u""
            line2.Text = u"{0} · {1}".format(
                _fmt_confidence(s.get("confidence")),
                reason[:60] + (u"…" if len(reason) > 60 else u""),
            )

            detail.Children.Add(line1)
            detail.Children.Add(line2)

            row.Children.Add(cb)
            row.Children.Add(detail)
            sug_stack.Children.Add(row)

            s_copy = dict(s)
            s_copy["_ui_index"] = i
            check_pairs.append((cb, s_copy))

    scroll_sug.Content = sug_stack
    main_panel.Children.Add(scroll_sug)

    btn_panel = StackPanel()
    btn_panel.Orientation = Orientation.Horizontal
    btn_panel.HorizontalAlignment = HorizontalAlignment.Right
    btn_panel.Margin = Thickness(16, 8, 16, 16)

    win = Window()
    win.Title = u"Sugerir — BTZ"
    win.Width = 540
    win.Height = 720
    win.ResizeMode = ResizeMode.CanResize
    win.MinWidth = 480
    win.MinHeight = 500

    def on_apply(sender, args):
        chosen = []
        for cb, s in check_pairs:
            if cb.IsChecked is True:
                chosen.append(s)

        if not chosen:
            forms.alert(
                u"Marcá al menos una sugerencia o pulsá Cancelar.",
                title=u"Sugerir",
                warn_icon=False,
            )
            return

        per_ok = []
        failed = []
        for el in elements:
            ok, assignments, skipped_info, err = prepare_application_plan(
                el, chosen
            )
            if ok:
                per_ok.append((el, assignments, skipped_info))
            else:
                failed.append((el, err, skipped_info))

        if not per_ok:
            parts = [u"Ningún elemento puede recibir estas sugerencias."]
            for el, err, skipped_info in failed[:12]:
                eid = _element_id_as_int(el.Id)
                parts.append(u"\nId {0}: {1}".format(eid, err or u""))
                if skipped_info:
                    parts.append(u"  " + u"\n  ".join(skipped_info))
            if len(failed) > 12:
                parts.append(u"\n… y {0} más.".format(len(failed) - 12))
            forms.alert(
                u"".join(parts),
                title=u"Sugerir — no se aplicó nada",
                warn_icon=True,
            )
            return

        if failed:
            flines = []
            for el, err, _ski in failed[:15]:
                flines.append(
                    u"Id {0}: {1}".format(_element_id_as_int(el.Id), err or u"")
                )
            if len(failed) > 15:
                flines.append(u"… (+{0})".format(len(failed) - 15))
            forms.alert(
                u"Se aplicará a {0} de {1} elemento(s). "
                u"Estos no cumplen (slots / duplicados):\n\n{2}".format(
                    len(per_ok),
                    len(elements),
                    u"\n".join(flines),
                ),
                title=u"Sugerir — aplicación parcial",
                warn_icon=True,
            )

        outcome["apply"] = True
        outcome["per_element"] = per_ok
        win.Close()

    def on_cancel(sender, args):
        outcome["apply"] = False
        win.Close()

    btn_apply = Button()
    btn_apply.Content = u"Aplicar seleccionadas"
    btn_apply.Margin = Thickness(0, 0, 8, 0)
    btn_apply.MinWidth = 140
    btn_apply.Click += on_apply

    btn_cancel = Button()
    btn_cancel.Content = u"Cancelar"
    btn_cancel.MinWidth = 100
    btn_cancel.Click += on_cancel

    btn_panel.Children.Add(btn_apply)
    btn_panel.Children.Add(btn_cancel)

    DockPanel.SetDock(btn_panel, Dock.Bottom)
    root.Children.Add(btn_panel)
    root.Children.Add(main_panel)

    win.Content = root
    win.ShowDialog()

    if not outcome.get("apply"):
        return None

    return {"per_element": outcome["per_element"]}


def _pick_elements_multiselect(uidoc, doc):
    """PickObjects: el usuario puede elegir muchos elementos; termina con Fin."""
    refs = uidoc.Selection.PickObjects(
        ObjectType.Element,
        u"Seleccione uno o más elementos (Fin para terminar)",
    )
    seen = set()
    elements = []
    for r in refs:
        key = _element_id_as_int(r.ElementId)
        if key in seen:
            continue
        seen.add(key)
        el = doc.GetElement(r.ElementId)
        if el is not None:
            elements.append(el)
    return elements


def main():
    doc = revit.doc
    uidoc = revit.uidoc

    try:
        elements = _pick_elements_multiselect(uidoc, doc)
    except OperationCanceledException:
        return
    except Exception as ex:
        forms.alert(
            u"No se pudo completar la selección:\n{0}".format(ex),
            title=u"Sugerir",
            warn_icon=True,
        )
        return

    if not elements:
        forms.alert(
            u"No se seleccionó ningún elemento.",
            title=u"Sugerir",
            warn_icon=False,
        )
        return

    valid = []
    invalid_lines = []
    for el in elements:
        missing = missing_btz_parameters(el)
        if missing:
            eid = _element_id_as_int(el.Id)
            invalid_lines.append(
                u"Id {0}: faltan parámetros BTZ ({1}…)".format(
                    eid,
                    u", ".join(missing[:3]),
                )
            )
        else:
            valid.append(el)

    if invalid_lines and not valid:
        forms.alert(
            u"Ningún elemento tiene los parámetros BTZ enlazados.\n\n"
            + u"\n".join(invalid_lines[:15]),
            title=u"Sugerir",
            warn_icon=True,
        )
        return

    if invalid_lines:
        forms.alert(
            u"Se omiten {0} elemento(s) sin BTZ completos. "
            u"Continuá con {1} válido(s).\n\n{2}".format(
                len(invalid_lines),
                len(valid),
                u"\n".join(invalid_lines[:12]),
            ),
            title=u"Sugerir",
            warn_icon=True,
        )

    first = valid[0]
    sample_context = build_element_context(doc, first)

    try:
        webhook_payload = build_sugerir_webhook_payload(doc, uidoc, first)
    except Exception as ex:
        forms.alert(
            u"No se pudo armar el payload ni cargar el CSV de bloques:\n{0}".format(ex),
            title=u"Sugerir",
            warn_icon=True,
        )
        return

    print_webhook_payload_debug(webhook_payload)

    # Integración n8n: fetch_suggestions_for_payload llama call_n8n (webhook real),
    # valida la respuesta y la devuelve. Si falla, muestra error y no rompe el flujo.
    try:
        api_raw = fetch_suggestions_for_payload(webhook_payload)
    except NotImplementedError as ex:
        forms.alert(unicode(ex), title=u"Sugerir", warn_icon=True)
        return
    except Exception as ex:
        forms.alert(
            u"Error al obtener sugerencias (webhook):\n{0}".format(ex),
            title=u"Sugerir",
            warn_icon=True,
        )
        return

    ui_bundle = n8n_response_to_ui_bundle(api_raw)

    dlg_result = show_sugerir_window(valid, sample_context, ui_bundle)
    if dlg_result is None:
        return

    per_element = dlg_result["per_element"]
    summary_blocks = []
    any_error = False

    for el, assignments, skipped in per_element:
        eid = _element_id_as_int(el.Id)
        ok, applied_rows, err = apply_suggestions_to_element(
            doc, el, assignments
        )
        if not ok:
            any_error = True
            summary_blocks.append(
                u"Id {0}: ERROR — {1}".format(eid, err)
            )
            continue

        blk = [
            u"Id {0}: aplicadas {1} sugerencia(s).".format(
                eid, len(applied_rows)
            ),
        ]
        for pname, val in applied_rows:
            blk.append(u"  • {0} ← {1}".format(pname, val))
        blk.append(u"  • {0} = \"*\"".format(PARAM_BASE))
        if skipped:
            blk.append(u"  Omitidas en este elemento:")
            for m in skipped:
                blk.append(u"    - {0}".format(m))
        summary_blocks.append(u"\n".join(blk))

    if any_error:
        forms.alert(
            u"Resumen (hubo errores al escribir):\n\n"
            + u"\n\n".join(summary_blocks),
            title=u"Sugerir — resumen",
            warn_icon=True,
        )
    else:
        forms.alert(
            u"\n\n".join(summary_blocks),
            title=u"Sugerir — resumen",
            warn_icon=False,
        )


if __name__ == "__main__":
    main()
