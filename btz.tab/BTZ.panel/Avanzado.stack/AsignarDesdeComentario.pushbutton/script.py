# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "Asignar\nComentario"
__doc__ = (
    "LEGACY manual: asigna BTZ 01/02/03/04 desde Comments "
    "usando catalogo manual + alias."
)
__author__ = "btz.extension"

import os
import re
import sys
import unicodedata
from glob import glob

import clr

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    CategoryType,
    ElementCategoryFilter,
    FilteredElementCollector,
    GroupTypeId,
    LogicalOrFilter,
    Transaction,
)

from pyrevit import forms, revit


_bundle_dir = os.path.dirname(os.path.abspath(__file__))
if _bundle_dir not in sys.path:
    sys.path.insert(0, _bundle_dir)

_manual_dir = os.path.normpath(
    os.path.join(_bundle_dir, u"..", u"AsignarBTZ.pushbutton")
)
if _manual_dir not in sys.path:
    sys.path.insert(0, _manual_dir)
_export_dir = os.path.normpath(
    os.path.join(_bundle_dir, u"..", u"..", u"ExportarGrupos.pushbutton")
)
if _export_dir not in sys.path:
    sys.path.insert(0, _export_dir)

from btz_manual_catalog import load_manual_catalog
from btz_paths import get_public_file


PARAM_BASE = u"BTZ_Description"
PARAM_NUMERIC = [
    u"BTZ_Description_01",
    u"BTZ_Description_02",
    u"BTZ_Description_03",
    u"BTZ_Description_04",
    u"BTZ_Description_05",
    u"BTZ_Description_06",
    u"BTZ_Description_07",
    u"BTZ_Description_08",
    u"BTZ_Description_09",
    u"BTZ_Description_10",
    u"BTZ_Description_11",
    u"BTZ_Description_12",
    u"BTZ_Description_13",
]
ALL_PARAMS = [PARAM_BASE] + PARAM_NUMERIC

ALIAS_MAP = {
    u"dolfin": u"dolphin",
    u"gas oil": u"fuel oil",
    u"gasoil": u"fuel oil",
    u"torre de enfriamiento": u"torres enfriamiento",
    u"torre enfriamiento": u"torres enfriamiento",
    u"vehiculos personal": u"cocheras",
    u"estacionamiento": u"cocheras",
    u"administracion": u"oficinas",
    u"gerencia": u"oficinas",
    u"sala de bombas": u"bombas",
    u"tanques de lecitina": u"lecitina",
}

PLANT_HINTS = {
    u"TE": [u"te", u"terminal", u"terminal embarque"],
    u"PP": [u"pp", u"puerto planta", u"puerto"],
    u"P10": [u"p10", u"planta 1000", u"1000"],
    u"PR": [u"pr", u"ricardone"],
}


def _u(v):
    return unicode(v or u"").strip()


def _norm_text(value):
    text = _u(value).lower()
    if not text:
        return u""
    text = unicodedata.normalize("NFKD", text)
    text = u"".join(ch for ch in text if not unicodedata.combining(ch))
    for src, dst in ALIAS_MAP.items():
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9\s]+", u" ", text)
    text = re.sub(r"\s+", u" ", text).strip()
    return text


def _token_set(value):
    txt = _norm_text(value)
    if not txt:
        return set()
    return set([t for t in txt.split(u" ") if t])


def _resolve_btz_extension_paths():
    found_txt = None
    try:
        from pyrevit import script

        bpaths = script.get_bundle_paths()
        if bpaths:
            for bp in bpaths:
                bp = os.path.abspath(bp)
                ext = os.path.normpath(os.path.join(bp, u"..", u"..", u".."))
                candidate = os.path.join(ext, u"resources", u"BTZ_SharedParameters.txt")
                if os.path.isfile(candidate):
                    found_txt = os.path.normpath(os.path.abspath(candidate))
                    break
    except Exception:
        pass
    if not found_txt:
        d = os.path.dirname(os.path.abspath(__file__))
        for _ in range(14):
            candidate = os.path.join(d, u"resources", u"BTZ_SharedParameters.txt")
            if os.path.isfile(candidate):
                found_txt = os.path.normpath(os.path.abspath(candidate))
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    if not found_txt:
        base = os.path.dirname(os.path.abspath(__file__))
        ext = os.path.normpath(os.path.abspath(os.path.join(base, u"..", u"..", u"..")))
        found_txt = os.path.normpath(os.path.join(ext, u"resources", u"BTZ_SharedParameters.txt"))
    res_dir = os.path.dirname(found_txt)
    ext_dir = os.path.dirname(res_dir)
    return ext_dir, res_dir, found_txt


EXT_DIR, RESOURCES_DIR, SHARED_PARAMS_FILE = _resolve_btz_extension_paths()
PUBLIC_DIR = os.path.normpath(os.path.join(EXT_DIR, u"public"))


def _catalog_candidate_paths():
    corrected_alt = os.path.join(PUBLIC_DIR, u"sectores_subsectores_btz_manual (2).csv")
    base = [
        corrected_alt,
        get_public_file(u"sectores_subsectores_btz_manual.csv", u"optional", fallback=True),
        os.path.join(RESOURCES_DIR, u"sectores_subsectores_btz_manual.csv"),
    ]
    base.extend(
        sorted(
            glob(
                os.path.join(
                    os.path.dirname(
                        get_public_file(
                            u"sectores_subsectores_btz_manual.csv",
                            u"optional",
                            fallback=False,
                        )
                    ),
                    u"sectores_subsectores_btz_manual*.csv",
                )
            )
        )
    )
    base.extend(sorted(glob(os.path.join(RESOURCES_DIR, u"sectores_subsectores_btz_manual*.csv"))))
    unique = []
    seen = set()
    for p in base:
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        unique.append(ap)
    return unique


def _get_comment(element):
    p = element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p and p.HasValue:
        try:
            text = p.AsString()
            if _u(text):
                return _u(text)
        except Exception:
            pass
    alt = element.LookupParameter(u"Comments") or element.LookupParameter(u"Comentarios")
    if alt and alt.HasValue:
        try:
            return _u(alt.AsString())
        except Exception:
            pass
    return u""


def _read_selected_or_all_targets(doc, uidoc):
    picked_ids = list(uidoc.Selection.GetElementIds())
    allowed_ids = set(
        [
            int(BuiltInCategory.OST_Roofs),
            int(BuiltInCategory.OST_GenericModel),
        ]
    )
    out = []
    if picked_ids:
        for eid in picked_ids:
            el = doc.GetElement(eid)
            if not el or not el.Category:
                continue
            cid = int(el.Category.Id.Value if hasattr(el.Category.Id, 'Value') else el.Category.Id.IntegerValue)
            if cid in allowed_ids:
                out.append(el)
        return out

    roof_filter = ElementCategoryFilter(BuiltInCategory.OST_Roofs)
    gm_filter = ElementCategoryFilter(BuiltInCategory.OST_GenericModel)
    or_filter = LogicalOrFilter(roof_filter, gm_filter)
    return list(
        FilteredElementCollector(doc)
        .WherePasses(or_filter)
        .WhereElementIsNotElementType()
        .ToElements()
    )


def _detect_plant_hint(comment_norm):
    tokens = _token_set(comment_norm)
    for pcode, hints in PLANT_HINTS.items():
        for hint in hints:
            h = _norm_text(hint)
            if not h:
                continue
            if h in comment_norm or h in tokens:
                return pcode
    return u""


def _build_index(catalog):
    entries = []
    for p in catalog.get(u"plants", {}).values():
        pcode = _u(p.get(u"code")).upper()
        pname = _u(p.get(u"name"))
        for s in p.get(u"sectors", {}).values():
            skey = _u(s.get(u"key")).upper()
            swrite = _u(s.get(u"write_code")).upper()
            sname = _u(s.get(u"name"))
            entries.append(
                {
                    u"type": u"sector",
                    u"plant_code": pcode,
                    u"plant_name": pname,
                    u"sector_key": skey,
                    u"sector_code": swrite,
                    u"sector_name": sname,
                    u"subsector_code": u"",
                    u"subsector_name": u"",
                    u"unit_code": u"",
                    u"unit_name": u"",
                    u"search": _norm_text(u" ".join([pcode, pname, skey, swrite, sname])),
                }
            )
            for ss in s.get(u"subsectors", {}).values():
                sscode = _u(ss.get(u"code")).upper()
                ssname = _u(ss.get(u"name"))
                entries.append(
                    {
                        u"type": u"subsector",
                        u"plant_code": pcode,
                        u"plant_name": pname,
                        u"sector_key": skey,
                        u"sector_code": swrite,
                        u"sector_name": sname,
                        u"subsector_code": sscode,
                        u"subsector_name": ssname,
                        u"unit_code": u"",
                        u"unit_name": u"",
                        u"search": _norm_text(
                            u" ".join([pcode, pname, skey, swrite, sname, sscode, ssname])
                        ),
                    }
                )
                for uu in (ss.get(u"units") or {}).values():
                    ucode = _u(uu.get(u"code")).upper()
                    uname = _u(uu.get(u"name"))
                    entries.append(
                        {
                            u"type": u"unit",
                            u"plant_code": pcode,
                            u"plant_name": pname,
                            u"sector_key": skey,
                            u"sector_code": swrite,
                            u"sector_name": sname,
                            u"subsector_code": sscode,
                            u"subsector_name": ssname,
                            u"unit_code": ucode,
                            u"unit_name": uname,
                            u"search": _norm_text(
                                u" ".join(
                                    [
                                        pcode,
                                        pname,
                                        skey,
                                        swrite,
                                        sname,
                                        sscode,
                                        ssname,
                                        ucode,
                                        uname,
                                    ]
                                )
                            ),
                        }
                    )
    return entries


def _score_entry(comment_norm, comment_tokens, entry, plant_hint):
    target = entry.get(u"search", u"")
    if not target:
        return -999
    score = 0
    if comment_norm in target:
        score += 30
    if target in comment_norm:
        score += 40
    target_tokens = set([t for t in target.split(u" ") if t])
    overlap = len(comment_tokens.intersection(target_tokens))
    score += overlap * 7
    if entry.get(u"type") == u"subsector":
        score += 12
    elif entry.get(u"type") == u"unit":
        score += 20
    if plant_hint:
        if _u(entry.get(u"plant_code")).upper() == plant_hint:
            score += 20
        else:
            score -= 15
    return score


def _build_short_tag_index(catalog_index):
    """Mapea 'te-caladocamiones' -> entry, 'te-sectorbalanzaosl' -> entry, etc.
    Usa solo el nombre propio de cada nivel (sin heredar padre) para evitar falsos positivos."""
    tag_map = {}
    for entry in catalog_index:
        plant = re.sub(r"[^a-z0-9]", u"", _norm_text(_u(entry.get(u"plant_code"))))
        if not plant:
            continue
        entry_type = entry.get(u"type", u"")
        if entry_type == u"unit":
            own_nm = _u(entry.get(u"unit_name"))
        elif entry_type == u"subsector":
            own_nm = _u(entry.get(u"subsector_name"))
        else:
            own_nm = _u(entry.get(u"sector_name"))
        compact = re.sub(r"[^a-z0-9]", u"", _norm_text(own_nm))
        if compact and len(compact) >= 2:
            tag = plant + u"-" + compact
            if tag not in tag_map:
                tag_map[tag] = entry
    return tag_map


def _tag_lookup(comment_norm, tag_index):
    """Busca coincidencia exacta o parcial en el indice de tags compactos.
    Retorna (entry, True) o (None, False)."""
    parts = comment_norm.split()
    if len(parts) < 2:
        return None, False
    plant_part = parts[0]
    keyword = u"".join(parts[1:])
    tag_candidate = plant_part + u"-" + keyword

    if tag_candidate in tag_index:
        return tag_index[tag_candidate], True

    if len(keyword) < 4:
        return None, False

    prefix = plant_part + u"-"
    candidates = []
    for tag, entry in tag_index.items():
        if not tag.startswith(prefix):
            continue
        tag_kw = tag[len(prefix):]
        if keyword in tag_kw or tag_kw in keyword:
            match_len = min(len(keyword), len(tag_kw))
            candidates.append((match_len, tag_kw, entry))

    if not candidates:
        return None, False
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_len = candidates[0][0]
    if len(candidates) >= 2 and candidates[1][0] >= best_len - 2:
        return None, False
    return candidates[0][2], True


def _match_comment(comment_text, index, tag_index=None):
    comment_norm = _norm_text(comment_text)
    if not comment_norm:
        return None, u"sin_comentario"

    if tag_index:
        entry, found = _tag_lookup(comment_norm, tag_index)
        if found:
            return entry, u"ok"

    comment_tokens = _token_set(comment_norm)
    plant_hint = _detect_plant_hint(comment_norm)

    scored = []
    for e in index:
        sc = _score_entry(comment_norm, comment_tokens, e, plant_hint)
        if sc > 0:
            scored.append((sc, e))
    if not scored:
        return None, u"sin_match"
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else -999
    if best_score < 20:
        return None, u"confianza_baja"
    if second_score >= best_score - 6:
        return None, u"ambiguo"
    return best, u"ok"


def alert(msg, title=u"BTZ"):
    try:
        forms.alert(unicode(msg), title=title, warn_icon=False)
    except Exception:
        print(u"{0}: {1}".format(title, msg))


def _param_value_as_string(element, param_name):
    p = element.LookupParameter(param_name)
    if p is None or not p.HasValue:
        return u""
    try:
        s = p.AsString()
        if s is not None:
            return unicode(s)
    except Exception:
        pass
    return u""


def set_text_parameter(element, param_name, value):
    p = element.LookupParameter(param_name)
    if not p:
        return False, u"sin_parametro"
    if p.IsReadOnly:
        return False, u"solo_lectura"
    try:
        p.Set(_u(value).upper())
        return True, None
    except Exception as ex:
        return False, unicode(ex)


def get_definition_map(def_file):
    defs = {}
    for group in def_file.Groups:
        for definition in group.Definitions:
            try:
                name = definition.Name
            except Exception:
                name = None
            if name:
                defs[name] = definition
    return defs


def build_model_category_set(doc):
    catset = doc.Application.Create.NewCategorySet()
    count = 0
    for cat in doc.Settings.Categories:
        try:
            if cat is None or not cat.AllowsBoundParameters or cat.IsTagCategory:
                continue
            if cat.CategoryType != CategoryType.Model:
                continue
            catset.Insert(cat)
            count += 1
        except Exception:
            pass
    if count == 0:
        raise ValueError(u"No se pudo armar CategorySet de categorias de modelo.")
    return catset


def get_existing_binding_names(doc):
    names = set()
    it = doc.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        try:
            definition = it.Key
            if definition and definition.Name:
                names.add(definition.Name)
        except Exception:
            pass
    return names


def ensure_shared_parameters(doc, shared_params_path):
    if not shared_params_path or not os.path.isfile(shared_params_path):
        raise IOError(u"No se encontro TXT shared parameters: {0}".format(shared_params_path))
    app = doc.Application
    app.SharedParametersFilename = shared_params_path
    def_file = app.OpenSharedParameterFile()
    if def_file is None:
        raise IOError(u"Revit no pudo abrir el archivo de shared parameters.")
    definition_map = get_definition_map(def_file)
    missing = [name for name in ALL_PARAMS if name not in definition_map]
    if missing:
        raise ValueError(u"Faltan parametros en el TXT: {0}".format(u", ".join(missing)))
    catset = build_model_category_set(doc)
    creator = doc.Application.Create
    existing_names = get_existing_binding_names(doc)
    tx = Transaction(doc, u"BTZ | Vincular shared parameters")
    tx.Start()
    try:
        for name in ALL_PARAMS:
            definition = definition_map[name]
            binding = creator.NewInstanceBinding(catset)
            if name in existing_names:
                doc.ParameterBindings.ReInsert(definition, binding, GroupTypeId.Text)
            else:
                ok = doc.ParameterBindings.Insert(definition, binding, GroupTypeId.Text)
                if not ok:
                    doc.ParameterBindings.ReInsert(definition, binding, GroupTypeId.Text)
        tx.Commit()
    except Exception:
        tx.RollBack()
        raise


def main():
    doc = revit.doc
    uidoc = revit.uidoc
    if not doc or not uidoc:
        alert(u"No hay documento activo.", u"BTZ")
        return

    try:
        ensure_shared_parameters(doc, SHARED_PARAMS_FILE)
    except Exception as ex:
        alert(u"No se pudieron vincular shared parameters.\n\n{0}".format(ex), u"BTZ")
        return

    catalog_paths = _catalog_candidate_paths()
    try:
        catalog = load_manual_catalog(catalog_paths)
    except Exception as ex:
        alert(u"No se pudo cargar catalogo manual.\n\n{0}".format(ex), u"BTZ comentario")
        return

    index = _build_index(catalog)
    tag_index = _build_short_tag_index(index)
    elements = _read_selected_or_all_targets(doc, uidoc)
    if not elements:
        alert(u"No hay elementos de Techo/Modelo generico para procesar.", u"BTZ comentario")
        return

    overwrite = forms.CommandSwitchWindow.show(
        [u"Si", u"No"],
        message=u"Sobrescribir BTZ existentes en elementos ya clasificados?",
        title=u"BTZ comentario",
    )
    if overwrite is None:
        return
    overwrite = overwrite == u"Si"

    planned = []
    issues = []
    for el in elements:
        comment = _get_comment(el)
        try:
            eid = unicode(el.Id.Value if hasattr(el.Id, 'Value') else el.Id.IntegerValue)
        except Exception:
            eid = u"?"
        match, reason = _match_comment(comment, index, tag_index)
        if not match:
            if _u(comment):
                issues.append(u"Id {0}: {1} -> {2}".format(eid, comment, reason))
            continue
        planned.append((el, comment, match))

    if not planned:
        msg = [u"No se encontraron coincidencias para asignar."]
        if issues:
            msg.append(u"")
            msg.append(u"Muestras:")
            msg.extend(issues[:12])
        alert(u"\n".join(msg), u"BTZ comentario")
        return

    tx = Transaction(doc, u"BTZ | Asignar desde comentario")
    tx.Start()
    modified = 0
    unchanged = 0
    skipped_existing = 0
    errors = []
    try:
        for el, comment, m in planned:
            c1 = _u(_param_value_as_string(el, u"BTZ_Description_01")).upper()
            c2 = _u(_param_value_as_string(el, u"BTZ_Description_02")).upper()
            c3 = _u(_param_value_as_string(el, u"BTZ_Description_03")).upper()
            c4 = _u(_param_value_as_string(el, u"BTZ_Description_04")).upper()
            p1 = _u(m.get(u"plant_code")).upper()
            p2 = _u(m.get(u"sector_code")).upper()
            p3 = _u(m.get(u"subsector_code")).upper()
            p4 = _u(m.get(u"unit_code")).upper()
            if c1 == p1 and c2 == p2 and c3 == p3 and c4 == p4:
                unchanged += 1
                continue
            if (c1 or c2 or c3 or c4) and not overwrite:
                skipped_existing += 1
                continue
            ok1, e1 = set_text_parameter(el, u"BTZ_Description_01", p1)
            ok2, e2 = set_text_parameter(el, u"BTZ_Description_02", p2)
            ok3, e3 = set_text_parameter(el, u"BTZ_Description_03", p3)
            ok4, e4 = set_text_parameter(el, u"BTZ_Description_04", p4)
            if not (ok1 and ok2 and ok3 and ok4):
                try:
                    eid = unicode(el.Id.Value if hasattr(el.Id, 'Value') else el.Id.IntegerValue)
                except Exception:
                    eid = u"?"
                errors.append(
                    u"Id {0}: {1}".format(
                        eid,
                        u" | ".join([_u(x) for x in [e1, e2, e3, e4] if _u(x)]),
                    )
                )
                continue
            modified += 1
        tx.Commit()
    except Exception:
        tx.RollBack()
        raise

    msg = [
        u"Catalogo usado: {0}".format(catalog.get(u"source_path", u"")),
        u"Elementos candidatos (Techo/Modelo generico): {0}".format(len(elements)),
        u"Coincidencias por comentario: {0}".format(len(planned)),
        u"Elementos modificados: {0}".format(modified),
        u"Sin cambios: {0}".format(unchanged),
        u"Saltados por existentes: {0}".format(skipped_existing),
        u"Sin match / ambiguos: {0}".format(len(issues)),
    ]
    if issues:
        msg.append(u"")
        msg.append(u"Ejemplos sin match:")
        msg.extend(issues[:10])
    if errors:
        msg.append(u"")
        msg.append(u"Errores:")
        msg.extend(errors[:10])
    alert(u"\n".join(msg), u"BTZ comentario listo")


if __name__ == "__main__":
    main()
